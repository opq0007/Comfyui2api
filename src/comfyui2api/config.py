from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError


logger = logging.getLogger(__name__)


def _env_str(name: str, default: str = "") -> str:
    v = os.environ.get(name)
    return default if v is None else str(v).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env_str(name, "")
    if not raw:
        return int(default)
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = _env_str(name, "")
    if not raw:
        return float(default)
    return float(raw)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env_str(name, "")
    if not raw:
        return bool(default)
    return raw.lower() in {"1", "true", "yes", "y", "on"}


def _job_retention_seconds() -> int:
    raw_days = _env_str("JOB_RETENTION_DAYS", "")
    if raw_days:
        days = max(0.0, _env_float("JOB_RETENTION_DAYS", 0.0))
        return int(days * 24 * 60 * 60)
    return max(0, _env_int("JOB_RETENTION_SECONDS", 604_800))


def runtime_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def package_resource_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS).resolve()
        package_dir = base / "comfyui2api"
        return package_dir if package_dir.exists() else base
    return Path(__file__).resolve().parent


@dataclass(frozen=True)
class Config:
    api_listen: str
    api_port: int
    api_token: str
    public_base_url: str

    workflows_dir: Path
    runs_dir: Path
    data_dir: Path
    database_path: Path
    ui_enabled: bool
    ui_dist_dir: Path
    admin_token: str
    input_subdir: str

    max_body_bytes: int
    max_image_bytes: int
    timeout_s: int
    poll_interval_s: float
    http_timeout_s: int

    enable_workflow_watch: bool
    job_retention_seconds: int
    max_jobs_in_memory: int
    job_cleanup_interval_s: float
    signed_url_secret: str
    signed_url_ttl_seconds: int

    health_check_interval_s: int
    health_check_timeout_s: int
    health_check_fail_threshold: int
    health_check_recovery_threshold: int


def load_config() -> Config:
    project_root = runtime_base_dir()

    workflows_dir = Path(_env_str("WORKFLOWS_DIR", str(project_root / "comfyui-api-workflows"))).expanduser()
    runs_dir = Path(_env_str("RUNS_DIR", str(project_root / "runs"))).expanduser()
    data_dir = Path(_env_str("DATA_DIR", str(project_root / "data"))).expanduser()
    database_path = Path(_env_str("DATABASE_PATH", str(data_dir / "comfyui2api.db"))).expanduser()
    ui_enabled = _env_bool("COMFYUI2API_UI_ENABLED", True) and not _env_bool("COMFYUI2API_DISABLE_UI", False)
    api_token = _env_str("API_TOKEN", "")
    admin_token = _env_str("ADMIN_TOKEN", "")

    if not api_token:
        raise ConfigError("API_TOKEN is required (public API is fail-closed).")
    if not admin_token:
        raise ConfigError("ADMIN_TOKEN is required (public admin UI is fail-closed).")
    if api_token == admin_token:
        logger.warning("API_TOKEN and ADMIN_TOKEN are identical; using the same secret for both roles.")

    job_cleanup_interval_s = _env_float("JOB_CLEANUP_INTERVAL_S", 60.0)
    if job_cleanup_interval_s <= 0:
        job_cleanup_interval_s = 60.0

    return Config(
        api_listen=_env_str("API_LISTEN", "0.0.0.0"),
        api_port=_env_int("API_PORT", 8000),
        api_token=api_token,
        public_base_url=_env_str("PUBLIC_BASE_URL", "").rstrip("/"),
        workflows_dir=workflows_dir,
        runs_dir=runs_dir,
        data_dir=data_dir,
        database_path=database_path,
        ui_enabled=ui_enabled,
        ui_dist_dir=Path(_env_str("COMFYUI2API_UI_DIST_DIR", str(package_resource_dir() / "webui_dist"))).expanduser(),
        admin_token=admin_token,
        input_subdir=_env_str("INPUT_SUBDIR", "comfyui2api").strip("/").strip("\\"),
        max_body_bytes=_env_int("MAX_BODY_BYTES", 30_000_000),
        max_image_bytes=_env_int("MAX_IMAGE_BYTES", 20_000_000),
        timeout_s=_env_int("TIMEOUT_S", 3600),
        poll_interval_s=_env_float("POLL_INTERVAL_S", 0.5),
        http_timeout_s=_env_int("HTTP_TIMEOUT_S", 30),
        enable_workflow_watch=_env_bool("ENABLE_WORKFLOW_WATCH", True),
        job_retention_seconds=_job_retention_seconds(),
        max_jobs_in_memory=max(0, _env_int("MAX_JOBS_IN_MEMORY", 1000)),
        job_cleanup_interval_s=job_cleanup_interval_s,
        signed_url_secret=_env_str("SIGNED_URL_SECRET", ""),
        signed_url_ttl_seconds=max(1, _env_int("SIGNED_URL_TTL_SECONDS", 3600)),
        health_check_interval_s=max(1, _env_int("HEALTH_CHECK_INTERVAL_S", 60)),
        health_check_timeout_s=max(1, _env_int("HEALTH_CHECK_TIMEOUT_S", 5)),
        health_check_fail_threshold=max(1, _env_int("HEALTH_CHECK_FAIL_THRESHOLD", 3)),
        health_check_recovery_threshold=max(1, _env_int("HEALTH_CHECK_RECOVERY_THRESHOLD", 1)),
    )
