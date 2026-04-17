from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict
import json
import threading

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
PROFILES_FILE = DATA_DIR / "profiles.json"
RUNTIME_CONFIG_FILE = DATA_DIR / "runtime_config.json"
JOB_STATUS_FILE = DATA_DIR / "job_status.json"
LAST_REPORT_FILE = DATA_DIR / "last_report.json"
MANIFEST_FILE = DATA_DIR / "manifest.json"

_LOCK = threading.Lock()


def _now_str() -> str:
    return datetime.now().strftime("%d.%m.%Y %H:%M:%S")


def ensure_storage():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not PROFILES_FILE.exists():
        _write_json(PROFILES_FILE, {"profiles": {}})
    if not RUNTIME_CONFIG_FILE.exists():
        _write_json(RUNTIME_CONFIG_FILE, {})
    if not JOB_STATUS_FILE.exists():
        _write_json(JOB_STATUS_FILE, _default_job_status())
    if not LAST_REPORT_FILE.exists():
        _write_json(LAST_REPORT_FILE, {})
    if not MANIFEST_FILE.exists():
        _write_json(MANIFEST_FILE, {"items": {}})


def _default_job_status() -> Dict[str, Any]:
    return {
        "running": False,
        "phase": "idle",
        "progress": 0,
        "message": "Bereit.",
        "error": None,
        "logs": [],
        "started_at": None,
        "finished_at": None,
    }


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def _write_json(path: Path, data: Any):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_profiles() -> Dict[str, Any]:
    ensure_storage()
    data = _read_json(PROFILES_FILE, {"profiles": {}})
    if not isinstance(data, dict):
        return {}
    profiles = data.get("profiles", {})
    return profiles if isinstance(profiles, dict) else {}


def save_profile(name: str, config: Dict[str, Any]):
    ensure_storage()
    name = (name or "").strip()
    if not name:
        raise ValueError("Profilname fehlt.")
    with _LOCK:
        data = _read_json(PROFILES_FILE, {"profiles": {}})
        profiles = data.get("profiles", {})
        if not isinstance(profiles, dict):
            profiles = {}
        profiles[name] = {
            "name": name,
            "config": config,
            "updated_at": _now_str(),
        }
        data["profiles"] = profiles
        _write_json(PROFILES_FILE, data)


def delete_profile(name: str):
    ensure_storage()
    with _LOCK:
        data = _read_json(PROFILES_FILE, {"profiles": {}})
        profiles = data.get("profiles", {})
        if isinstance(profiles, dict) and name in profiles:
            del profiles[name]
        data["profiles"] = profiles
        _write_json(PROFILES_FILE, data)


def load_runtime_config() -> Dict[str, Any]:
    ensure_storage()
    data = _read_json(RUNTIME_CONFIG_FILE, {})
    return data if isinstance(data, dict) else {}


def save_runtime_config(config: Dict[str, Any]):
    ensure_storage()
    with _LOCK:
        _write_json(RUNTIME_CONFIG_FILE, config or {})


def get_job_status() -> Dict[str, Any]:
    ensure_storage()
    data = _read_json(JOB_STATUS_FILE, _default_job_status())
    if not isinstance(data, dict):
        return _default_job_status()
    return data


def set_job_status(**updates):
    ensure_storage()
    with _LOCK:
        current = get_job_status()
        current.update(updates)
        _write_json(JOB_STATUS_FILE, current)


def append_job_log(message: str):
    ensure_storage()
    with _LOCK:
        current = get_job_status()
        logs = current.get("logs", [])
        if not isinstance(logs, list):
            logs = []
        logs.append(f"[{_now_str()}] {message}")
        logs = logs[-250:]
        current["logs"] = logs
        current["message"] = message
        _write_json(JOB_STATUS_FILE, current)


def save_last_report(report: Dict[str, Any]):
    ensure_storage()
    with _LOCK:
        _write_json(LAST_REPORT_FILE, report or {})


def get_last_report() -> Dict[str, Any]:
    ensure_storage()
    data = _read_json(LAST_REPORT_FILE, {})
    return data if isinstance(data, dict) else {}


def clear_last_report():
    ensure_storage()
    with _LOCK:
        _write_json(LAST_REPORT_FILE, {})


def load_manifest() -> Dict[str, Any]:
    ensure_storage()
    data = _read_json(MANIFEST_FILE, {"items": {}})
    if not isinstance(data, dict):
        return {"items": {}}
    items = data.get("items", {})
    if not isinstance(items, dict):
        items = {}
    return {"items": items}


def save_manifest(manifest: Dict[str, Any]):
    ensure_storage()
    with _LOCK:
        _write_json(MANIFEST_FILE, manifest or {"items": {}})


def clear_manifest():
    ensure_storage()
    with _LOCK:
        _write_json(MANIFEST_FILE, {"items": {}})