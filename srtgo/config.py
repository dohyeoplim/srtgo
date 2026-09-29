import json
import os
from pathlib import Path
from typing import Any, Optional

from dotenv import find_dotenv, load_dotenv

from .ktx import generate_device_id


def load_env() -> None:
    load_dotenv(find_dotenv(usecwd=True))


def env(name: str) -> Optional[str]:
    return os.environ.get(name) or None


def _settings_path() -> Path:
    if path := env("SRTGO_SETTINGS_FILE"):
        return Path(path)
    return Path(env("XDG_CONFIG_HOME") or Path.home() / ".config") / "srtgo" / "settings.json"


def load_settings() -> dict:
    try:
        return json.loads(_settings_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_settings(**values: Any) -> None:
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**load_settings(), **values}, ensure_ascii=False, indent=2), encoding="utf-8")


def device_id() -> str:
    # Korail's macro detection tracks the device, so a generated id is kept across runs.
    if value := env("KORAIL_DEVICE_ID") or load_settings().get("device_id"):
        return value
    save_settings(device_id=(value := generate_device_id()))
    return value
