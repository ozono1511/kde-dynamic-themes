"""Paths and host-independent configuration. Legacy project data are not moved."""
import os
from pathlib import Path

def path_from_env(variable: str, fallback: Path) -> Path:
    value = os.environ.get(variable)
    return Path(value).expanduser().resolve() if value else fallback.expanduser().resolve()

PROJECT_ROOT = path_from_env("KDT_PROJECT_ROOT", Path.home() / "Projects/kde-dynamic-themes")
USER_CONFIG = path_from_env("XDG_CONFIG_HOME", Path.home() / ".config")
USER_DATA = path_from_env("XDG_DATA_HOME", Path.home() / ".local/share")
USER_CACHE = path_from_env("XDG_CACHE_HOME", Path.home() / ".cache")
