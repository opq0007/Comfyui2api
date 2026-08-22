from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


from comfyui2api.config import load_config


class ConfigTests(unittest.TestCase):
    def test_job_retention_days_overrides_seconds(self) -> None:
        with patch.dict(
            os.environ,
            {
                "API_TOKEN": "api-token",
                "ADMIN_TOKEN": "admin-token",
                "JOB_RETENTION_DAYS": "3",
                "JOB_RETENTION_SECONDS": "60",
            },
            clear=False,
        ):
            cfg = load_config()

        self.assertEqual(cfg.job_retention_seconds, 3 * 24 * 60 * 60)

    def test_job_retention_days_supports_zero(self) -> None:
        with patch.dict(
            os.environ,
            {
                "API_TOKEN": "api-token",
                "ADMIN_TOKEN": "admin-token",
                "JOB_RETENTION_DAYS": "0",
                "JOB_RETENTION_SECONDS": "604800",
            },
            clear=False,
        ):
            cfg = load_config()

        self.assertEqual(cfg.job_retention_seconds, 0)

    def test_job_retention_seconds_used_when_days_not_set(self) -> None:
        with patch.dict(
            os.environ,
            {
                "API_TOKEN": "api-token",
                "ADMIN_TOKEN": "admin-token",
                "JOB_RETENTION_DAYS": "",
                "JOB_RETENTION_SECONDS": "120",
            },
            clear=False,
        ):
            cfg = load_config()

        self.assertEqual(cfg.job_retention_seconds, 120)

    def test_http_timeout_defaults_to_ten_minutes(self) -> None:
        with patch.dict(
            os.environ,
            {
                "API_TOKEN": "api-token",
                "ADMIN_TOKEN": "admin-token",
                "HTTP_TIMEOUT_S": "",
            },
            clear=False,
        ):
            cfg = load_config()

        self.assertEqual(cfg.http_timeout_s, 600)

    def test_missing_tokens_raise_config_error(self) -> None:
        from comfyui2api.errors import ConfigError

        with patch.dict(os.environ, {"API_TOKEN": "", "ADMIN_TOKEN": "admin"}, clear=False):
            with self.assertRaises(ConfigError):
                load_config()
        with patch.dict(os.environ, {"API_TOKEN": "api", "ADMIN_TOKEN": ""}, clear=False):
            with self.assertRaises(ConfigError):
                load_config()


if __name__ == "__main__":
    unittest.main()
