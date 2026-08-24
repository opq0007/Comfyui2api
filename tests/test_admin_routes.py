from __future__ import annotations

import asyncio
import importlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from comfyui2api.jobs import Job, JobOutput


class AdminRoutesTests(unittest.TestCase):
    def _app_with_env(self, root: Path, *, ui_built: bool = True):
        workflows = root / "workflows"
        runs = root / "runs"
        data = root / "data"
        ui_dist = root / "ui"
        workflows.mkdir(parents=True, exist_ok=True)
        runs.mkdir(parents=True, exist_ok=True)
        data.mkdir(parents=True, exist_ok=True)
        if ui_built:
            (ui_dist / "assets").mkdir(parents=True, exist_ok=True)
            (ui_dist / "index.html").write_text(
                '<html><body>dashboard<script type="module" src="/ui/assets/app.js"></script></body></html>',
                encoding="utf-8",
            )
            (ui_dist / "assets" / "app.js").write_text("window.__comfyui2api = true;\n", encoding="utf-8")

        env = {
            "ADMIN_TOKEN": "admin-token",
            "API_TOKEN": "api-token",
            "COMFYUI2API_UI_DIST_DIR": str(ui_dist),
            "DATA_DIR": str(data),
            "DATABASE_PATH": str(data / "tasks.db"),
            "ENABLE_WORKFLOW_WATCH": "0",
            "RUNS_DIR": str(runs),
            "WORKFLOWS_DIR": str(workflows),
        }
        patcher = patch.dict(os.environ, env, clear=False)
        patcher.start()
        import comfyui2api.app as app_module

        app = importlib.reload(app_module).create_app()
        self.addCleanup(patcher.stop)
        return app

    def test_admin_tasks_require_token_and_return_filters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = self._app_with_env(Path(tmp))
            with TestClient(app) as client:
                job = Job(
                    job_id="task_admin",
                    created_at=1780000000,
                    created_at_utc="2026-05-29T00:19:20Z",
                    status="completed",
                    kind="txt2img",
                    workflow="wf.json",
                    platform="OpenAI",
                    prompt_id="prompt_admin",
                    progress_percent=100,
                    url="/runs/task_admin/out.png",
                    outputs=[
                        JobOutput(
                            filename="out.png",
                            url="/runs/task_admin/out.png",
                            media_type="image/png",
                            node_id="1",
                            output_key="images",
                        )
                    ],
                )
                asyncio.run(app.state.job_store.upsert_job(job))
                asyncio.run(app.state.job_store.replace_outputs(job.job_id, job.outputs))

                unauthorized = client.get("/v1/admin/tasks")
                self.assertEqual(unauthorized.status_code, 401)

                response = client.get(
                    "/v1/admin/tasks?status=completed&kind=txt2img&platform=OpenAI&q=prompt_admin",
                    headers={"Authorization": "Bearer admin-token"},
                )
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["total"], 1)
                self.assertEqual(payload["items"][0]["job_id"], "task_admin")
                self.assertIn("/runs/task_admin/out.png", payload["items"][0]["url"])
                self.assertIn("sig=", payload["items"][0]["url"])

                detail = client.get("/v1/admin/tasks/task_admin", headers={"Authorization": "Bearer admin-token"})
                self.assertEqual(detail.status_code, 200)
                output_url = detail.json()["outputs"][0]["url"]
                self.assertIn("/runs/task_admin/out.png", output_url)
                self.assertIn("sig=", output_url)

    def test_admin_ws_sends_snapshot_and_rejects_missing_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = self._app_with_env(Path(tmp))
            with TestClient(app) as client:
                # Missing-token connection: server accepts, sends a JSON error
                # frame, and closes with policy-violation code 1008.
                with client.websocket_connect("/v1/admin/tasks/ws") as ws:
                    error = ws.receive_json()
                    self.assertEqual(error["type"], "error")
                    self.assertEqual(error["data"]["status"], 401)
                    with self.assertRaises(WebSocketDisconnect) as ctx:
                        ws.receive_json()
                self.assertEqual(ctx.exception.code, 1008)

                with client.websocket_connect("/v1/admin/tasks/ws?token=admin-token") as ws:
                    payload = ws.receive_json()
                self.assertEqual(payload["type"], "snapshot")

    def test_admin_ws_rejects_wrong_token_with_structured_error(self) -> None:
        """Wrong-token WebSocket connections must be closed with a structured
        JSON error frame AND a 1008 close code. They must NOT cause uvicorn to
        emit an HTTP 403 in the handshake."""
        with tempfile.TemporaryDirectory() as tmp:
            app = self._app_with_env(Path(tmp))
            with TestClient(app) as client:
                with client.websocket_connect(
                    "/v1/admin/tasks/ws?token=WRONG-TOKEN"
                ) as ws:
                    error = ws.receive_json()
                    self.assertEqual(error["type"], "error")
                    self.assertEqual(error["data"]["status"], 401)
                    with self.assertRaises(WebSocketDisconnect) as ctx:
                        ws.receive_json()
                self.assertEqual(ctx.exception.code, 1008)

    def test_admin_rest_401_when_admin_token_missing(self) -> None:
        """Server-side misconfiguration (no ADMIN_TOKEN) must raise ConfigError
        at startup time, not silently let unauthenticated requests through."""
        with tempfile.TemporaryDirectory() as tmp:
            workflows = Path(tmp) / "workflows"
            runs = Path(tmp) / "runs"
            data = Path(tmp) / "data"
            ui_dist = Path(tmp) / "ui"
            for d in (workflows, runs, data, ui_dist):
                d.mkdir(parents=True, exist_ok=True)
            (ui_dist / "index.html").write_text("<html></html>", encoding="utf-8")
            env = {
                # Deliberately do NOT set ADMIN_TOKEN
                "API_TOKEN": "api-token",
                "COMFYUI2API_UI_DIST_DIR": str(ui_dist),
                "DATA_DIR": str(data),
                "DATABASE_PATH": str(data / "tasks.db"),
                "ENABLE_WORKFLOW_WATCH": "0",
                "RUNS_DIR": str(runs),
                "WORKFLOWS_DIR": str(workflows),
            }
            patcher = patch.dict(os.environ, env, clear=False)
            patcher.start()
            try:
                # ADMIN_TOKEN must NOT be in the process env for this assertion
                os.environ.pop("ADMIN_TOKEN", None)
                with self.assertRaises(Exception) as ctx:
                    from comfyui2api.config import load_config
                    load_config()
                self.assertIn("ADMIN_TOKEN", str(ctx.exception))
            finally:
                patcher.stop()

    def test_admin_auth_logs_misconfiguration(self) -> None:
        """When ADMIN_TOKEN is configured but the Authorization header is
        missing, we return 401 and do NOT log a 'misconfiguration' warning."""
        with tempfile.TemporaryDirectory() as tmp:
            app = self._app_with_env(Path(tmp))
            with TestClient(app) as client:
                with self.assertLogs("comfyui2api.admin_routes", level="INFO") as cm:
                    r = client.get("/v1/admin/tasks")
                self.assertEqual(r.status_code, 401)
                # The missing-header case logs at INFO, not WARNING
                self.assertFalse(
                    any("not configured" in m for m in cm.output),
                    msg=f"Did not expect a misconfiguration warning: {cm.output}",
                )

    @unittest.skipUnless(shutil.which("powershell"), "powershell not available")
    def test_start_ps1_import_envfile_parses_utf8_with_chinese_comments(self) -> None:
        """Regression test for the .env parsing bug in start.ps1.

        The legacy Import-EnvFile read .env with the active ANSI codepage,
        which truncated UTF-8 lines at the first non-ASCII character and
        skipped every line that began with '#'. The result: ADMIN_TOKEN,
        WORKFLOWS_DIR, RUNS_DIR, ENABLE_WORKFLOW_WATCH and several others
        never made it into the process environment, so the Python child
        silently fell back to defaults (or, worse, picked up a stale value).

        The fixed parser:
          * reads .env as raw UTF-8 bytes (via [System.IO.File]::ReadAllBytes),
            tolerating an optional UTF-8 BOM,
          * strips an optional leading '#' comment marker so a documented
            "ADMIN_TOKEN=..." inline still parses,
          * skips empty values so they don't shadow the real .env values
            via python-dotenv's ``override=False``.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_path = tmp_path / ".env"
            # Fixture mirrors the bug-trigger shape from the real-world .env:
            # a Chinese comment line that ends with the literal "ADMIN_TOKEN=..."
            # text, followed by the actual assignment on the next line.
            env_path.write_text(
                "\n".join(
                    [
                        "### API 监听地址",
                        "API_LISTEN=0.0.0.0",
                        "",
                        "### 必填：业务接口 Authorization: Bearer <token>",
                        "API_TOKEN=opq007sb",
                        "",
                        "### 必填：管理台 /v1/admin 与 /ui 密钥门 ADMIN_TOKEN=opq007sb",
                        "ADMIN_TOKEN=opq007sb",
                        "",
                        "### 工作流目录（ComfyUI File -> Export (API) 导出的 JSON）",
                        "WORKFLOWS_DIR=./comfyui-api-workflows",
                        "",
                        "### 运行产物目录（任务输出会保存到 RUNS_DIR/<job_id>/）",
                        "RUNS_DIR=./runs",
                        "",
                        "PUBLIC_BASE_URL=",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            # Extract the Import-EnvFile function from the real start.ps1
            source = (Path(__file__).resolve().parents[1] / "start.ps1").read_text(
                encoding="utf-8"
            )
            start = source.index("function Import-EnvFile")
            depth = 0
            end = start
            for idx in range(start, len(source)):
                ch = source[idx]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = idx + 1
                        break
            function_dump = tmp_path / "import_envfile.ps1"
            function_dump.write_text(source[start:end], encoding="utf-8")

            # Verify the fix is actually present. The legacy parser used
            # Get-Content which silently corrupts UTF-8; the fixed parser
            # uses [System.IO.File]::ReadAllBytes which is encoding-safe.
            function_body = function_dump.read_text(encoding="utf-8")
            self.assertIn(
                "ReadAllBytes",
                function_body,
                msg="Import-EnvFile must read the .env file as raw UTF-8 bytes",
            )

            checker = tmp_path / "checker.ps1"
            checker.write_text(
                "\n".join(
                    [
                        "param([string]$EnvFile, [string]$FnFile)",
                        "$ErrorActionPreference = 'Stop'",
                        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8",
                        f". \"{function_dump}\"",
                        "[Environment]::SetEnvironmentVariable('__TEST_DUMMY','preserve','Process')",
                        "Import-EnvFile -Path $EnvFile",
                        "foreach ($k in @('API_TOKEN','ADMIN_TOKEN','API_LISTEN','WORKFLOWS_DIR','RUNS_DIR','__TEST_DUMMY')) {",
                        "  $v = [Environment]::GetEnvironmentVariable($k, 'Process')",
                        "  Write-Host (\"KEY={0}::{1}\" -f $k, $v)",
                        "}",
                    ]
                ),
                encoding="utf-8",
            )

            proc = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(checker),
                    "-EnvFile",
                    str(env_path),
                    "-FnFile",
                    str(function_dump),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            seen = {}
            for line in proc.stdout.splitlines():
                if line.startswith("KEY=") and "::" in line:
                    name, _, value = line[len("KEY="):].partition("::")
                    seen[name] = value

            self.assertEqual(seen.get("API_TOKEN"), "opq007sb")
            self.assertEqual(seen.get("ADMIN_TOKEN"), "opq007sb")
            self.assertEqual(seen.get("API_LISTEN"), "0.0.0.0")
            self.assertEqual(seen.get("WORKFLOWS_DIR"), "./comfyui-api-workflows")
            self.assertEqual(seen.get("RUNS_DIR"), "./runs")
            # Pre-existing process env vars must be preserved.
            self.assertEqual(seen.get("__TEST_DUMMY"), "preserve")

    @unittest.skipUnless(shutil.which("powershell"), "powershell not available")
    def test_start_ps1_import_envfile_handles_bom(self) -> None:
        """Import-EnvFile must tolerate a UTF-8 BOM at the start of the file.

        Some Windows tools (PowerShell Out-File, Notepad save-as UTF-8) emit
        a BOM by default. The legacy parser passed the file through
        Get-Content which silently corrupted the rest of the file because
        of the BOM bytes; the fixed parser strips them up front.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_path = tmp_path / ".env"
            env_path.write_bytes(
                b"\xef\xbb\xbf"  # UTF-8 BOM
                + "ADMIN_TOKEN=opq007sb\nAPI_TOKEN=opq007sb\n".encode("utf-8")
            )

            source = (Path(__file__).resolve().parents[1] / "start.ps1").read_text(
                encoding="utf-8"
            )
            start = source.index("function Import-EnvFile")
            depth = 0
            end = start
            for idx in range(start, len(source)):
                ch = source[idx]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = idx + 1
                        break
            function_dump = tmp_path / "import_envfile.ps1"
            function_dump.write_text(source[start:end], encoding="utf-8")

            checker = tmp_path / "checker.ps1"
            checker.write_text(
                "\n".join(
                    [
                        "param([string]$EnvFile, [string]$FnFile)",
                        "$ErrorActionPreference = 'Stop'",
                        f". \"{function_dump}\"",
                        "Import-EnvFile -Path $EnvFile",
                        "foreach ($k in @('API_TOKEN','ADMIN_TOKEN')) {",
                        "  $v = [Environment]::GetEnvironmentVariable($k, 'Process')",
                        "  Write-Host (\"KEY={0}::{1}\" -f $k, $v)",
                        "}",
                    ]
                ),
                encoding="utf-8",
            )

            proc = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(checker),
                    "-EnvFile",
                    str(env_path),
                    "-FnFile",
                    str(function_dump),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            seen = {}
            for line in proc.stdout.splitlines():
                if line.startswith("KEY=") and "::" in line:
                    name, _, value = line[len("KEY="):].partition("::")
                    seen[name] = value

            # With the BOM stripped, ADMIN_TOKEN/API_TOKEN must be clean values,
            # not something like "\ufeffopq007sb" that would silently fail auth.
            self.assertEqual(seen.get("API_TOKEN"), "opq007sb")
            self.assertEqual(seen.get("ADMIN_TOKEN"), "opq007sb")

    def test_admin_shutdown_requires_token_and_local_callback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = self._app_with_env(Path(tmp))
            called = False

            def shutdown_callback() -> None:
                nonlocal called
                called = True

            app.state.shutdown_callback = shutdown_callback
            with TestClient(app, client=("127.0.0.1", 50000)) as client:
                unauthorized = client.post("/v1/admin/shutdown")
                self.assertEqual(unauthorized.status_code, 401)

                response = client.post("/v1/admin/shutdown", headers={"Authorization": "Bearer admin-token"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["status"], "shutting_down")
                time.sleep(0.4)

            self.assertTrue(called)

    def test_ui_mount_built_and_missing_states(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = self._app_with_env(Path(tmp), ui_built=True)
            with TestClient(app) as client:
                response = client.get("/ui")
                self.assertEqual(response.status_code, 200)
                self.assertIn("dashboard", response.text)
                self.assertIn("text/html", response.headers.get("content-type", "").lower())

                asset = client.get("/ui/assets/app.js")
                self.assertEqual(asset.status_code, 200)
                self.assertIn("window.__comfyui2api", asset.text)
                content_type = asset.headers.get("content-type", "").lower()
                self.assertTrue(
                    content_type.startswith("text/javascript") or content_type.startswith("application/javascript"),
                    msg=f"ES modules require a JavaScript MIME type, got {content_type!r}",
                )

        with tempfile.TemporaryDirectory() as tmp:
            import mimetypes

            from comfyui2api.webui import ensure_web_asset_mimetypes

            mimetypes.add_type("text/plain", ".js")
            self.assertEqual(mimetypes.guess_type("asset.js")[0], "text/plain")
            ensure_web_asset_mimetypes()
            self.assertEqual(mimetypes.guess_type("asset.js")[0], "text/javascript")

            app = self._app_with_env(Path(tmp), ui_built=True)
            with TestClient(app) as client:
                asset = client.get("/ui/assets/app.js")
                self.assertEqual(asset.status_code, 200)
                content_type = asset.headers.get("content-type", "").lower()
                self.assertTrue(
                    content_type.startswith("text/javascript") or content_type.startswith("application/javascript"),
                    msg=f"Windows text/plain override must not leak to /ui/assets, got {content_type!r}",
                )

        with tempfile.TemporaryDirectory() as tmp:
            app = self._app_with_env(Path(tmp), ui_built=False)
            with TestClient(app) as client:
                response = client.get("/ui")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["error"], "Web UI has not been built.")


if __name__ == "__main__":
    unittest.main()
