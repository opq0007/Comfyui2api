from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from comfyui2api.comfy_client import (
    ComfyApiError,
    ComfyUIClient,
    extract_history_entry,
    history_entry_error,
    history_entry_is_complete,
)


class ComfyClientTests(unittest.IsolatedAsyncioTestCase):
    def test_local_loopback_client_bypasses_system_proxy(self) -> None:
        with patch("comfyui2api.comfy_client.httpx.AsyncClient") as mock_client:
            ComfyUIClient("http://127.0.0.1:8188")
        self.assertFalse(mock_client.call_args.kwargs["trust_env"])

    def test_remote_client_keeps_trust_env_enabled(self) -> None:
        with patch("comfyui2api.comfy_client.httpx.AsyncClient") as mock_client:
            ComfyUIClient("https://example.com")
        self.assertTrue(mock_client.call_args.kwargs["trust_env"])

    async def test_queue_prompt_http_error_includes_status_url_headers_and_body(self) -> None:
        client = ComfyUIClient("http://127.0.0.1:8188")
        response = httpx.Response(
            502,
            headers={"server": "nginx", "content-type": "text/plain"},
            text="",
            request=httpx.Request("POST", "http://127.0.0.1:8188/prompt"),
        )
        client._client.post = AsyncMock(return_value=response)

        with self.assertRaises(ComfyApiError) as ctx:
            await client.queue_prompt(prompt={"1": {}}, client_id="cid")

        message = str(ctx.exception)
        self.assertIn("status=502", message)
        self.assertIn("url=http://127.0.0.1:8188/prompt", message)
        self.assertIn("'server': 'nginx'", message)
        self.assertIn("body=''", message)
        await client.aclose()

    def test_history_entry_is_complete_when_outputs_exist_without_status_flag(self) -> None:
        entry = {
            "outputs": {
                "94": {
                    "images": [
                        {"filename": "Flux2_Klein_9b_kv_00001_.png", "subfolder": "", "type": "output"}
                    ]
                }
            }
        }
        self.assertTrue(history_entry_is_complete(entry))
        self.assertIsNone(history_entry_error(entry))

    def test_history_entry_is_complete_when_status_completed_true(self) -> None:
        self.assertTrue(history_entry_is_complete({"status": {"completed": True}, "outputs": {}}))

    def test_history_entry_error_on_failed_status(self) -> None:
        entry = {"status": {"status_str": "error", "completed": False, "messages": ["node 94 exploded"]}}
        self.assertFalse(history_entry_is_complete(entry))
        self.assertIn("node 94 exploded", history_entry_error(entry) or "")

    def test_extract_history_entry_accepts_bare_outputs_payload(self) -> None:
        payload = {"outputs": {"1": {"images": [{"filename": "a.png"}]}}}
        self.assertEqual(extract_history_entry(payload, prompt_id="missing"), payload)

    async def test_wait_for_history_complete_returns_when_outputs_exist(self) -> None:
        client = ComfyUIClient("http://127.0.0.1:8188")
        client.get_history_entry = AsyncMock(
            return_value={
                "outputs": {
                    "94": {"images": [{"filename": "out.png", "subfolder": "", "type": "output"}]}
                }
            }
        )
        entry = await client.wait_for_history_complete(prompt_id="p1", timeout_s=5, poll_interval_s=0.01)
        self.assertEqual(entry["outputs"]["94"]["images"][0]["filename"], "out.png")
        await client.aclose()


if __name__ == "__main__":
    unittest.main()
