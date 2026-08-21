from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def _write_txt2img(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "prompt": {
                    "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "hello"}},
                    "2": {"class_type": "SaveImage", "inputs": {"filename_prefix": "sample"}},
                }
            }
        ),
        encoding="utf-8",
    )


class MultiBackendContractTests(unittest.TestCase):
    def _app(self, root: Path, extra_env: dict[str, str] | None = None):
        workflows = root / "workflows"
        runs = root / "runs"
        data = root / "data"
        workflows.mkdir(parents=True, exist_ok=True)
        runs.mkdir(parents=True, exist_ok=True)
        data.mkdir(parents=True, exist_ok=True)
        _write_txt2img(workflows / "demo.json")
        env = {
            "API_TOKEN": "api-token",
            "ADMIN_TOKEN": "admin-token",
            "DATA_DIR": str(data),
            "DATABASE_PATH": str(data / "tasks.db"),
            "ENABLE_WORKFLOW_WATCH": "0",
            "RUNS_DIR": str(runs),
            "WORKFLOWS_DIR": str(workflows),
        }
        if extra_env:
            env.update(extra_env)
        patcher = patch.dict(os.environ, env, clear=False)
        patcher.start()
        import comfyui2api.app as app_module

        app = importlib.reload(app_module).create_app()
        self.addCleanup(patcher.stop)
        return app

    def test_zero_instances_lists_no_models_and_unknown_model_is_404(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = self._app(Path(tmp))
            with TestClient(app) as client:
                listed = client.get("/v1/models", headers={"Authorization": "Bearer api-token"})
                self.assertEqual(listed.status_code, 200)
                self.assertEqual(listed.json()["data"], [])
                missing = client.post(
                    "/v1/images/generations",
                    headers={"Authorization": "Bearer api-token", "x-comfyui-async": "1"},
                    json={"prompt": "cat", "model": "missing"},
                )
                self.assertEqual(missing.status_code, 404)
                self.assertEqual(missing.json()["error"]["code"], "model_not_found")

    def test_enabled_model_without_healthy_backend_is_503(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = self._app(Path(tmp))
            with TestClient(app) as client:
                created = client.post(
                    "/v1/admin/instances",
                    headers={"Authorization": "Bearer admin-token"},
                    json={"slug": "gpu-a", "base_url": "http://127.0.0.1:18188"},
                )
                self.assertEqual(created.status_code, 200)
                model = client.post(
                    "/v1/admin/models",
                    headers={"Authorization": "Bearer admin-token"},
                    json={
                        "slug": "demo",
                        "workflow_name": "demo.json",
                        "enabled": True,
                        "instance_slugs": ["gpu-a"],
                    },
                )
                self.assertEqual(model.status_code, 200)
                listed = client.get("/v1/models", headers={"Authorization": "Bearer api-token"})
                item = listed.json()["data"][0]
                self.assertEqual(item["id"], "demo")
                self.assertFalse(item["ready"])
                response = client.post(
                    "/v1/images/generations",
                    headers={"Authorization": "Bearer api-token", "x-comfyui-async": "1"},
                    json={"prompt": "cat", "model": "demo"},
                )
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()["error"]["code"], "no_available_backend")

    def test_missing_workflow_file_returns_workflow_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = self._app(Path(tmp))
            with TestClient(app) as client:
                client.post(
                    "/v1/admin/instances",
                    headers={"Authorization": "Bearer admin-token"},
                    json={"slug": "gpu-a", "base_url": "http://127.0.0.1:18188"},
                )
                created = client.post(
                    "/v1/admin/models",
                    headers={"Authorization": "Bearer admin-token"},
                    json={"slug": "demo", "workflow_name": "demo.json", "enabled": False, "instance_slugs": ["gpu-a"]},
                )
                self.assertEqual(created.status_code, 200)
                (Path(tmp) / "workflows" / "demo.json").unlink()
                import asyncio

                asyncio.run(app.state.registry.load_all())
                enabled = client.patch(
                    "/v1/admin/models/demo",
                    headers={"Authorization": "Bearer admin-token"},
                    json={"enabled": True},
                )
                self.assertEqual(enabled.status_code, 400)

    def test_admin_auth_limiter_returns_429_after_ten_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = self._app(Path(tmp))
            with TestClient(app) as client:
                for _ in range(10):
                    failed = client.get("/v1/admin/stats", headers={"Authorization": "Bearer wrong"})
                    self.assertEqual(failed.status_code, 401)
                blocked = client.get("/v1/admin/stats", headers={"Authorization": "Bearer wrong"})
                self.assertEqual(blocked.status_code, 429)

    def test_public_workflows_removed_admin_workflows_remain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = self._app(Path(tmp))
            with TestClient(app) as client:
                public = client.get("/v1/workflows", headers={"Authorization": "Bearer api-token"})
                self.assertEqual(public.status_code, 404)
                admin = client.get("/v1/admin/workflows", headers={"Authorization": "Bearer admin-token"})
                self.assertEqual(admin.status_code, 200)
                names = [item["name"] for item in admin.json()["items"]]
                self.assertIn("demo.json", names)
