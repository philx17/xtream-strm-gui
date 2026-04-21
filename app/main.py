from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.templating import Jinja2Templates

from pathlib import Path
from typing import Any, Dict, List
import threading
import traceback
import time
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .xtream_api import XtreamClient
from .jellyfin_api import JellyfinClient
from .proxy_core import handle_player_api, handle_movie_stream, handle_series_stream
from .export_core import run_export_job, reset_generated_output, ExportCancelled
from .state_core import (
    ensure_storage,
    get_profiles,
    save_profile,
    delete_profile,
    load_runtime_config,
    save_runtime_config,
    set_job_status,
    get_job_status,
    get_last_report,
    clear_last_report,
    request_cancel,
    clear_cancel_request,
)

APP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"

app = FastAPI(title="xtream-strm-gui")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

ensure_storage()
EXPORT_LOCK = threading.Lock()
SCHEDULER = BackgroundScheduler()
SCHEDULER.start()

ITEM_CACHE_LOCK = threading.Lock()
ITEM_CACHE: Dict[str, Dict[str, Any]] = {}
ITEM_CACHE_TTL_SECONDS = 180


class ConnectionPayload(BaseModel):
    base_url: str
    username: str
    password: str


class ProfilePayload(BaseModel):
    name: str
    config: Dict[str, Any]


class DeleteProfilePayload(BaseModel):
    name: str


class ExportPayload(BaseModel):
    config: Dict[str, Any]


class ResetPayload(BaseModel):
    config: Dict[str, Any]
    delete_runtime_state: bool = False


class LoadItemsPayload(BaseModel):
    connection: Dict[str, Any]
    item_type: str
    category_ids: List[str] = []


class SchedulePayload(BaseModel):
    schedule: Dict[str, Any]
    profile_name: str | None = None


class JellyfinConnectionPayload(BaseModel):
    base_url: str
    api_key: str


def _normalize_schedule(schedule_cfg: Dict[str, Any]) -> Dict[str, Any]:
    cfg = dict(schedule_cfg or {})
    cfg.setdefault("enabled", False)
    cfg.setdefault("mode", "daily")
    cfg.setdefault("time", "03:30")
    cfg.setdefault("weekday", "monday")
    cfg.setdefault("interval_days", 1)
    cfg.setdefault("profile_name", "")
    return cfg


def _parse_time_str(time_str: str) -> tuple[int, int]:
    try:
        hour_str, minute_str = (time_str or "03:30").split(":", 1)
        hour = max(0, min(23, int(hour_str)))
        minute = max(0, min(59, int(minute_str)))
        return hour, minute
    except Exception:
        return 3, 30


def _build_trigger(schedule_cfg: Dict[str, Any]):
    cfg = _normalize_schedule(schedule_cfg)
    if not cfg.get("enabled"):
        return None

    hour, minute = _parse_time_str(cfg.get("time", "03:30"))
    mode = cfg.get("mode", "daily")

    if mode == "weekly":
        weekday = str(cfg.get("weekday", "monday")).lower()
        weekday_map = {
            "monday": "mon",
            "tuesday": "tue",
            "wednesday": "wed",
            "thursday": "thu",
            "friday": "fri",
            "saturday": "sat",
            "sunday": "sun",
        }
        return CronTrigger(day_of_week=weekday_map.get(weekday, "mon"), hour=hour, minute=minute)

    if mode == "interval":
        every_days = max(1, int(cfg.get("interval_days", 1)))
        now = datetime.now()
        start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if start <= now:
            start = start + timedelta(days=1)
        return IntervalTrigger(days=every_days, start_date=start)

    return CronTrigger(hour=hour, minute=minute)


def _resolve_scheduled_profile_config() -> Dict[str, Any] | None:
    runtime_cfg = load_runtime_config()
    schedule = _normalize_schedule(runtime_cfg.get("schedule", {}))
    profile_name = schedule.get("profile_name")

    if not profile_name:
        return None

    profiles = get_profiles()
    profile_entry = profiles.get(profile_name)
    if not isinstance(profile_entry, dict):
        return None

    config = profile_entry.get("config")
    if not isinstance(config, dict):
        return None

    return config


def _start_export_thread(config: Dict[str, Any], source: str = "manual") -> bool:
    if EXPORT_LOCK.locked():
        return False

    runtime_cfg = load_runtime_config()
    if not isinstance(runtime_cfg, dict):
        runtime_cfg = {}

    merged = dict(runtime_cfg)
    merged.update(config or {})

    if "schedule" not in (config or {}) and "schedule" in runtime_cfg:
        merged["schedule"] = runtime_cfg["schedule"]

    save_runtime_config(merged)
    clear_cancel_request()

    set_job_status(
        running=True,
        phase="initializing",
        progress=0,
        message=f"Export wird vorbereitet ({source}) ...",
        error=None,
        logs=[],
        started_at=datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
        finished_at=None,
        cancel_requested=False,
    )

    def worker():
        with EXPORT_LOCK:
            try:
                run_export_job(config)
            except ExportCancelled:
                pass
            except Exception as exc:
                tb = traceback.format_exc()
                set_job_status(
                    running=False,
                    phase="failed",
                    progress=100,
                    message="Export fehlgeschlagen.",
                    error=f"{exc}\n\n{tb}",
                    finished_at=datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
                    cancel_requested=False,
                )

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return True


def _scheduled_export_runner():
    config = _resolve_scheduled_profile_config()
    if not config:
        return
    schedule = _normalize_schedule(load_runtime_config().get("schedule", {}))
    profile_name = schedule.get("profile_name") or "unbekannt"
    _start_export_thread(config, source=f"scheduler:{profile_name}")


def _apply_scheduler_from_runtime():
    runtime_cfg = load_runtime_config()
    schedule_cfg = _normalize_schedule(runtime_cfg.get("schedule", {}))

    try:
        SCHEDULER.remove_job("xtream_auto_export")
    except Exception:
        pass

    trigger = _build_trigger(schedule_cfg)
    if trigger is None:
        return

    SCHEDULER.add_job(
        _scheduled_export_runner,
        trigger=trigger,
        id="xtream_auto_export",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )


def _make_item_cache_key(connection: Dict[str, Any], item_type: str, category_ids: List[str]) -> str:
    base_url = str(connection.get("base_url", "")).strip()
    username = str(connection.get("username", "")).strip()
    item_type = str(item_type or "").strip().lower()
    ids = ",".join(sorted(str(x).strip() for x in category_ids if str(x).strip()))
    return f"{base_url}|{username}|{item_type}|{ids}"


def _get_cached_items(cache_key: str):
    now = time.time()
    with ITEM_CACHE_LOCK:
        entry = ITEM_CACHE.get(cache_key)
        if not entry:
            return None
        if now - entry.get("ts", 0) > ITEM_CACHE_TTL_SECONDS:
            ITEM_CACHE.pop(cache_key, None)
            return None
        return entry.get("items")


def _set_cached_items(cache_key: str, items: List[Dict[str, Any]]):
    with ITEM_CACHE_LOCK:
        ITEM_CACHE[cache_key] = {
            "ts": time.time(),
            "items": items,
        }


_apply_scheduler_from_runtime()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/status")
async def api_status():
    return JSONResponse(get_job_status())


@app.get("/api/report")
async def api_report():
    return JSONResponse(get_last_report())


@app.post("/api/report/clear")
async def api_report_clear():
    clear_last_report()
    return JSONResponse({"ok": True})


@app.get("/api/runtime-config")
async def api_runtime_config():
    return JSONResponse(load_runtime_config())


@app.post("/api/runtime-config")
async def api_save_runtime_config(payload: Dict[str, Any]):
    save_runtime_config(payload)
    _apply_scheduler_from_runtime()
    return JSONResponse({"ok": True})


@app.get("/api/profiles")
async def api_profiles():
    return JSONResponse({"profiles": get_profiles()})


@app.post("/api/profiles/save")
async def api_profiles_save(payload: ProfilePayload):
    save_profile(payload.name, payload.config)
    return JSONResponse({"ok": True, "name": payload.name})


@app.post("/api/profiles/delete")
async def api_profiles_delete(payload: DeleteProfilePayload):
    delete_profile(payload.name)
    return JSONResponse({"ok": True, "name": payload.name})


@app.post("/api/test-connection")
async def api_test_connection(payload: ConnectionPayload):
    try:
        client = XtreamClient(payload.base_url, payload.username, payload.password)
        account = client.get_account_info()
        return JSONResponse({"ok": True, "account": account})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.post("/api/load-catalog")
async def api_load_catalog(payload: ConnectionPayload):
    try:
        client = XtreamClient(payload.base_url, payload.username, payload.password)
        catalog = client.load_catalog()
        account = client.get_account_info()
        return JSONResponse({"ok": True, "catalog": catalog, "account": account})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.post("/api/load-items")
async def api_load_items(payload: LoadItemsPayload):
    try:
        connection = payload.connection or {}
        item_type = str(payload.item_type or "").strip().lower()
        category_ids = [str(x).strip() for x in payload.category_ids if str(x).strip()]

        if item_type not in {"livetv", "movies", "series"}:
            return JSONResponse({"ok": False, "error": "Ungültiger item_type."}, status_code=400)

        cache_key = _make_item_cache_key(connection, item_type, category_ids)
        cached = _get_cached_items(cache_key)
        if cached is not None:
            return JSONResponse({"ok": True, "items": cached, "cached": True})

        client = XtreamClient(
            connection.get("base_url", ""),
            connection.get("username", ""),
            connection.get("password", ""),
        )

        if item_type == "livetv":
            items = client.get_live_streams_multi(category_ids) if category_ids else []
        elif item_type == "movies":
            items = client.get_vod_streams_multi(category_ids) if category_ids else []
        else:
            items = client.get_series_multi(category_ids) if category_ids else []

        _set_cached_items(cache_key, items)
        return JSONResponse({"ok": True, "items": items, "cached": False})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.post("/api/proxy/test-jellyfin")
async def api_proxy_test_jellyfin(payload: JellyfinConnectionPayload):
    try:
        client = JellyfinClient(payload.base_url, payload.api_key)
        info = client.test_connection()
        return JSONResponse({"ok": True, "info": info})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.post("/api/proxy/libraries")
async def api_proxy_libraries(payload: JellyfinConnectionPayload):
    try:
        client = JellyfinClient(payload.base_url, payload.api_key)
        libs = client.get_libraries()
        return JSONResponse({"ok": True, "libraries": libs})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.get("/api/schedule")
async def api_schedule_get():
    runtime_cfg = load_runtime_config()
    schedule_cfg = _normalize_schedule(runtime_cfg.get("schedule", {}))
    job = SCHEDULER.get_job("xtream_auto_export")

    next_run = None
    if job and job.next_run_time:
        next_run = job.next_run_time.strftime("%d.%m.%Y %H:%M:%S")

    return JSONResponse({
        "schedule": schedule_cfg,
        "next_run": next_run
    })


@app.post("/api/schedule/save")
async def api_schedule_save(payload: SchedulePayload):
    runtime_cfg = load_runtime_config()
    if not isinstance(runtime_cfg, dict):
        runtime_cfg = {}

    runtime_cfg["schedule"] = _normalize_schedule(payload.schedule or {})
    runtime_cfg["schedule"]["profile_name"] = payload.profile_name or ""

    save_runtime_config(runtime_cfg)
    _apply_scheduler_from_runtime()

    job = SCHEDULER.get_job("xtream_auto_export")
    next_run = None
    if job and job.next_run_time:
        next_run = job.next_run_time.strftime("%d.%m.%Y %H:%M:%S")

    return JSONResponse({"ok": True, "next_run": next_run})


@app.post("/api/schedule/run-now")
async def api_schedule_run_now():
    config = _resolve_scheduled_profile_config()
    if not config:
        return JSONResponse(
            {"ok": False, "error": "Kein gültiges Profil für den Automatikmodus ausgewählt."},
            status_code=400,
        )

    schedule = _normalize_schedule(load_runtime_config().get("schedule", {}))
    profile_name = schedule.get("profile_name") or "unbekannt"

    ok = _start_export_thread(config, source=f"run-now:{profile_name}")
    if not ok:
        return JSONResponse({"ok": False, "error": "Es läuft bereits ein Export."}, status_code=409)
    return JSONResponse({"ok": True})


@app.post("/api/export/start")
async def api_export_start(payload: ExportPayload):
    cfg = payload.config or {}
    if not isinstance(cfg, dict):
        cfg = {}

    ok = _start_export_thread(cfg, source="manual")
    if not ok:
        return JSONResponse({"ok": False, "error": "Es läuft bereits ein Export."}, status_code=409)

    return JSONResponse({"ok": True})


@app.post("/api/export/cancel")
async def api_export_cancel():
    status = get_job_status()
    if not status.get("running"):
        return JSONResponse({"ok": False, "error": "Aktuell läuft kein Export."}, status_code=409)

    request_cancel()
    set_job_status(
        cancel_requested=True,
        message="Abbruch wurde angefordert ...",
        phase=status.get("phase", "cancelling"),
        progress=status.get("progress", 0),
    )
    return JSONResponse({"ok": True})


@app.post("/api/output/reset")
async def api_output_reset(payload: ResetPayload):
    try:
        result = reset_generated_output(
            config=payload.config or {},
            delete_runtime_state=payload.delete_runtime_state,
        )
        return JSONResponse({"ok": True, "result": result})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.get("/proxy/player_api.php")
async def proxy_player_api(
    request: Request,
    username: str = "",
    password: str = "",
    action: str | None = None,
    category_id: str | None = None,
    series_id: str | None = None,
):
    runtime_cfg = load_runtime_config()
    return handle_player_api(
        runtime_cfg=runtime_cfg,
        request=request,
        username=username,
        password=password,
        action=action,
        category_id=category_id,
        series_id=series_id,
    )


@app.get("/proxy/movie/{username}/{password}/{item_id}.{ext}")
async def proxy_movie_stream(
    request: Request,
    username: str,
    password: str,
    item_id: str,
    ext: str,
):
    runtime_cfg = load_runtime_config()
    return handle_movie_stream(runtime_cfg, request, username, password, item_id, ext)


@app.get("/proxy/series/{username}/{password}/{item_id}.{ext}")
async def proxy_series_stream(
    request: Request,
    username: str,
    password: str,
    item_id: str,
    ext: str,
):
    runtime_cfg = load_runtime_config()
    return handle_series_stream(runtime_cfg, request, username, password, item_id, ext)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8787, reload=False)
