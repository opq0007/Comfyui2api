# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"

ROOT = Path.cwd().resolve()
SRC = ROOT / "src"
ICON = ROOT / "assets" / "comfyui2api.ico"
# Linux has no .ico icon support; PyInstaller falls back to a default icon.
ICON_ARG = str(ICON) if IS_WINDOWS and ICON.exists() else None


def data_files():
    items = []
    webui_dist = SRC / "comfyui2api" / "webui_dist"
    if webui_dist.exists():
        items.append((str(webui_dist), "comfyui2api/webui_dist"))
    if ICON.exists():
        items.append((str(ICON), "comfyui2api"))
    for name in ("README.md", ".env.example"):
        path = ROOT / name
        if path.exists():
            items.append((str(path), "."))
    return items


a = Analysis(
    [
        str(SRC / "comfyui2api" / "desktop_entry.py"),
        str(SRC / "comfyui2api" / "cli_entry.py"),
    ],
    pathex=[str(SRC)],
    binaries=[],
    datas=data_files(),
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

runtime_hooks = [script for script in a.scripts if script[0].startswith("pyi_rth_")]
scripts_by_name = {script[0]: script for script in a.scripts}

# console=True/False and upx only apply to Windows bootloaders. On Linux they
# are ignored or produce warnings, so gate them to keep one spec usable for
# both win + linux packaging.
def exe_kwargs(*, console: bool) -> dict:
    kwargs = dict(
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    if IS_WINDOWS:
        kwargs["console"] = console
        kwargs["upx"] = True
        kwargs["disable_windowed_traceback"] = False
    return kwargs


desktop_exe = EXE(
    pyz,
    runtime_hooks + [scripts_by_name["desktop_entry"]],
    [],
    exclude_binaries=True,
    name="comfyui2api",
    **exe_kwargs(console=False),
    icon=ICON_ARG,
)

cli_exe = EXE(
    pyz,
    runtime_hooks + [scripts_by_name["cli_entry"]],
    [],
    exclude_binaries=True,
    name="comfyui2api-cli",
    **exe_kwargs(console=True),
    icon=ICON_ARG,
)

coll = COLLECT(
    desktop_exe,
    cli_exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=IS_WINDOWS,
    upx_exclude=[],
    name="comfyui2api",
)
