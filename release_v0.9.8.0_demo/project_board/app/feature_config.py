"""Load and validate ``config.yaml`` for the app factory.

Uses a hand-rolled minimal YAML reader (only the dialect this project emits —
top-level ``key: value`` mappings with string/int/bool values) so we do not
depend on PyYAML. Replace with PyYAML if/when the schema grows beyond this.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Final

logger = logging.getLogger(__name__)

_REQUIRED_KEYS: Final[tuple[str, ...]] = (
    "ADMIN_USERNAME",
    "ADMIN_PASSWORD",
    "SECRET_KEY",
    "DB_PATH",
    "SESSION_LIFETIME_HOURS",
    "SESSION_COOKIE_SECURE",
    "SESSION_COOKIE_HTTPONLY",
)


class ConfigError(ValueError):
    """Raised when config.yaml is missing, unreadable, or missing required keys."""


def load_config(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Load config from ``path`` and validate required keys.

    Environment variables override the file values for SECRET_KEY (so a
    leaked config.yaml does not leak the production secret) and DB_PATH
    (so deployments can point the data directory at a mounted volume).
    """
    cfg = _read_yaml_file(Path(path))
    _validate(cfg)
    cfg = _apply_env_overrides(cfg)
    _coerce_types(cfg)
    logger.info("config loaded path=%s keys=%s", path, sorted(cfg.keys()))
    return cfg


# ---------- internals ----------

def _read_yaml_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    text = path.read_text(encoding="utf-8")
    return _parse_minimal_yaml(text)


def _parse_minimal_yaml(text: str) -> dict[str, Any]:
    """Parse the subset of YAML used by this project's config.yaml.

    Supported: top-level ``key: value`` lines, ``#`` comments, blank lines.
    Values may be quoted strings, bare strings, ints, or true/false.
    """
    result: dict[str, Any] = {}
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if line.startswith((" ", "\t")):
            raise ConfigError(f"nested YAML not supported: {raw_line!r}")
        if ":" not in line:
            raise ConfigError(f"malformed line (no ':'): {raw_line!r}")
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not key:
            raise ConfigError(f"empty key in line: {raw_line!r}")
        result[key] = _coerce_scalar(value)
    return result


def _coerce_scalar(value: str) -> Any:
    if value == "":
        return ""
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    if value == "true":
        return True
    if value == "false":
        return False
    try:
        return int(value)
    except ValueError:
        return value


def _validate(cfg: dict[str, Any]) -> None:
    missing = [k for k in _REQUIRED_KEYS if k not in cfg]
    if missing:
        raise ConfigError(f"config missing required keys: {missing}")


def _apply_env_overrides(cfg: dict[str, Any]) -> dict[str, Any]:
    """Environment overrides for the two values that vary per deploy."""
    overrides = {
        "SECRET_KEY": os.environ.get("PROJECT_BOARD_SECRET_KEY"),
        "DB_PATH": os.environ.get("PROJECT_BOARD_DB_PATH"),
    }
    for key, value in overrides.items():
        if value:
            cfg[key] = value
    return cfg


def _coerce_types(cfg: dict[str, Any]) -> None:
    """Final type tightening after env override."""
    if not isinstance(cfg.get("SESSION_LIFETIME_HOURS"), int):
        raise ConfigError("SESSION_LIFETIME_HOURS must be an integer")
    if not isinstance(cfg.get("SESSION_COOKIE_SECURE"), bool):
        raise ConfigError("SESSION_COOKIE_SECURE must be true or false")
    if not isinstance(cfg.get("SESSION_COOKIE_HTTPONLY"), bool):
        raise ConfigError("SESSION_COOKIE_HTTPONLY must be true or false")
    if not isinstance(cfg.get("ADMIN_USERNAME"), str) or not cfg["ADMIN_USERNAME"]:
        raise ConfigError("ADMIN_USERNAME must be a non-empty string")
    if not isinstance(cfg.get("ADMIN_PASSWORD"), str) or not cfg["ADMIN_PASSWORD"]:
        raise ConfigError("ADMIN_PASSWORD must be a non-empty string")
    if not isinstance(cfg.get("SECRET_KEY"), str) or not cfg["SECRET_KEY"]:
        raise ConfigError("SECRET_KEY must be a non-empty string")
    if not isinstance(cfg.get("DB_PATH"), str) or not cfg["DB_PATH"]:
        raise ConfigError("DB_PATH must be a non-empty string")


__all__ = ["ConfigError", "load_config"]
