from __future__ import annotations

from pathlib import Path

from .util import guess_image_ext, sanitize_filename_part


INBOX_DIRNAME = "_inbox"


def stage_input_image(
    *,
    runs_dir: Path,
    data: bytes,
    filename_hint: str | None,
    max_bytes: int,
    name_prefix: str,
) -> Path:
    if len(data) > max(1, int(max_bytes)):
        raise ValueError(f"Image too large ({len(data)} bytes)")
    inbox = Path(runs_dir) / INBOX_DIRNAME
    inbox.mkdir(parents=True, exist_ok=True)
    filename = _staging_filename(data=data, filename_hint=filename_hint, name_prefix=name_prefix)
    path = inbox / filename
    path.write_bytes(data)
    return path


def _staging_filename(*, data: bytes, filename_hint: str | None, name_prefix: str) -> str:
    ext = ""
    stem = "image"
    if filename_hint:
        hinted = Path(filename_hint)
        ext = hinted.suffix
        stem = hinted.stem or stem
    ext = (ext or guess_image_ext(data)).lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
        ext = guess_image_ext(data)
    if ext == ".jpeg":
        ext = ".jpg"
    safe_stem = sanitize_filename_part(stem, max_len=60)
    safe_prefix = sanitize_filename_part(name_prefix[:12], max_len=12)
    return f"{safe_prefix}--{safe_stem}{ext}"
