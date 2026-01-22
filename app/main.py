import os
import json
import shutil
import hashlib
import re
from pathlib import Path
from datetime import datetime, timezone

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from urllib.request import urlopen, Request as UrlReq
from urllib.parse import quote

from .m3u_core import build_catalog, parse_m3u, classify_item, extract_show_season_episode, clean_lang_tags
from .sync_core import run_sync


DATA_DIR = Path(os.getenv("DATA_DIR", "/data")).resolve()
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/output")).resolve()
PORT = int(os.getenv("PORT", "8787"))

GUI_USER = os.getenv("GUI_USER", "").strip()
GUI_PASS = os.getenv("GUI_PASS", "").strip()

CONFIG_PATH = DATA_DIR / "config.json"
PLAYLIST_PATH = DATA_DIR / "playlist.m3u"
CATALOG_PATH = DATA_DIR / "catalog.json"
LASTRUN_PATH = DATA_DIR / "last_run.json"

# NEW: playlist snapshot (to detect new playlist items)
PLAYLIST_SNAPSHOT_PATH = DATA_DIR / "playlist_snapshot.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI()
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def require_auth(request: Request):
    if not GUI_USER or not GUI_PASS:
        return
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("basic "):
        raise HTTPException(status_code=401, detail="Auth required", headers={"WWW-Authenticate": "Basic"})
    import base64

    b64 = auth.split(" ", 1)[1].strip()
    try:
        raw = base64.b64decode(b64).decode("utf-8")
    except Exception:
        raise HTTPException(status_code=401, detail="Bad auth", headers={"WWW-Authenticate": "Basic"})
    if ":" not in raw:
        raise HTTPException(status_code=401, detail="Bad auth", headers={"WWW-Authenticate": "Basic"})
    u, p = raw.split(":", 1)
    if u != GUI_USER or p != GUI_PASS:
        raise HTTPException(status_code=401, detail="Bad auth", headers={"WWW-Authenticate": "Basic"})


def load_config():
    if not CONFIG_PATH.exists():
        return {
            "xtream": {"base_url": "", "username": "", "password": "", "output": "ts"},
            "paths": {"out_dir": str(OUTPUT_DIR)},
            "sync": {
                "sync_delete": True,
                "prune_sidecars": False,
                "auto_refresh_playlist": True,
            },
            "schedule": {"enabled": False, "daily_time": "03:30"},
            "allow": {
                "livetv": {"categories": [], "titles": [], "full_categories": []},
                "movies": {"categories": [], "titles": [], "full_categories": []},
                "series": {"shows": [], "titles": []},
            },
        }
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def build_m3u_url(cfg):
    x = cfg["xtream"]
    base = x["base_url"].rstrip("/")
    out = (x.get("output") or "ts").lower().strip()
    if out == "m3u":
        out = "ts"
    if out not in ("ts", "m3u8"):
        out = "ts"
    return f"{base}/get.php?username={quote(x['username'])}&password={quote(x['password'])}&type=m3u_plus&output={quote(out)}"


def build_player_api_url(cfg):
    x = cfg["xtream"]
    base = x["base_url"].rstrip("/")
    return f"{base}/player_api.php?username={quote(x['username'])}&password={quote(x['password'])}"


def download_playlist(cfg):
    url = build_m3u_url(cfg)
    req = UrlReq(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=90) as r:
        data = r.read()
    PLAYLIST_PATH.write_bytes(data)
    return data.decode("utf-8", errors="replace")


def read_playlist_text():
    if not PLAYLIST_PATH.exists():
        return None
    return PLAYLIST_PATH.read_text(encoding="utf-8", errors="replace")


def write_catalog(cat: dict):
    CATALOG_PATH.write_text(json.dumps(cat, ensure_ascii=False, indent=2), encoding="utf-8")


def read_catalog():
    if not CATALOG_PATH.exists():
        return None
    try:
        return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_last_run(payload):
    LASTRUN_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_last_run():
    if not LASTRUN_PATH.exists():
        return None
    try:
        return json.loads(LASTRUN_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def parse_exp_date(user_info: dict):
    exp = user_info.get("exp_date")
    if not exp or str(exp).strip() in ("0", "-1"):
        return None
    try:
        ts = int(str(exp).strip())
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt
    except Exception:
        return None


def remaining_time(exp_dt: datetime):
    if not exp_dt:
        return None
    now = datetime.now(timezone.utc)
    delta = exp_dt - now
    secs = int(delta.total_seconds())
    return secs


# ---------------------------
# NEW: Playlist change tracker
# ---------------------------
def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _clean_group(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s or "Ungrouped"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_playlist_snapshot(m3u_text: str) -> dict:
    """
    Snapshot of ALL playlist items (independent of selection).
    We key by sha256(url) because url is usually unique in Xtream lists.
    """
    items = {}
    for it in parse_m3u(m3u_text):
        attrs = it["attrs"]
        url = (it.get("url") or "").strip()
        title = it.get("title") or ""
        if not url:
            continue

        group = _clean_group(attrs.get("group-title") or "Ungrouped")
        tvg_name = attrs.get("tvg-name") or title
        kind0 = classify_item(url, group, tvg_name, title)

        # normalize kind to GUI buckets
        if kind0 == "movie":
            kind = "movies"
        elif kind0 == "series":
            kind = "series"
        else:
            kind = "livetv"

        show = None
        season = None
        episode = None
        if kind == "series":
            s, se, epn, _ = extract_show_season_episode(tvg_name)
            show = s or clean_lang_tags(tvg_name)
            try:
                season = int(se or 0)
            except Exception:
                season = 0
            try:
                episode = int(epn or 0)
            except Exception:
                episode = 0

        key = _sha256(url)
        items[key] = {
            "kind": kind,
            "group": group if kind != "series" else None,
            "show": show if kind == "series" else None,
            "season": season if kind == "series" else None,
            "episode": episode if kind == "series" else None,
            "title": tvg_name,
            "url": url,
        }
    return {"generated_at": _utc_iso(), "items": items}


def _read_snapshot():
    if not PLAYLIST_SNAPSHOT_PATH.exists():
        return None
    try:
        return json.loads(PLAYLIST_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_snapshot(snap: dict):
    PLAYLIST_SNAPSHOT_PATH.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_changes_files(out_dir: Path, added_items: list, counts: dict):
    """
    Writes playlist-change files (ONLY added items):
      - out_dir/changes_latest.json
      - out_dir/changes_latest.txt
      - out_dir/changes_history.jsonl
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "time": _utc_iso(),
        "counts": counts,
        "added": added_items[:20],  # hard cap for GUI
        "added_total": counts.get("total", 0),
        "note": "Playlist changes (global). Only newly detected playlist items are listed here.",
    }

    (out_dir / "changes_latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = []
    lines.append(f"Xtream Playlist – Neue Inhalte ({payload['time']})")
    lines.append(
        f"Total neu: {counts.get('total',0)} | LiveTV: {counts.get('livetv',0)} | Movies: {counts.get('movies',0)} | Series: {counts.get('series',0)}"
    )
    lines.append("")

    if counts.get("total", 0) == 0:
        lines.append("Keine neuen Inhalte.")
    else:
        def sk(it):
            return (
                (it.get("kind") or ""),
                (it.get("group") or it.get("show") or ""),
                (it.get("title") or ""),
            )

        for it in sorted(added_items[:20], key=sk):
            kind = (it.get("kind") or "unknown").upper()
            grp = it.get("group") or it.get("show") or "Ungrouped"
            title = it.get("title") or ""
            lines.append(f"{kind} [{grp}] {title}")

        if counts.get("total", 0) > 20:
            lines.append("")
            lines.append(f"... und {counts.get('total',0)-20} weitere")

    (out_dir / "changes_latest.txt").write_text("\n".join(lines), encoding="utf-8")

    hist = out_dir / "changes_history.jsonl"
    with hist.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def track_playlist_changes(m3u_text: str, out_dir: Path):
    """
    Compare current playlist snapshot with previous snapshot.
    Only track ADDED items (not deletes/updates) as requested.
    """
    old = _read_snapshot()
    new = _build_playlist_snapshot(m3u_text)

    old_items = (old or {}).get("items") or {}
    new_items = (new or {}).get("items") or {}

    old_keys = set(old_items.keys())
    new_keys = set(new_items.keys())

    added_keys = sorted(list(new_keys - old_keys))

    added_items = []
    counts = {"livetv": 0, "movies": 0, "series": 0, "total": 0}

    for k in added_keys:
        it = new_items.get(k) or {}
        kind = it.get("kind") or "livetv"
        added_items.append(
            {
                "kind": kind,
                "group": it.get("group"),
                "show": it.get("show"),
                "season": it.get("season"),
                "episode": it.get("episode"),
                "title": it.get("title"),
            }
        )
        if kind in counts:
            counts[kind] += 1
        counts["total"] += 1

    # Sort and keep the full list in counts_total; JSON will carry first 20
    added_items.sort(
        key=lambda x: (
            (x.get("kind") or ""),
            (x.get("group") or x.get("show") or ""),
            (x.get("title") or ""),
        )
    )

    _write_snapshot(new)
    _write_changes_files(out_dir, added_items, counts)

    return {"counts": counts, "added_preview": added_items[:20]}


scheduler = BackgroundScheduler()


def schedule_job():
    scheduler.remove_all_jobs()
    cfg = load_config()
    sch = cfg.get("schedule", {})
    if not sch.get("enabled"):
        return
    hh, mm = sch.get("daily_time", "03:30").split(":")
    trigger = CronTrigger(hour=int(hh), minute=int(mm))
    scheduler.add_job(lambda: do_sync_run("scheduled"), trigger, id="daily_sync", replace_existing=True)


def do_sync_run(reason: str):
    cfg = load_config()

    sync_cfg = cfg.get("sync", {})
    auto_refresh = bool(sync_cfg.get("auto_refresh_playlist", True))

    if auto_refresh:
        m3u_text = download_playlist(cfg)
    else:
        m3u_text = read_playlist_text() or download_playlist(cfg)

    # keep catalog cached so GUI can work without re-download
    try:
        cat = build_catalog(m3u_text)
        write_catalog(cat)
    except Exception:
        pass

    out_dir = Path(cfg["paths"].get("out_dir") or str(OUTPUT_DIR)).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # NEW: track playlist changes globally (independent of selection)
    try:
        track_playlist_changes(m3u_text, out_dir)
    except Exception:
        pass

    # STRM sync still runs (selection-based), but changes UI is now playlist-based
    res = run_sync(
        m3u_text=m3u_text,
        out_dir=out_dir,
        allow_cfg=cfg.get("allow", {}),
        sync_delete=bool(sync_cfg.get("sync_delete", True)),
        prune_sidecars=bool(sync_cfg.get("prune_sidecars", False)),
    )

    payload = {"time": datetime.now().isoformat(timespec="seconds"), "reason": reason, "result": res}
    write_last_run(payload)
    return payload


@app.on_event("startup")
def on_startup():
    if not scheduler.running:
        scheduler.start()
    schedule_job()


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    require_auth(request)
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/config")
def api_get_config(request: Request):
    require_auth(request)
    return JSONResponse(load_config())


@app.post("/api/config")
async def api_set_config(request: Request):
    require_auth(request)
    cfg = await request.json()
    save_config(cfg)
    schedule_job()
    return JSONResponse({"ok": True})


@app.post("/api/refresh")
def api_refresh(request: Request):
    require_auth(request)
    cfg = load_config()
    text = download_playlist(cfg)
    cat = build_catalog(text)
    write_catalog(cat)

    # NEW: track playlist changes also on refresh
    out_dir = Path(cfg["paths"].get("out_dir") or str(OUTPUT_DIR)).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        track_playlist_changes(text, out_dir)
    except Exception:
        pass

    return JSONResponse({"ok": True, "catalog": cat})


@app.get("/api/catalog")
def api_catalog(request: Request):
    require_auth(request)
    text = read_playlist_text()
    if not text:
        return JSONResponse({"ok": False, "error": "No playlist cached. Click 'Playlist laden' first."}, status_code=400)
    cat = build_catalog(text)
    return JSONResponse({"ok": True, "catalog": cat})


@app.get("/api/catalog_cached")
def api_catalog_cached(request: Request):
    require_auth(request)
    cat = read_catalog()
    if not cat:
        return JSONResponse({"ok": False, "error": "No cached catalog yet. Click 'Playlist laden' once."}, status_code=400)
    return JSONResponse({"ok": True, "catalog": cat})


@app.get("/api/changes_latest")
def api_changes_latest(request: Request):
    require_auth(request)
    cfg = load_config()
    out_dir = Path(cfg["paths"].get("out_dir") or str(OUTPUT_DIR)).resolve()
    p = out_dir / "changes_latest.json"
    if not p.exists():
        return JSONResponse({"ok": True, "has_changes": False, "data": None})
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return JSONResponse({"ok": False, "has_changes": False, "error": "changes_latest.json is invalid"}, status_code=500)
    return JSONResponse({"ok": True, "has_changes": True, "data": data})


@app.post("/api/run")
def api_run(request: Request):
    require_auth(request)
    payload = do_sync_run("manual")
    return JSONResponse({"ok": True, "run": payload})


@app.get("/api/status")
def api_status(request: Request):
    require_auth(request)
    cfg = load_config()
    last = read_last_run()

    out_dir = Path(cfg["paths"].get("out_dir") or str(OUTPUT_DIR)).resolve()
    changes_path = out_dir / "changes_latest.json"

    has_changes = changes_path.exists()
    changes = None
    if has_changes:
        try:
            changes = json.loads(changes_path.read_text(encoding="utf-8"))
        except Exception:
            changes = None

    return JSONResponse(
        {
            "ok": True,
            "has_playlist": PLAYLIST_PATH.exists(),
            "has_catalog": CATALOG_PATH.exists(),
            "config_path": str(CONFIG_PATH),
            "playlist_path": str(PLAYLIST_PATH),
            "catalog_path": str(CATALOG_PATH),
            "output_dir": cfg.get("paths", {}).get("out_dir"),
            "last_run": last,
            "has_changes_latest": has_changes,
            "changes_latest_path": str(changes_path),
            "changes_latest": changes,
        }
    )


@app.post("/api/cleanup")
async def api_cleanup(request: Request):
    require_auth(request)
    cfg = load_config()
    body = await request.json()
    targets = set(body.get("targets") or [])
    include_state = bool(body.get("include_state", False))

    out_dir = Path(cfg["paths"].get("out_dir") or str(OUTPUT_DIR)).resolve()

    mapping = {
        "movies": out_dir / "Movies",
        "series": out_dir / "Series",
        "livetv": out_dir / "LiveTV",
    }

    deleted = []
    for t, p in mapping.items():
        if t in targets and p.exists():
            shutil.rmtree(p, ignore_errors=True)
            deleted.append(str(p))

    if include_state:
        state_dir = out_dir / ".xtream_state"
        if state_dir.exists():
            shutil.rmtree(state_dir, ignore_errors=True)
            deleted.append(str(state_dir))

    return JSONResponse({"ok": True, "deleted": deleted})


@app.get("/api/test")
def api_test(request: Request):
    require_auth(request)
    cfg = load_config()
    url = build_player_api_url(cfg)
    try:
        req = UrlReq(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=30) as r:
            data = r.read().decode("utf-8", errors="replace")
        js = json.loads(data)
        user = js.get("user_info", {})
        server = js.get("server_info", {})
        exp_dt = parse_exp_date(user)
        rem = remaining_time(exp_dt) if exp_dt else None

        return JSONResponse(
            {
                "ok": True,
                "player_api": True,
                "user_info": {
                    "status": user.get("status"),
                    "is_trial": user.get("is_trial"),
                    "active_cons": user.get("active_cons"),
                    "max_connections": user.get("max_connections"),
                    "created_at": user.get("created_at"),
                    "exp_date": int(user.get("exp_date")) if str(user.get("exp_date", "")).isdigit() else user.get("exp_date"),
                    "exp_iso": exp_dt.isoformat() if exp_dt else None,
                    "remaining_seconds": rem,
                },
                "server_info": {
                    "url": server.get("url"),
                    "port": server.get("port"),
                    "https_port": server.get("https_port"),
                    "timezone": server.get("timezone"),
                    "timestamp_now": server.get("timestamp_now"),
                },
            }
        )
    except Exception as e:
        try:
            m3u_url = build_m3u_url(cfg)
            req = UrlReq(m3u_url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=30) as r:
                ok = (r.status == 200)
            return JSONResponse({"ok": ok, "player_api": False, "error": str(e)})
        except Exception as e2:
            return JSONResponse({"ok": False, "player_api": False, "error": str(e2)})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=PORT, reload=False)