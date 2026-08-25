#!/usr/bin/env bash
# Linux/macOS one-click launcher for comfyui2api (functionally equivalent to
# start.ps1, without Windows-only netsh/excluded-port APIs).
#
#   * uv sync --locked to manage the project venv + deps
#   * auto-builds /ui into src/comfyui2api/webui_dist when assets are missing
#   * port fallback when the requested port is not bindable
#   * optional .env loading + COMFYUI_BASE_URL probe warning
#
# Usage:
#   ./start.sh
#   ./start.sh -ListenHost 127.0.0.1 -Port 9000
#   ./start.sh -CheckOnly
#   ./start.sh -EnvFile .env
#   ./start.sh -SkipFrontendBuild
set -eo pipefail

ListenHost=""
Port=""
Python=""
EnvFile=""
SkipComfyCheck=0
SkipFrontendBuild=0
CheckOnly=0
UV_EXE=""
SELECTED_PORT=""

# --- minimal CLI parsing (mirrors start.ps1 param names) --------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        -ListenHost)        ListenHost="$2"; shift 2 ;;
        -Port)              Port="$2"; shift 2 ;;
        -Python)            Python="$2"; shift 2 ;;
        -EnvFile)           EnvFile="$2"; shift 2 ;;
        -SkipComfyCheck)    SkipComfyCheck=1; shift ;;
        -SkipFrontendBuild) SkipFrontendBuild=1; shift ;;
        -CheckOnly)         CheckOnly=1; shift ;;
        *) echo "Unknown option: $1"; exit 2 ;;
    esac
done

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"
DEFAULT_ENV_FILE="$PROJECT_ROOT/.env"

warn() { printf '[comfyui2api] %s\n' "$1"; }

# --- env file import (only forwards non-empty values) ----------------------
# Mirrors start.ps1 Import-EnvFile: tolerate UTF-8 (with/without BOM), CRLF,
# leading comment markers, and surrounding quotes.
import_env_file() {
    local path="$1"
    [ -f "$path" ] || return
    local line name value
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line%"${line##*[![:space:]]}"}"   # trim trailing ws
        if [[ -z "$line" || "$line" =~ ^# ]]; then
            continue
        fi
        # strip leading comment markers (e.g. "###  KEY=value" docs)
        line="${line#\#\#\#}"
        line="${line#\#\#}"
        line="${line#\#}"
        if [[ ! "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*=[[:space:]]*(.*)$ ]]; then
            continue
        fi
        name="${BASH_REMATCH[1]}"
        value="${BASH_REMATCH[2]}"
        value="${value#"${value%%[![:space:]]*}"}"              # trim leading value ws
        value="${value%"${value##*[![:space:]]}"}"              # trim trailing value ws
        # strip a single layer of surrounding '...' or "..." quotes
        if [[ "$value" == \"*\" ]]; then
            value="${value#\"}"; value="${value%\"}"
        elif [[ "$value" == \'*\' ]]; then
            value="${value#\'}"; value="${value%\'}"
        fi
        if [ -n "$value" ]; then
            export "$name"="$value"
        fi
    done < "$path"
}

# --- webui readiness --------------------------------------------------------
is_webui_ready() {
    [ -f "$PROJECT_ROOT/src/comfyui2api/webui_dist/index.html" ] || return 1
    [ -d "$PROJECT_ROOT/src/comfyui2api/webui_dist/assets" ] || return 1
    local files
    files="$(find "$PROJECT_ROOT/src/comfyui2api/webui_dist/assets" -maxdepth 1 -type f 2>/dev/null | wc -l)"
    [ "$files" -gt 0 ] && return 0
    return 1
}

ensure_webui_dist() {
    if [ "$SkipFrontendBuild" -eq 1 ]; then
        if ! is_webui_ready; then
            warn "Web UI assets are missing. /ui will be empty until you run scripts/build-frontend.sh"
        fi
        return
    fi
    if is_webui_ready; then
        warn "Web UI assets found."
        return
    fi
    local build_script="$PROJECT_ROOT/scripts/build-frontend.sh"
    if [ ! -f "$build_script" ]; then
        echo "Web UI has not been built and $build_script is missing."
        exit 1
    fi
    warn "Web UI assets missing; building frontend into src/comfyui2api/webui_dist ..."
    "$build_script" || exit 1
    if ! is_webui_ready; then
        echo "Frontend build finished but src/comfyui2api/webui_dist still has no assets."
        exit 1
    fi
}

# --- TCP bind probe via venv python (cross-platform; no netsh needed) ------
can_bind() {
    local host="$1" port="$2"
    local py="$VENV_PYTHON"
    if [ -n "$Python" ] && [ -f "$Python" ]; then
        py="$Python"
    fi
    # If the project venv doesn't exist yet (first run, before uv sync), fall
    # back to a system python for the socket probe so the port is still chosen
    # correctly even though /ui is not yet built.
    if [ ! -f "$py" ]; then
        if command -v python3 >/dev/null 2>&1; then
            py="$(command -v python3)"
        elif command -v python >/dev/null 2>&1; then
            py="$(command -v python)"
        else
            return 1
        fi
    fi
    "$py" - "$host" "$port" >/dev/null 2>&1 <<'PYEOF'
import sys, socket
host, port = sys.argv[1], int(sys.argv[2])
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((host, port))
except Exception:
    sys.exit(1)
finally:
    try:
        s.close()
    except Exception:
        pass
PYEOF
}

find_available_port() {
    local host="$1" port="$2"
    if [[ -z "$port" || ! "$port" =~ ^[0-9]+$ ]]; then
        port=8000
    fi
    if [ "$port" -gt 65535 ]; then port=65535; fi
    if [ "$port" -lt 1 ]; then port=1; fi

    if can_bind "$host" "$port"; then
        SELECTED_PORT="$port"
        return
    fi
    warn "Port $port is not bindable on $host. Falling back to an available port."
    local cand
    for cand in $(seq "$((port + 1))" 65535); do
        if can_bind "$host" "$cand"; then
            warn "Falling back to available port $cand."
            SELECTED_PORT="$cand"
            return
        fi
    done
    echo "No available TCP port was found starting from $port."
    exit 1
}

resolve_uv() {
    if command -v uv >/dev/null 2>&1; then
        UV_EXE="$(command -v uv)"
        return
    fi
    echo "uv was not found. Install uv first: https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
}

ensure_uv_environment() {
    local uv_exe="$1"
    local uv_args="sync --locked"
    if [ -n "$Python" ]; then
        if [ ! -f "$Python" ]; then
            echo "Python executable not found: $Python"
            exit 1
        fi
        uv_args="$uv_args --python $Python"
    fi
    warn "Syncing project environment with uv ..."
    "$uv_exe" $uv_args || exit 1
    if [ ! -f "$VENV_PYTHON" ]; then
        echo "uv did not create the expected project environment at $VENV_PYTHON"
        exit 1
    fi
}

test_comfy_reachable() {
    local base="$1"
    local health_url="${base%/}/system_stats"
    if curl -fsS --max-time 5 "$health_url" >/dev/null 2>&1; then
        warn "ComfyUI reachable at $base"
    else
        warn "ComfyUI is not reachable at $base. The API will still start, but requests may fail until ComfyUI is available."
    fi
}

# ---------------------------------------------------------------------------
cd "$PROJECT_ROOT" || exit 1

resolve_uv
uv_exe="$UV_EXE"

if [ -z "$EnvFile" ] && [ -f "$DEFAULT_ENV_FILE" ]; then
    EnvFile="$DEFAULT_ENV_FILE"
fi
resolved_env_file=""
if [ -n "$EnvFile" ]; then
    if [ ! -f "$EnvFile" ]; then
        echo "ENV file not found: $EnvFile"
        exit 1
    fi
    resolved_env_file="$(cd "$(dirname "$EnvFile")" && pwd)/$(basename "$EnvFile")"
    export ENV_FILE="$resolved_env_file"
    import_env_file "$resolved_env_file"
fi

# defaults, overridable by CLI args below
if [[ -z "${COMFYUI_BASE_URL:-}" ]]; then export COMFYUI_BASE_URL="http://127.0.0.1:8188"; fi
if [[ -z "${IMAGE_UPLOAD_MODE:-}" ]]; then export IMAGE_UPLOAD_MODE="comfy"; fi
if [[ -z "${API_LISTEN:-}" ]]; then export API_LISTEN="0.0.0.0"; fi
if [[ -z "${API_PORT:-}" ]]; then export API_PORT="8000"; fi

if [ -n "$ListenHost" ]; then
    export API_LISTEN="$ListenHost"
fi
if [ -n "$Port" ]; then
    export API_PORT="$Port"
fi

resolved_host="${API_LISTEN:-0.0.0.0}"
resolved_port="${API_PORT:-8000}"
resolved_comfy="${COMFYUI_BASE_URL:-http://127.0.0.1:8188}"
resolved_upload_mode="${IMAGE_UPLOAD_MODE:-comfy}"

find_available_port "$resolved_host" "$resolved_port"
selected_port="$SELECTED_PORT"
if [ -n "$selected_port" ] && [ "$selected_port" != "$resolved_port" ]; then
    export API_PORT="$selected_port"
fi
resolved_port="${API_PORT:-8000}"

ensure_uv_environment "$uv_exe"
ensure_webui_dist
python_exe="$VENV_PYTHON"

warn "Project root: $PROJECT_ROOT"
warn "uv: $uv_exe"
warn "Python: $python_exe"
warn "ENV_FILE: ${ENV_FILE:-}"
warn "COMFYUI_BASE_URL: $resolved_comfy"
warn "IMAGE_UPLOAD_MODE: $resolved_upload_mode"
warn "Listening on: http://$resolved_host:$resolved_port"

if [ "$SkipComfyCheck" -eq 0 ]; then
    test_comfy_reachable "$resolved_comfy"
fi

if [ "$CheckOnly" -eq 1 ]; then
    warn "Check only mode finished."
    exit 0
fi

# Decide launch mode from the resolved listen host.
#   - Loopback (127.0.0.1 / ::1 / localhost): keep `ui` mode so the dashboard
#     is served and the browser is opened (matches start.ps1 behaviour).
#   - Anything else (0.0.0.0, LAN IP, etc.): use `serve` so the process binds
#     the external interface and API_LISTEN / API_PORT actually take effect.
#     Bare `python -m comfyui2api` defaults to `ui` mode which hard-codes
#     127.0.0.1 and would silently ignore API_LISTEN (=> not reachable remotely).
is_loopback() {
    local h="$1"
    [[ "$h" == "127.0.0.1" || "$h" == "localhost" || "$h" == "::1" || "$h" == "0:0:0:0:0:0:0:1" ]]
}

warn "Starting comfyui2api ..."
if is_loopback "$resolved_host"; then
    warn "Listen host is loopback; starting in 'ui' mode (127.0.0.1)."
    "$uv_exe" run --locked --no-sync -m comfyui2api
else
    warn "Listen host is non-loopback; starting in 'serve' mode ($resolved_host:$resolved_port)."
    "$uv_exe" run --locked --no-sync -m comfyui2api serve --host "$resolved_host" --port "$resolved_port"
fi
exit 0