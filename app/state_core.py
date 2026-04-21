from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict
import json
import os
import shutil
import threading

APP_DIR = Path(__file__).resolve().parent
LEGACY_DATA_DIR = APP_DIR / "data"
DATA_DIR = Path(os.environ.get("APP_DATA_DIR", "/data")).resolve()

PROFILES_FILE = DATA_DIR / "profiles.json"
RUNTIME_CONFIG_FILE = DATA_DIR / "runtime_config.json"
JOB_STATUS_FILE = DATA_DIR / "job_status.json"
LAST_REPORT_FILE = DATA_DIR / "last_report.json"
MANIFEST_FILE = DATA_DIR / "manifest.json"

_LOCK = threading.Lock()


def _now_str() -> str:
    return datetime.now().strftime("%d.%m.%Y %H:%M:%S")


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
        "cancel_requested": False,
    }


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def _write_json(path: Path, data: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _migrate_legacy_file(src: Path, dst: Path):
    if src.exists() and not dst.exists():
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        except Exception:
            pass


def ensure_storage():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    _migrate_legacy_file(LEGACY_DATA_DIR / "profiles.json", PROFILES_FILE)
    _migrate_legacy_file(LEGACY_DATA_DIR / "runtime_config.json", RUNTIME_CONFIG_FILE)
    _migrate_legacy_file(LEGACY_DATA_DIR / "job_status.json", JOB_STATUS_FILE)
    _migrate_legacy_file(LEGACY_DATA_DIR / "last_report.json", LAST_REPORT_FILE)
    _migrate_legacy_file(LEGACY_DATA_DIR / "manifest.json", MANIFEST_FILE)

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
    merged = _default_job_status()
    merged.update(data)
    return merged


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
        logs = logs[-500:]
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


def request_cancel():
    ensure_storage()
    with _LOCK:
        current = get_job_status()
        current["cancel_requested"] = True
        _write_json(JOB_STATUS_FILE, current)


def clear_cancel_request():
    ensure_storage()
    with _LOCK:
        current = get_job_status()
        current["cancel_requested"] = False
        _write_json(JOB_STATUS_FILE, current)


def is_cancel_requested() -> bool:
    ensure_storage()
    current = get_job_status()
    return bool(current.get("cancel_requested", False))


def save_changelog_file(report: Dict[str, Any]):
    ensure_storage()

    history_dir = DATA_DIR / "history"
    history_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    json_path = history_dir / f"changelog_{timestamp}.json"
    txt_path = history_dir / f"changelog_{timestamp}.txt"

    try:
      _write_json(json_path, report or {})
    except Exception:
      pass

    try:
      lines = []
      lines.append(f"Changelog {timestamp}")
      lines.append("=" * 40)

      added = report.get("changelog", {}).get("added", [])
      removed = report.get("changelog", {}).get("removed", [])

      lines.append("\nNeu:")
      for x in added:
          lines.append(f"+ {x.get('name') or x.get('path')}")

      lines.append("\nGelöscht:")
      for x in removed:
          lines.append(f"- {x.get('name') or x.get('path')}")

      txt_path.write_text("\n".join(lines), encoding="utf-8")
    except Exception:
      pass