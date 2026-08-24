#!/usr/bin/env bash
# Compile the Vite dashboard and copy it into the Python package so a single
# comfyui2api process can serve both /ui and /v1.
#
# Linux/macOS equivalent of scripts/build-frontend.ps1. Production assets use
# base "/ui/" and call same-origin /v1 and /runs (see frontend/vite.config.ts
# and frontend/src/lib/api.ts). The Vite proxy is dev-only and is not needed
# after this copy.
#
# Usage:
#   ./scripts/build-frontend.sh            # install deps + build + sync
#   ./scripts/build-frontend.sh --skip-install   # build + sync only
set -eo pipefail

skip_install=0
PNPM_PATH=""
if [[ -n "$1" && "$1" == "--skip-install" ]]; then
    skip_install=1
fi

# Resolve the repo root as the parent of this script's directory.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND="$ROOT/frontend"
FRONTEND_DIST="$FRONTEND/dist"
WEBUI_DIST="$ROOT/src/comfyui2api/webui_dist"

warn() { printf '[build-frontend] %s\n' "$*"; }

# Locate pnpm. Prefer an explicit PNPM override, then PATH. The Windows script
# resolves a .cmd shim; on Linux pnpm is a plain binary/shell shim on PATH.
# Sets PNPM_PATH as a named output (bash functions cannot return data).
resolve_pnpm() {
    if [ -n "$PNPM" ]; then
        [ -f "$PNPM" ] || { warn "PNPM override not found: $PNPM"; exit 1; }
        PNPM_PATH="$PNPM"
        return
    fi
    if command -v pnpm >/dev/null 2>&1; then
        PNPM_PATH="$(command -v pnpm)"
        return
    fi
    echo "pnpm was not found. Install Node.js and pnpm, or enable Corepack: corepack enable"
    exit 1
}

assert_frontend_layout() {
    if [ ! -d "$FRONTEND" ]; then
        echo "Frontend directory not found: $FRONTEND"; exit 1
    fi
    if [ ! -f "$FRONTEND/package.json" ]; then
        echo "frontend/package.json is missing."; exit 1
    fi
}

sync_webui_dist() {
    if [ ! -f "$FRONTEND_DIST/index.html" ]; then
        echo "Frontend build did not produce dist/index.html"; exit 1
    fi

    local asset_dir="$FRONTEND_DIST/assets"
    local built_count=0 copied_count=0 name
    if [ -d "$asset_dir" ]; then
        built_count="$(find "$asset_dir" -maxdepth 1 -type f | wc -l)"
    fi
    if [ "$built_count" -eq 0 ]; then
        echo "Frontend build did not produce any files under dist/assets"; exit 1
    fi

    # Clear any prior package copy, then copy the fresh build. Guard against
    # unexpected paths (only ever remove the known webui_dist target).
    if [ -e "$WEBUI_DIST" ]; then
        resolved="$(cd "$WEBUI_DIST" && pwd)"
        root_prefix="$ROOT/"
        if [[ "$resolved" != "$root_prefix"* ]]; then
            echo "Refusing to remove unexpected path: $resolved"; exit 1
        fi
        rm -rf "$WEBUI_DIST"
    fi
    mkdir -p "$WEBUI_DIST"
    cp -R "$FRONTEND_DIST/." "$WEBUI_DIST/"

    local index="$WEBUI_DIST/index.html"
    local copied_assets="$WEBUI_DIST/assets"
    if [ ! -f "$index" ]; then
        echo "Copy failed: $index is missing"; exit 1
    fi
    local copied_files=0
    if [ -d "$copied_assets" ]; then
        copied_files="$(find "$copied_assets" -maxdepth 1 -type f | wc -l)"
    fi
    if [ "$copied_files" -eq 0 ]; then
        echo "Copy failed: $copied_assets is empty"; exit 1
    fi

    # Verify index.html references only assets that actually got copied.
    for name2 in $(grep -oE '/ui/assets/[^" ]+' "$index" | sed -E 's#/ui/assets/##' | sort -u); do
        if [ ! -f "$copied_assets/$name2" ]; then
            echo "Copied index.html references missing asset: $name2"; exit 1
        fi
    done

    warn "Synced $copied_files asset file(s) to $WEBUI_DIST"
}

assert_frontend_layout
resolve_pnpm
pnpm="$PNPM_PATH"
warn "Project root: $ROOT"
warn "pnpm: $pnpm"

# Run the build with cwd inside frontend/, so pnpm finds package.json.
cd "$FRONTEND"
if [ "$skip_install" -eq 0 ]; then
    warn "Installing frontend dependencies..."
    "$pnpm" install
fi
warn "Building frontend (base=/ui/, same-origin /v1)..."
"$pnpm" build

warn "Copying dist -> src/comfyui2api/webui_dist ..."
sync_webui_dist
warn "Done. start.sh can now serve /ui from the Python process."