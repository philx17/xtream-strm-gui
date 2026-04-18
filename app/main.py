from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.templating import Jinja2Templates

from pathlib import Path
from typing import Any, Dict, Optional
import threading
import traceback

from .xtream_api import XtreamClient
from .export_core import run_export_job, reset_generated_output
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
)

APP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"

app = FastAPI(title="xtream-strm-gui")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

ensure_storage()

EXPORT_LOCK = threading.Lock()


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


@app.post("/api/export/start")
async def api_export_start(payload: ExportPayload):
    if EXPORT_LOCK.locked():
        return JSONResponse(
            {"ok": False, "error": "Es läuft bereits ein Export."},
            status_code=409,
        )

    config = payload.config or {}
    save_runtime_config(config)

    def worker():
        with EXPORT_LOCK:
            try:
                set_job_status(
                    running=True,
                    phase="initializing",
                    progress=0,
                    message="Export wird vorbereitet ...",
                    error=None,
                    logs=[],
                    started_at=None,
                    finished_at=None,
                )
                run_export_job(config)
            except Exception as exc:
                tb = traceback.format_exc()
                set_job_status(
                    running=False,
                    phase="failed",
                    progress=100,
                    message="Export fehlgeschlagen.",
                    error=f"{exc}\n\n{tb}",
                    finished_at=None,
                )

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

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
