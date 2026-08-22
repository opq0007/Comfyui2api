from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from starlette.datastructures import Headers
from starlette.responses import Response
from starlette.staticfiles import NotModifiedResponse, StaticFiles
from starlette.types import Scope


# Windows registry often maps .js -> text/plain. Browsers refuse to execute
# <script type="module"> unless Content-Type is a JavaScript MIME type.
_JS_MIME = "text/javascript"
_ASSET_MIME_OVERRIDES = {
    ".js": _JS_MIME,
    ".mjs": _JS_MIME,
    ".cjs": _JS_MIME,
    ".css": "text/css",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".wasm": "application/wasm",
    ".map": "application/json",
}


def ensure_web_asset_mimetypes() -> None:
    for suffix, content_type in _ASSET_MIME_OVERRIDES.items():
        current, _encoding = mimetypes.guess_type(f"asset{suffix}")
        if current != content_type:
            mimetypes.add_type(content_type, suffix)


def asset_media_type(path: str | os.PathLike[str]) -> str | None:
    return _ASSET_MIME_OVERRIDES.get(Path(path).suffix.lower())


class WebAssetStaticFiles(StaticFiles):
    def file_response(
        self,
        full_path: os.PathLike[str] | str,
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        ensure_web_asset_mimetypes()
        request_headers = Headers(scope=scope)
        media_type = asset_media_type(full_path)
        kwargs: dict[str, Any] = {
            "status_code": status_code,
            "stat_result": stat_result,
        }
        if media_type:
            kwargs["media_type"] = media_type
        response = FileResponse(full_path, **kwargs)
        if self.is_not_modified(response.headers, request_headers):
            return NotModifiedResponse(response.headers)
        return response


def mount_webui(app: FastAPI, ui_dist_dir: Path) -> None:
    ensure_web_asset_mimetypes()
    index = Path(ui_dist_dir) / "index.html"
    assets = Path(ui_dist_dir) / "assets"

    if not index.exists():
        @app.get("/ui")
        async def ui_missing() -> dict[str, str]:
            return {
                "error": "Web UI has not been built.",
                "hint": "Run the frontend build script first.",
            }

        return

    if assets.exists():
        app.mount("/ui/assets", WebAssetStaticFiles(directory=str(assets)), name="ui-assets")

    @app.get("/ui")
    @app.get("/ui/{path:path}")
    async def webui(path: str = "") -> Any:
        return FileResponse(str(index), media_type="text/html; charset=utf-8")
