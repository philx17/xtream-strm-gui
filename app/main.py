from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from datetime import datetime, timedelta
import requests

from pathlib import Path
from typing import Any, Dict, List
import threading
import traceback
import time
import os
import secrets
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .xtream_api import XtreamClient
from .jellyfin_api import JellyfinClient
from .proxy_core import (
    handle_player_api,
    handle_movie_stream,
    handle_series_stream,
    handle_live_stream,
    _is_local_request,
)
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

GUI_USERNAME = os.getenv("GUI_USERNAME", "admin")
GUI_PASSWORD = os.getenv("GUI_PASSWORD", "admin123")
SESSION_SECRET = os.getenv("GUI_SESSION_SECRET", "change-this-session-secret-please")

ITEM_CACHE_TTL_SECONDS = 180

GUI_LOGIN_FAIL_LIMIT = int(os.getenv("GUI_LOGIN_FAIL_LIMIT", "6"))
GUI_LOGIN_BAN_SECONDS = int(os.getenv("GUI_LOGIN_BAN_SECONDS", "9000"))

PROXY_FAIL_LIMIT = int(os.getenv("PROXY_FAIL_LIMIT", "12"))
PROXY_BAN_SECONDS = int(os.getenv("PROXY_BAN_SECONDS", "18000"))

XMLTV_DEFAULT_URL = "http://192.168.9.222:9981/xmltv"
SERVER_STARTED_AT = datetime.now()

app = FastAPI(title="xtream-strm-gui")
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="xtream_gui_session",
    same_site="lax",
    https_only=False,
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

ensure_storage()
EXPORT_LOCK = threading.Lock()
SCHEDULER = BackgroundScheduler()
SCHEDULER.start()

ITEM_CACHE_LOCK = threading.Lock()
ITEM_CACHE: Dict[str, Dict[str, Any]] = {}

SECURITY_LOCK = threading.Lock()
SECURITY_STATE: Dict[str, Dict[str, Dict[str, float | int]]] = {
    "gui": {},
    "proxy": {},
}


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


def _is_logged_in(request: Request) -> bool:
    session = request.scope.get("session")
    if not isinstance(session, dict):
        return False
    return session.get("gui_authenticated") is True


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "").strip()
    if xff:
        return xff.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _local_for_gui(request: Request) -> bool:
    try:
        return bool(_is_local_request(request))
    except Exception:
        return False


def _local_for_gui_response(request: Request):
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            {"detail": "GUI ist nur aus dem lokalen Netzwerk erreichbar."},
            status_code=403,
        )
    return PlainTextResponse(
        "GUI ist nur aus dem lokalen Netzwerk erreichbar.",
        status_code=403,
    )


def _not_logged_in_response():
    return JSONResponse({"detail": "Nicht eingeloggt."}, status_code=401)


def _security_bucket(scope: str) -> Dict[str, Dict[str, float | int]]:
    return SECURITY_STATE.setdefault(scope, {})


def _is_banned(scope: str, ip: str) -> tuple[bool, int]:
    now = time.time()
    with SECURITY_LOCK:
        entry = _security_bucket(scope).get(ip)
        if not entry:
            return False, 0

        banned_until = float(entry.get("banned_until", 0.0))
        if banned_until <= now:
            entry["banned_until"] = 0.0
            entry["fail_count"] = 0
            return False, 0

        return True, max(1, int(banned_until - now))


def _register_failure(scope: str, ip: str, limit: int, ban_seconds: int):
    now = time.time()
    with SECURITY_LOCK:
        bucket = _security_bucket(scope)
        entry = bucket.get(ip) or {"fail_count": 0, "banned_until": 0.0, "last_fail": 0.0}
        entry["fail_count"] = int(entry.get("fail_count", 0)) + 1
        entry["last_fail"] = now

        if int(entry["fail_count"]) >= limit:
            entry["banned_until"] = now + ban_seconds
            entry["fail_count"] = 0

        bucket[ip] = entry


def _clear_failures(scope: str, ip: str):
    with SECURITY_LOCK:
        bucket = _security_bucket(scope)
        if ip in bucket:
            bucket[ip]["fail_count"] = 0
            bucket[ip]["banned_until"] = 0.0


def _require_gui_api_access_response(request: Request):
    if not _local_for_gui(request):
        return _local_for_gui_response(request)
    if not _is_logged_in(request):
        return _not_logged_in_response()
    return None


def _proxy_expected_credentials() -> tuple[str, str]:
    runtime_cfg = load_runtime_config()
    proxy_cfg = runtime_cfg.get("proxy", {}) if isinstance(runtime_cfg, dict) else {}
    return (
        str(proxy_cfg.get("username") or "").strip(),
        str(proxy_cfg.get("password") or ""),
    )


def _proxy_auth_ok(username: str, password: str) -> bool:
    expected_user, expected_pass = _proxy_expected_credentials()
    return bool(expected_user) and username == expected_user and password == expected_pass


def _proxy_ban_response(ip: str, retry_after: int):
    return JSONResponse(
        {
            "error": f"Zu viele falsche Proxy-Anfragen von {ip}. Bitte später erneut versuchen.",
            "retry_after": retry_after,
        },
        status_code=429,
        headers={"Retry-After": str(retry_after)},
    )


@app.middleware("http")
async def gui_local_only_middleware(request: Request, call_next):
    path = request.url.path or "/"

    if path.startswith("/proxy/"):
        return await call_next(request)

    if path in {"/xmltv.php", "/proxy/xmltv.php", "/healthz"}:
        return await call_next(request)

    if path.startswith("/static/"):
        return await call_next(request)

    if path == "/" or path.startswith("/api/") or path in {"/login", "/logout"}:
        if not _local_for_gui(request):
            return _local_for_gui_response(request)

    return await call_next(request)


_apply_scheduler_from_runtime()


@app.get("/healthz")
async def healthz():
    status = get_job_status() or {}
    runtime_cfg = load_runtime_config()
    schedule_cfg = _normalize_schedule(runtime_cfg.get("schedule", {})) if isinstance(runtime_cfg, dict) else _normalize_schedule({})
    job = SCHEDULER.get_job("xtream_auto_export")

    next_run = None
    if job and job.next_run_time:
        next_run = job.next_run_time.strftime("%d.%m.%Y %H:%M:%S")

    now = datetime.now()
    uptime_delta = now - SERVER_STARTED_AT

    days = uptime_delta.days
    hours, remainder = divmod(uptime_delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    uptime_human = f"{days}d {hours:02d}:{minutes:02d}:{seconds:02d}"

    proxy_cfg = runtime_cfg.get("proxy", {}) if isinstance(runtime_cfg, dict) else {}
    proxy_user = str(proxy_cfg.get("username") or "").strip()
    proxy_pass = str(proxy_cfg.get("password") or "")
    jellyfin_url = str(proxy_cfg.get("jellyfin_base_url") or "").strip()
    jellyfin_api_key = str(proxy_cfg.get("jellyfin_api_key") or "").strip()
    xmltv_url = str(proxy_cfg.get("epg_xml_url") or "http://192.168.9.222:9981/xmltv").strip()

    proxy_configured = bool(proxy_user and proxy_pass and jellyfin_url and jellyfin_api_key)

    proxy_check = {
        "configured": proxy_configured,
        "username_set": bool(proxy_user),
        "password_set": bool(proxy_pass),
        "jellyfin_url_set": bool(jellyfin_url),
        "jellyfin_api_key_set": bool(jellyfin_api_key),
        "xmltv_url": xmltv_url,
        "status": "ok" if proxy_configured else "incomplete",
    }

    return JSONResponse({
        "ok": True,
        "service": {
            "name": "xtream-proxy",
            "alive": True,
            "started_at": SERVER_STARTED_AT.strftime("%d.%m.%Y %H:%M:%S"),
            "now": now.strftime("%d.%m.%Y %H:%M:%S"),
            "uptime_seconds": int(uptime_delta.total_seconds()),
            "uptime_human": uptime_human,
        },
        "proxy": proxy_check,
        "scheduler": {
            "available": bool(SCHEDULER.running),
            "enabled": bool(schedule_cfg.get("enabled")),
            "mode": schedule_cfg.get("mode", "daily"),
            "time": schedule_cfg.get("time", "03:30"),
            "weekday": schedule_cfg.get("weekday", "monday"),
            "interval_days": int(schedule_cfg.get("interval_days", 1) or 1),
            "profile_name": schedule_cfg.get("profile_name", ""),
            "next_run": next_run,
        },
        "export": {
            "running": bool(status.get("running")),
            "phase": status.get("phase", "idle"),
            "progress": int(status.get("progress", 0) or 0),
            "message": status.get("message", ""),
            "started_at": status.get("started_at"),
            "finished_at": status.get("finished_at"),
            "cancel_requested": bool(status.get("cancel_requested")),
            "last_error": status.get("error"),
        }
    })


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if not _local_for_gui(request):
        return _local_for_gui_response(request)

    ip = _client_ip(request)
    banned, retry_after = _is_banned("gui", ip)
    if banned:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": f"Zu viele falsche Logins. Bitte in {retry_after} Sekunden erneut versuchen.",
            },
            status_code=429,
        )

    if _is_logged_in(request):
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    if not _local_for_gui(request):
        return _local_for_gui_response(request)

    ip = _client_ip(request)
    banned, retry_after = _is_banned("gui", ip)
    if banned:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": f"Zu viele falsche Logins. Bitte in {retry_after} Sekunden erneut versuchen.",
            },
            status_code=429,
        )

    if not secrets.compare_digest(username, GUI_USERNAME) or not secrets.compare_digest(password, GUI_PASSWORD):
        _register_failure("gui", ip, GUI_LOGIN_FAIL_LIMIT, GUI_LOGIN_BAN_SECONDS)
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Benutzername oder Passwort ist falsch."},
            status_code=401,
        )

    _clear_failures("gui", ip)
    request.session["gui_authenticated"] = True
    request.session["gui_login_at"] = datetime.now().isoformat()
    return RedirectResponse(url="/", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    if not _local_for_gui(request):
        return _local_for_gui_response(request)
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if not _local_for_gui(request):
        return _local_for_gui_response(request)
    if not _is_logged_in(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/status")
async def api_status(request: Request):
    denied = _require_gui_api_access_response(request)
    if denied:
        return denied
    return JSONResponse(get_job_status())


@app.get("/api/report")
async def api_report(request: Request):
    denied = _require_gui_api_access_response(request)
    if denied:
        return denied
    return JSONResponse(get_last_report())


@app.post("/api/report/clear")
async def api_report_clear(request: Request):
    denied = _require_gui_api_access_response(request)
    if denied:
        return denied
    clear_last_report()
    return JSONResponse({"ok": True})


@app.get("/api/runtime-config")
async def api_runtime_config(request: Request):
    denied = _require_gui_api_access_response(request)
    if denied:
        return denied
    return JSONResponse(load_runtime_config())


@app.post("/api/runtime-config")
async def api_save_runtime_config(request: Request, payload: Dict[str, Any]):
    denied = _require_gui_api_access_response(request)
    if denied:
        return denied
    save_runtime_config(payload)
    _apply_scheduler_from_runtime()
    return JSONResponse({"ok": True})


@app.get("/api/profiles")
async def api_profiles(request: Request):
    denied = _require_gui_api_access_response(request)
    if denied:
        return denied
    return JSONResponse({"profiles": get_profiles()})


@app.post("/api/profiles/save")
async def api_profiles_save(request: Request, payload: ProfilePayload):
    denied = _require_gui_api_access_response(request)
    if denied:
        return denied
    save_profile(payload.name, payload.config)
    return JSONResponse({"ok": True, "name": payload.name})


@app.post("/api/profiles/delete")
async def api_profiles_delete(request: Request, payload: DeleteProfilePayload):
    denied = _require_gui_api_access_response(request)
    if denied:
        return denied
    delete_profile(payload.name)
    return JSONResponse({"ok": True, "name": payload.name})


@app.post("/api/test-connection")
async def api_test_connection(request: Request, payload: ConnectionPayload):
    denied = _require_gui_api_access_response(request)
    if denied:
        return denied
    try:
        client = XtreamClient(payload.base_url, payload.username, payload.password)
        account = client.get_account_info()
        return JSONResponse({"ok": True, "account": account})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.post("/api/load-catalog")
async def api_load_catalog(request: Request, payload: ConnectionPayload):
    denied = _require_gui_api_access_response(request)
    if denied:
        return denied
    try:
        client = XtreamClient(payload.base_url, payload.username, payload.password)
        catalog = client.load_catalog()
        account = client.get_account_info()
        return JSONResponse({"ok": True, "catalog": catalog, "account": account})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.post("/api/load-items")
async def api_load_items(request: Request, payload: LoadItemsPayload):
    denied = _require_gui_api_access_response(request)
    if denied:
        return denied
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
async def api_proxy_test_jellyfin(request: Request, payload: JellyfinConnectionPayload):
    denied = _require_gui_api_access_response(request)
    if denied:
        return denied
    try:
        client = JellyfinClient(payload.base_url, payload.api_key)
        info = client.test_connection()
        return JSONResponse({"ok": True, "info": info})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.post("/api/proxy/libraries")
async def api_proxy_libraries(request: Request, payload: JellyfinConnectionPayload):
    denied = _require_gui_api_access_response(request)
    if denied:
        return denied
    try:
        client = JellyfinClient(payload.base_url, payload.api_key)
        libs = client.get_libraries()
        return JSONResponse({"ok": True, "libraries": libs})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.get("/api/schedule")
async def api_schedule_get(request: Request):
    denied = _require_gui_api_access_response(request)
    if denied:
        return denied
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
async def api_schedule_save(request: Request, payload: SchedulePayload):
    denied = _require_gui_api_access_response(request)
    if denied:
        return denied
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
async def api_schedule_run_now(request: Request):
    denied = _require_gui_api_access_response(request)
    if denied:
        return denied

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
async def api_export_start(request: Request, payload: ExportPayload):
    denied = _require_gui_api_access_response(request)
    if denied:
        return denied

    cfg = payload.config or {}
    if not isinstance(cfg, dict):
        cfg = {}

    ok = _start_export_thread(cfg, source="manual")
    if not ok:
        return JSONResponse({"ok": False, "error": "Es läuft bereits ein Export."}, status_code=409)

    return JSONResponse({"ok": True})


@app.post("/api/export/cancel")
async def api_export_cancel(request: Request):
    denied = _require_gui_api_access_response(request)
    if denied:
        return denied

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
async def api_output_reset(request: Request, payload: ResetPayload):
    denied = _require_gui_api_access_response(request)
    if denied:
        return denied
    try:
        result = reset_generated_output(
            config=payload.config or {},
            delete_runtime_state=payload.delete_runtime_state,
        )
        return JSONResponse({"ok": True, "result": result})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.get("/api/health")
async def api_health(request: Request):
    denied = _require_gui_api_access_response(request)
    if denied:
        return denied

    runtime_cfg = load_runtime_config()
    proxy_cfg = runtime_cfg.get("proxy", {}) if isinstance(runtime_cfg, dict) else {}
    xmltv_url = str(proxy_cfg.get("epg_xml_url") or XMLTV_DEFAULT_URL).strip()

    health: Dict[str, Any] = {
        "ok": True,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scheduler_running": bool(SCHEDULER.running),
        "export_status": get_job_status(),
        "profiles_count": len(get_profiles() or {}),
        "xmltv_url": xmltv_url,
        "checks": {},
    }

    try:
        xmltv_resp = requests.get(xmltv_url, timeout=10)
        health["checks"]["xmltv"] = {
            "ok": xmltv_resp.ok,
            "status_code": xmltv_resp.status_code,
            "content_type": xmltv_resp.headers.get("content-type", ""),
        }
        if not xmltv_resp.ok:
            health["ok"] = False
    except Exception as exc:
        health["checks"]["xmltv"] = {"ok": False, "error": str(exc)}
        health["ok"] = False

    try:
        jf_url = str(proxy_cfg.get("jellyfin_base_url") or "").strip()
        jf_key = str(proxy_cfg.get("jellyfin_api_key") or "").strip()
        if jf_url and jf_key:
            jf = JellyfinClient(jf_url, jf_key)
            info = jf.test_connection()
            health["checks"]["jellyfin"] = {
                "ok": True,
                "server_name": info.get("ServerName") or info.get("Name") or "",
                "version": info.get("Version") or "",
            }
        else:
            health["checks"]["jellyfin"] = {"ok": False, "error": "Nicht konfiguriert."}
    except Exception as exc:
        health["checks"]["jellyfin"] = {"ok": False, "error": str(exc)}
        health["ok"] = False

    return JSONResponse(health, status_code=200 if health["ok"] else 503)


@app.get("/proxy/player_api.php")
async def proxy_player_api(
    request: Request,
    username: str = "",
    password: str = "",
    action: str | None = None,
    category_id: str | None = None,
    series_id: str | None = None,
    stream_id: str | None = None,
    limit: str | None = None,
):
    ip = _client_ip(request)
    banned, retry_after = _is_banned("proxy", ip)
    if banned:
        return _proxy_ban_response(ip, retry_after)

    if not _proxy_auth_ok(username, password):
        _register_failure("proxy", ip, PROXY_FAIL_LIMIT, PROXY_BAN_SECONDS)
        return JSONResponse({"error": "Ungültige Proxy-Zugangsdaten."}, status_code=401)

    _clear_failures("proxy", ip)

    runtime_cfg = load_runtime_config()
    return handle_player_api(
        runtime_cfg=runtime_cfg,
        request=request,
        username=username,
        password=password,
        action=action,
        category_id=category_id,
        series_id=series_id,
        stream_id=stream_id,
        # limit=limit,
    )


@app.get("/proxy/movie/{username}/{password}/{item_id}.{ext}")
async def proxy_movie_stream(
    request: Request,
    username: str,
    password: str,
    item_id: str,
    ext: str,
):
    ip = _client_ip(request)
    banned, retry_after = _is_banned("proxy", ip)
    if banned:
        return _proxy_ban_response(ip, retry_after)

    if not _proxy_auth_ok(username, password):
        _register_failure("proxy", ip, PROXY_FAIL_LIMIT, PROXY_BAN_SECONDS)
        return JSONResponse({"error": "Ungültige Proxy-Zugangsdaten."}, status_code=401)

    _clear_failures("proxy", ip)

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
    ip = _client_ip(request)
    banned, retry_after = _is_banned("proxy", ip)
    if banned:
        return _proxy_ban_response(ip, retry_after)

    if not _proxy_auth_ok(username, password):
        _register_failure("proxy", ip, PROXY_FAIL_LIMIT, PROXY_BAN_SECONDS)
        return JSONResponse({"error": "Ungültige Proxy-Zugangsdaten."}, status_code=401)

    _clear_failures("proxy", ip)

    runtime_cfg = load_runtime_config()
    return handle_series_stream(runtime_cfg, request, username, password, item_id, ext)


@app.get("/proxy/live/{username}/{password}/{item_id}.{ext}")
async def proxy_live_stream(
    request: Request,
    username: str,
    password: str,
    item_id: str,
    ext: str,
):
    ip = _client_ip(request)
    banned, retry_after = _is_banned("proxy", ip)
    if banned:
        return _proxy_ban_response(ip, retry_after)

    if not _proxy_auth_ok(username, password):
        _register_failure("proxy", ip, PROXY_FAIL_LIMIT, PROXY_BAN_SECONDS)
        return JSONResponse({"error": "Ungültige Proxy-Zugangsdaten."}, status_code=401)

    _clear_failures("proxy", ip)

    runtime_cfg = load_runtime_config()
    return handle_live_stream(runtime_cfg, request, username, password, item_id, ext)


@app.api_route("/xmltv.php", methods=["GET", "HEAD"])
@app.api_route("/proxy/xmltv.php", methods=["GET", "HEAD"])
async def proxy_xmltv(request: Request):
    runtime_cfg = load_runtime_config()
    proxy_cfg = runtime_cfg.get("proxy", {}) if isinstance(runtime_cfg, dict) else {}
    xmltv_url = str(proxy_cfg.get("epg_xml_url") or XMLTV_DEFAULT_URL).strip()

    try:
        resp = requests.get(xmltv_url, timeout=30)
        resp.raise_for_status()

        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "Cache-Control": "public, max-age=60",
        }

        if request.method == "HEAD":
            return Response(content=b"", headers=headers)

        return Response(
            content=resp.content,
            media_type="text/xml; charset=utf-8",
            headers=headers,
        )

    except Exception as exc:
        return JSONResponse(
            {"ok": False, "error": f"XMLTV konnte nicht geladen werden: {exc}"},
            status_code=502
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8787, reload=False)