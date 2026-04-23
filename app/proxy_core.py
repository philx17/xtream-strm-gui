from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from ipaddress import ip_address, ip_network
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
import traceback
import threading
import zlib
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
import json
import time
import tempfile
import os


LOCAL_NETS = [
    ip_network("10.0.0.0/8"),
    ip_network("172.16.0.0/12"),
    ip_network("192.168.0.0/16"),
    ip_network("127.0.0.0/8"),
    ip_network("169.254.0.0/16"),
    ip_network("fc00::/7"),
    ip_network("fe80::/10"),
    ip_network("::1/128"),
]

DEFAULT_XMLTV_URL = "http://192.168.9.222:9981/xmltv"
XMLTV_TIMEOUT = 30
XMLTV_CACHE_SECONDS = 300

APP_DIR = Path(__file__).resolve().parent
PROXY_DATA_DIR = APP_DIR / ".proxy_state"
PROXY_DATA_DIR.mkdir(parents=True, exist_ok=True)

ID_MAP_FILE = PROXY_DATA_DIR / "id_maps.json"
XMLTV_CACHE_FILE = PROXY_DATA_DIR / "xmltv_cache.xml"
XMLTV_META_FILE = PROXY_DATA_DIR / "xmltv_cache_meta.json"

ID_MAP_LOCK = threading.RLock()
ID_MAPS_LOADED = False

PROXY_ID_TO_JELLYFIN: Dict[str, str] = {}
JELLYFIN_TO_PROXY_ID: Dict[str, str] = {}

PROXY_CATEGORY_TO_LIBRARY: Dict[str, str] = {}
LIBRARY_TO_PROXY_CATEGORY: Dict[str, str] = {}

PROXY_LIVE_CATEGORY_TO_NAME: Dict[str, str] = {}
LIVE_CATEGORY_NAME_TO_PROXY: Dict[str, str] = {}

XMLTV_CACHE_LOCK = threading.Lock()
XMLTV_MEMORY_CACHE: Dict[str, Any] = {
    "loaded_from": "",
    "loaded_at": 0.0,
    "channels": {},
    "programmes": {},
}


def _now_ts() -> float:
    return time.time()


def _atomic_write_text(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(path.parent)) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)


def _atomic_write_bytes(path: Path, content: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", delete=False, dir=str(path.parent)) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)


def _read_json_file(path: Path, default: Any):
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json_file(path: Path, payload: Any):
    _atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


def _proxy_cfg(runtime_cfg: Dict[str, Any]) -> Dict[str, Any]:
    return runtime_cfg.get("proxy", {}) if isinstance(runtime_cfg, dict) else {}


def _selection_cfg(runtime_cfg: Dict[str, Any]) -> Dict[str, Any]:
    return runtime_cfg.get("selection", {}) if isinstance(runtime_cfg, dict) else {}


def _selected_library_ids(runtime_cfg: Dict[str, Any]) -> List[str]:
    selection = _selection_cfg(runtime_cfg)
    values = selection.get("proxy_library_ids") or []
    if not isinstance(values, list):
        return []
    return [str(x).strip() for x in values if str(x).strip()]


def _make_jellyfin_client(runtime_cfg: Dict[str, Any]):
    from .jellyfin_api import JellyfinClient

    proxy = _proxy_cfg(runtime_cfg)
    base_url = str(proxy.get("jellyfin_base_url") or "").strip()
    api_key = str(proxy.get("jellyfin_api_key") or "").strip()

    missing = []
    if not base_url:
        missing.append("jellyfin_base_url")
    if not api_key:
        missing.append("jellyfin_api_key")

    if missing:
        raise RuntimeError(
            "Jellyfin Proxy ist nicht vollständig konfiguriert. Fehlend: " + ", ".join(missing)
        )

    return JellyfinClient(base_url, api_key)


def _proxy_credentials_ok(runtime_cfg: Dict[str, Any], username: str, password: str) -> bool:
    proxy = _proxy_cfg(runtime_cfg)
    expected_user = str(proxy.get("username") or "").strip()
    expected_pass = str(proxy.get("password") or "")
    return username == expected_user and password == expected_pass and bool(expected_user)


def _proxy_base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/") + "/proxy"


def _request_host_with_port(request: Request) -> str:
    forwarded_host = request.headers.get("x-forwarded-host", "").strip()
    host = forwarded_host or request.headers.get("host", "").strip() or request.url.netloc
    if "," in host:
        host = host.split(",")[0].strip()
    return host


def _request_host(request: Request) -> str:
    host = _request_host_with_port(request)
    if host.startswith("["):
        return host.lower()
    if ":" in host:
        return host.split(":", 1)[0].strip().lower()
    return host.lower()


def _request_scheme(request: Request) -> str:
    forwarded_proto = request.headers.get("x-forwarded-proto", "").strip()
    if forwarded_proto:
        return forwarded_proto.split(",")[0].strip().lower()
    return str(request.url.scheme or "http").lower()


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "").strip()
    if xff:
        return xff.split(",")[0].strip()
    client = request.client.host if request.client else ""
    return client or ""


def _is_local_request(request: Request) -> bool:
    host = _request_host(request)
    if host in {"localhost"} or host.endswith(".local"):
        return True

    try:
        host_ip = ip_address(host)
        for net in LOCAL_NETS:
            if host_ip in net:
                return True
    except Exception:
        pass

    client = _client_ip(request)
    try:
        client_ip = ip_address(client)
        for net in LOCAL_NETS:
            if client_ip in net:
                return True
    except Exception:
        pass

    return False


def _effective_jellyfin_base_url(runtime_cfg: Dict[str, Any], request: Request) -> str:
    proxy = _proxy_cfg(runtime_cfg)
    local_url = str(proxy.get("jellyfin_base_url") or "").strip()
    external_url = str(proxy.get("jellyfin_external_base_url") or "").strip()

    if not local_url and not external_url:
        return ""

    if _is_local_request(request):
        return local_url or external_url

    return external_url or local_url


def _xmltv_url(runtime_cfg: Dict[str, Any]) -> str:
    proxy = _proxy_cfg(runtime_cfg)
    return str(proxy.get("epg_xml_url") or DEFAULT_XMLTV_URL).strip()


def _is_movie_library(lib: Dict[str, Any]) -> bool:
    collection_type = str(lib.get("collection_type") or "").strip().lower()
    lib_type = str(lib.get("type") or "").strip().lower()
    name = str(lib.get("name") or "").strip().lower()

    if collection_type in {"movies", "movie"}:
        return True
    if lib_type in {"movies", "movie"}:
        return True
    if "film" in name or "movie" in name:
        return True
    return False


def _is_series_library(lib: Dict[str, Any]) -> bool:
    collection_type = str(lib.get("collection_type") or "").strip().lower()
    lib_type = str(lib.get("type") or "").strip().lower()
    name = str(lib.get("name") or "").strip().lower()

    if collection_type in {"tvshows", "tvshow", "series"}:
        return True
    if lib_type in {"tvshows", "tvshow", "series"}:
        return True
    if "serie" in name or "show" in name or "tv" in name:
        return True
    return False


def _get_selected_libraries(client, runtime_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    selected_ids = set(_selected_library_ids(runtime_cfg))
    libs = client.get_libraries()
    if not selected_ids:
        return []
    return [lib for lib in libs if str(lib.get("id")) in selected_ids]


def _get_selected_movie_libraries(client, runtime_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [lib for lib in _get_selected_libraries(client, runtime_cfg) if _is_movie_library(lib)]


def _get_selected_series_libraries(client, runtime_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [lib for lib in _get_selected_libraries(client, runtime_cfg) if _is_series_library(lib)]


def _user_info_ok(username: str) -> Dict[str, Any]:
    return {
        "username": username,
        "auth": 1,
        "status": "Active",
        "is_trial": "0",
        "active_cons": "0",
        "created_at": "0",
        "exp_date": "0",
        "max_connections": "1",
        "allowed_output_formats": ["mp4", "mkv", "ts"],
    }


def _user_info_fail(username: str) -> Dict[str, Any]:
    return {
        "username": username,
        "auth": 0,
        "status": "Disabled",
        "is_trial": "0",
        "active_cons": "0",
        "created_at": "0",
        "exp_date": "0",
        "max_connections": "0",
        "allowed_output_formats": [],
    }


def _server_info(request: Request) -> Dict[str, Any]:
    scheme = _request_scheme(request)
    host_with_port = _request_host_with_port(request)

    if host_with_port:
        base_url = f"{scheme}://{host_with_port}/proxy"
    else:
        base_url = _proxy_base_url(request)

    port = ""
    if ":" in host_with_port and not host_with_port.startswith("["):
        port = host_with_port.split(":", 1)[1]
    elif request.url.port:
        port = str(request.url.port)

    https_port = port if scheme == "https" else ""

    return {
        "url": base_url,
        "port": port,
        "https_port": https_port,
        "server_protocol": scheme,
        "rtmp_port": "0",
        "timezone": "Europe/Berlin",
        "timestamp_now": "",
        "time_now": "",
    }


def _item_year(item: Dict[str, Any]) -> str:
    year = item.get("ProductionYear")
    return str(year) if year not in (None, "") else ""


def _provider_ids(item: Dict[str, Any]) -> Dict[str, Any]:
    raw = item.get("ProviderIds")
    return raw if isinstance(raw, dict) else {}


def _build_direct_stream_url(client, item_id: str, runtime_cfg: Dict[str, Any], request: Request) -> str:
    effective_base = _effective_jellyfin_base_url(runtime_cfg, request)
    stream_url = client.build_stream_url(item_id, "mp4", base_url_override=effective_base)
    return stream_url.replace("/stream.mp4?", "/stream?")


def _load_id_maps_if_needed():
    global ID_MAPS_LOADED

    with ID_MAP_LOCK:
        if ID_MAPS_LOADED:
            return

        payload = _read_json_file(ID_MAP_FILE, {})
        proxy_to_jellyfin = payload.get("proxy_id_to_jellyfin", {})
        jellyfin_to_proxy = payload.get("jellyfin_to_proxy_id", {})
        proxy_cat_to_lib = payload.get("proxy_category_to_library", {})
        lib_to_proxy_cat = payload.get("library_to_proxy_category", {})
        proxy_live_cat_to_name = payload.get("proxy_live_category_to_name", {})
        live_name_to_proxy_cat = payload.get("live_category_name_to_proxy", {})

        if isinstance(proxy_to_jellyfin, dict):
            PROXY_ID_TO_JELLYFIN.update({str(k): str(v) for k, v in proxy_to_jellyfin.items()})
        if isinstance(jellyfin_to_proxy, dict):
            JELLYFIN_TO_PROXY_ID.update({str(k): str(v) for k, v in jellyfin_to_proxy.items()})
        if isinstance(proxy_cat_to_lib, dict):
            PROXY_CATEGORY_TO_LIBRARY.update({str(k): str(v) for k, v in proxy_cat_to_lib.items()})
        if isinstance(lib_to_proxy_cat, dict):
            LIBRARY_TO_PROXY_CATEGORY.update({str(k): str(v) for k, v in lib_to_proxy_cat.items()})
        if isinstance(proxy_live_cat_to_name, dict):
            PROXY_LIVE_CATEGORY_TO_NAME.update({str(k): str(v) for k, v in proxy_live_cat_to_name.items()})
        if isinstance(live_name_to_proxy_cat, dict):
            LIVE_CATEGORY_NAME_TO_PROXY.update({str(k): str(v) for k, v in live_name_to_proxy_cat.items()})

        ID_MAPS_LOADED = True


def _save_id_maps_unlocked():
    payload = {
        "proxy_id_to_jellyfin": PROXY_ID_TO_JELLYFIN,
        "jellyfin_to_proxy_id": JELLYFIN_TO_PROXY_ID,
        "proxy_category_to_library": PROXY_CATEGORY_TO_LIBRARY,
        "library_to_proxy_category": LIBRARY_TO_PROXY_CATEGORY,
        "proxy_live_category_to_name": PROXY_LIVE_CATEGORY_TO_NAME,
        "live_category_name_to_proxy": LIVE_CATEGORY_NAME_TO_PROXY,
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    _write_json_file(ID_MAP_FILE, payload)


def _make_proxy_numeric_id(jellyfin_id: str, kind: str) -> str:
    _load_id_maps_if_needed()
    key = f"{kind}:{jellyfin_id}"

    with ID_MAP_LOCK:
        existing = JELLYFIN_TO_PROXY_ID.get(key)
        if existing:
            return existing

        base = zlib.crc32(key.encode("utf-8")) & 0x7FFFFFFF
        candidate = str(base if base > 0 else 1)

        while True:
            existing_jf = PROXY_ID_TO_JELLYFIN.get(candidate)
            if existing_jf is None or existing_jf == jellyfin_id:
                PROXY_ID_TO_JELLYFIN[candidate] = jellyfin_id
                JELLYFIN_TO_PROXY_ID[key] = candidate
                _save_id_maps_unlocked()
                return candidate
            base += 1
            candidate = str(base)


def _resolve_jellyfin_id(item_id: str) -> str:
    _load_id_maps_if_needed()
    value = str(item_id or "").strip()
    if not value:
        return ""
    with ID_MAP_LOCK:
        return PROXY_ID_TO_JELLYFIN.get(value, value)


def _make_proxy_category_id(library_id: str, kind: str) -> str:
    _load_id_maps_if_needed()
    key = f"{kind}:{library_id}"

    with ID_MAP_LOCK:
        existing = LIBRARY_TO_PROXY_CATEGORY.get(key)
        if existing:
            return existing

        base = zlib.crc32(key.encode("utf-8")) & 0x7FFFFFFF
        candidate = str(base if base > 0 else 1)

        while True:
            existing_lib = PROXY_CATEGORY_TO_LIBRARY.get(candidate)
            if existing_lib is None or existing_lib == library_id:
                PROXY_CATEGORY_TO_LIBRARY[candidate] = library_id
                LIBRARY_TO_PROXY_CATEGORY[key] = candidate
                _save_id_maps_unlocked()
                return candidate
            base += 1
            candidate = str(base)


def _resolve_category_id(category_id: str) -> str:
    _load_id_maps_if_needed()
    value = str(category_id or "").strip()
    if not value:
        return ""
    with ID_MAP_LOCK:
        return PROXY_CATEGORY_TO_LIBRARY.get(value, value)


def _make_live_category_id(group_name: str) -> str:
    _load_id_maps_if_needed()
    normalized = str(group_name or "").strip() or "LiveTV"
    key = f"live:{normalized}"

    with ID_MAP_LOCK:
        existing = LIVE_CATEGORY_NAME_TO_PROXY.get(key)
        if existing:
            return existing

        base = zlib.crc32(key.encode("utf-8")) & 0x7FFFFFFF
        candidate = str(base if base > 0 else 1)

        while True:
            existing_name = PROXY_LIVE_CATEGORY_TO_NAME.get(candidate)
            if existing_name is None or existing_name == normalized:
                PROXY_LIVE_CATEGORY_TO_NAME[candidate] = normalized
                LIVE_CATEGORY_NAME_TO_PROXY[key] = candidate
                _save_id_maps_unlocked()
                return candidate
            base += 1
            candidate = str(base)


def _resolve_live_category_id(category_id: str) -> str:
    _load_id_maps_if_needed()
    value = str(category_id or "").strip()
    if not value:
        return ""
    with ID_MAP_LOCK:
        return PROXY_LIVE_CATEGORY_TO_NAME.get(value, value)


def _library_to_category(lib: Dict[str, Any], kind: str) -> Dict[str, Any]:
    library_id = str(lib.get("id") or "")
    proxy_category_id = _make_proxy_category_id(library_id, kind)
    return {
        "category_id": int(proxy_category_id),
        "category_name": str(lib.get("name") or "Unbekannt"),
        "parent_id": 0,
    }


def _build_live_categories(channels: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    names = set()
    for ch in channels:
        group_name = str(ch.get("group_name") or "LiveTV").strip() or "LiveTV"
        names.add(group_name)

    result = []
    for name in sorted(names, key=lambda x: x.lower()):
        result.append({
            "category_id": int(_make_live_category_id(name)),
            "category_name": name,
            "parent_id": 0,
        })
    return result


def _normalize_channel_name(value: str) -> str:
    value = (value or "").strip().lower()
    repl = [
        (" hd", ""),
        (" fhd", ""),
        (" uhd", ""),
        (" 4k", ""),
        (" 8k", ""),
        (" de", ""),
        (" at", ""),
        (" ch", ""),
        (" ger", ""),
        (" | ", " "),
        (" - ", " "),
        ("_", " "),
        ("-", " "),
    ]
    for a, b in repl:
        value = value.replace(a, b)
    while "  " in value:
        value = value.replace("  ", " ")
    return value.strip()


def _parse_xmltv_time(value: str) -> Optional[datetime]:
    value = (value or "").strip()
    if not value:
        return None

    for fmt in ("%Y%m%d%H%M%S %z", "%Y%m%d%H%M%S%z", "%Y%m%d%H%M%S"):
        try:
            dt = datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            continue
    return None


def _parse_xmltv_content(content: bytes) -> Tuple[Dict[str, str], Dict[str, List[Dict[str, Any]]]]:
    root = ET.fromstring(content)

    channels: Dict[str, str] = {}
    programmes: Dict[str, List[Dict[str, Any]]] = {}

    for ch in root.findall("channel"):
        channel_id = str(ch.attrib.get("id") or "").strip()
        if not channel_id:
            continue

        display_name = ""
        dn = ch.find("display-name")
        if dn is not None and dn.text:
            display_name = dn.text.strip()

        if not display_name:
            display_name = channel_id

        channels[channel_id] = display_name

    for pr in root.findall("programme"):
        channel_id = str(pr.attrib.get("channel") or "").strip()
        if not channel_id:
            continue

        start_raw = str(pr.attrib.get("start") or "").strip()
        stop_raw = str(pr.attrib.get("stop") or "").strip()

        start_dt = _parse_xmltv_time(start_raw)
        stop_dt = _parse_xmltv_time(stop_raw)

        title = ""
        desc = ""
        title_el = pr.find("title")
        desc_el = pr.find("desc")

        if title_el is not None and title_el.text:
            title = title_el.text.strip()
        if desc_el is not None and desc_el.text:
            desc = desc_el.text.strip()

        entry = {
            "channel_id": channel_id,
            "start": start_dt,
            "stop": stop_dt,
            "title": title,
            "description": desc,
        }
        programmes.setdefault(channel_id, []).append(entry)

    for channel_id in list(programmes.keys()):
        programmes[channel_id] = sorted(
            programmes[channel_id],
            key=lambda x: x["start"] or datetime.min.replace(tzinfo=timezone.utc)
        )

    return channels, programmes


def _load_xmltv(runtime_cfg: Dict[str, Any]) -> Tuple[Dict[str, str], Dict[str, List[Dict[str, Any]]]]:
    xmltv_url = _xmltv_url(runtime_cfg)
    now = _now_ts()

    with XMLTV_CACHE_LOCK:
        mem_source = XMLTV_MEMORY_CACHE.get("loaded_from", "")
        mem_time = float(XMLTV_MEMORY_CACHE.get("loaded_at", 0.0))
        if mem_source == xmltv_url and (now - mem_time) < XMLTV_CACHE_SECONDS:
            return XMLTV_MEMORY_CACHE["channels"], XMLTV_MEMORY_CACHE["programmes"]

    meta = _read_json_file(XMLTV_META_FILE, {})
    meta_source = str(meta.get("source") or "")
    meta_fetched_at = float(meta.get("fetched_at", 0.0) or 0.0)

    should_refresh = (meta_source != xmltv_url) or ((now - meta_fetched_at) >= XMLTV_CACHE_SECONDS)

    xml_content: Optional[bytes] = None
    fetched_fresh = False

    if should_refresh:
        try:
            response = requests.get(xmltv_url, timeout=XMLTV_TIMEOUT)
            response.raise_for_status()
            xml_content = response.content
            _atomic_write_bytes(XMLTV_CACHE_FILE, xml_content)
            _write_json_file(XMLTV_META_FILE, {
                "source": xmltv_url,
                "fetched_at": now,
                "size": len(xml_content),
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
            fetched_fresh = True
        except Exception:
            xml_content = None

    if xml_content is None:
        if XMLTV_CACHE_FILE.exists():
            xml_content = XMLTV_CACHE_FILE.read_bytes()
        else:
            raise RuntimeError("Keine XMLTV-Daten verfügbar und kein Cache vorhanden.")

    channels, programmes = _parse_xmltv_content(xml_content)

    with XMLTV_CACHE_LOCK:
        XMLTV_MEMORY_CACHE["loaded_from"] = xmltv_url
        XMLTV_MEMORY_CACHE["loaded_at"] = now if fetched_fresh else meta_fetched_at or now
        XMLTV_MEMORY_CACHE["channels"] = channels
        XMLTV_MEMORY_CACHE["programmes"] = programmes

    return channels, programmes


def _find_xmltv_channel_for_live_item(runtime_cfg: Dict[str, Any], live_item: Dict[str, Any]) -> Optional[str]:
    channels, _ = _load_xmltv(runtime_cfg)

    epg_id = str(live_item.get("epg_channel_id") or "").strip()
    if epg_id and epg_id in channels:
        return epg_id

    normalized_live_name = _normalize_channel_name(str(live_item.get("Name") or ""))

    for channel_id, display_name in channels.items():
        if epg_id and epg_id == channel_id:
            return channel_id
        if normalized_live_name and normalized_live_name == _normalize_channel_name(display_name):
            return channel_id
        if normalized_live_name and normalized_live_name == _normalize_channel_name(channel_id):
            return channel_id

    return None


def _build_short_epg_for_stream(runtime_cfg: Dict[str, Any], live_item: Dict[str, Any], limit: int = 10) -> Dict[str, Any]:
    channel_id = _find_xmltv_channel_for_live_item(runtime_cfg, live_item)
    if not channel_id:
        return {"epg_listings": []}

    _, programmes = _load_xmltv(runtime_cfg)
    items = programmes.get(channel_id, [])
    now = datetime.now(timezone.utc)

    future_or_current = []
    for item in items:
        stop_dt = item.get("stop")
        if stop_dt and stop_dt < now:
            continue
        future_or_current.append(item)

    listings = []
    for item in future_or_current[:max(1, limit)]:
        start_dt = item.get("start")
        stop_dt = item.get("stop")

        start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S") if isinstance(start_dt, datetime) else ""
        stop_str = stop_dt.strftime("%Y-%m-%d %H:%M:%S") if isinstance(stop_dt, datetime) else ""

        listings.append({
            "id": str(int((start_dt.timestamp() if start_dt else now.timestamp()))),
            "epg_id": str(int((start_dt.timestamp() if start_dt else now.timestamp()))),
            "title": item.get("title") or "",
            "description": item.get("description") or "",
            "start": start_str,
            "end": stop_str,
            "start_timestamp": str(int(start_dt.timestamp())) if isinstance(start_dt, datetime) else "0",
            "stop_timestamp": str(int(stop_dt.timestamp())) if isinstance(stop_dt, datetime) else "0",
            "now_playing": 1 if isinstance(start_dt, datetime) and isinstance(stop_dt, datetime) and start_dt <= now <= stop_dt else 0,
            "has_archive": 0,
        })

    return {"epg_listings": listings}


def _build_simple_data_table(runtime_cfg: Dict[str, Any], live_item: Dict[str, Any]) -> Dict[str, Any]:
    short_epg = _build_short_epg_for_stream(runtime_cfg, live_item, limit=20)
    listings = short_epg.get("epg_listings", [])

    channel_id = _find_xmltv_channel_for_live_item(runtime_cfg, live_item) or ""
    current = next((x for x in listings if int(x.get("now_playing", 0)) == 1), None)

    return {
        "epg_id": channel_id,
        "epg_listings": listings,
        "now_playing": current or {},
    }


def _vod_item_to_xtream(client, lib: Dict[str, Any], item: Dict[str, Any], request: Request, runtime_cfg: Dict[str, Any]) -> Dict[str, Any]:
    jellyfin_id = str(item.get("Id") or "")
    proxy_id = _make_proxy_numeric_id(jellyfin_id, "movie")
    title = str(item.get("Name") or "Unknown Movie")
    year = _item_year(item)
    providers = _provider_ids(item)
    effective_base = _effective_jellyfin_base_url(runtime_cfg, request)

    library_id = str(lib.get("id") or "")
    proxy_category_id = _make_proxy_category_id(library_id, "movie_category")

    return {
        "num": int(proxy_id),
        "name": title,
        "stream_type": "movie",
        "stream_id": int(proxy_id),
        "stream_icon": client.build_image_url(jellyfin_id, base_url_override=effective_base),
        "rating": "0",
        "rating_5based": 0,
        "added": "0",
        "is_adult": "0",
        "category_id": int(proxy_category_id),
        "category_ids": [int(proxy_category_id)],
        "container_extension": "mp4",
        "custom_sid": "",
        "direct_source": "",
        "year": year,
        "tmdb": str(providers.get("Tmdb") or ""),
        "plot": str(item.get("Overview") or ""),
    }


def _series_item_to_xtream(client, lib: Dict[str, Any], item: Dict[str, Any], request: Request, runtime_cfg: Dict[str, Any]) -> Dict[str, Any]:
    jellyfin_id = str(item.get("Id") or "")
    proxy_id = _make_proxy_numeric_id(jellyfin_id, "series")
    title = str(item.get("Name") or "Unknown Series")
    year = _item_year(item)
    effective_base = _effective_jellyfin_base_url(runtime_cfg, request)
    providers = _provider_ids(item)

    library_id = str(lib.get("id") or "")
    proxy_category_id = _make_proxy_category_id(library_id, "series_category")

    return {
        "num": int(proxy_id),
        "name": title,
        "series_id": int(proxy_id),
        "cover": client.build_image_url(jellyfin_id, base_url_override=effective_base),
        "plot": str(item.get("Overview") or ""),
        "cast": "",
        "director": "",
        "genre": "",
        "releaseDate": year,
        "release_date": year,
        "last_modified": "0",
        "rating": "0",
        "rating_5based": 0,
        "backdrop_path": [],
        "youtube_trailer": "",
        "tmdb": str(providers.get("Tmdb") or ""),
        "episode_run_time": "0",
        "category_id": int(proxy_category_id),
        "category_ids": [int(proxy_category_id)],
    }


def _live_item_to_xtream(client, item: Dict[str, Any], request: Request, runtime_cfg: Dict[str, Any]) -> Dict[str, Any]:
    jellyfin_id = str(item.get("Id") or "")
    proxy_id = _make_proxy_numeric_id(jellyfin_id, "live")
    effective_base = _effective_jellyfin_base_url(runtime_cfg, request)

    name = str(item.get("Name") or "Unknown Channel")
    group_name = str(item.get("group_name") or "LiveTV").strip() or "LiveTV"
    proxy_category_id = _make_live_category_id(group_name)

    xmltv_channel_id = _find_xmltv_channel_for_live_item(runtime_cfg, item)
    epg_channel_id = xmltv_channel_id or str(item.get("epg_channel_id") or "")

    return {
        "num": int(proxy_id),
        "name": name,
        "stream_type": "live",
        "stream_id": int(proxy_id),
        "stream_icon": client.build_image_url(jellyfin_id, base_url_override=effective_base),
        "epg_channel_id": epg_channel_id,
        "added": "0",
        "is_adult": "0",
        "category_id": int(proxy_category_id),
        "category_ids": [int(proxy_category_id)],
        "container_extension": "ts",
        "custom_sid": "",
        "direct_source": "",
        "tv_archive": 0,
    }


def _group_episodes_by_season(client, episodes: List[Dict[str, Any]], request: Request, runtime_cfg: Dict[str, Any], series_tmdb: str = "") -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    effective_base = _effective_jellyfin_base_url(runtime_cfg, request)

    for ep in episodes:
        if not isinstance(ep, dict):
            continue

        season_no = ep.get("ParentIndexNumber")
        episode_no = ep.get("IndexNumber")
        jellyfin_id = str(ep.get("Id") or "").strip()
        if not jellyfin_id:
            continue

        proxy_id = _make_proxy_numeric_id(jellyfin_id, "episode")

        season_num = int(season_no) if isinstance(season_no, int) or str(season_no).isdigit() else 0
        episode_num = int(episode_no) if isinstance(episode_no, int) or str(episode_no).isdigit() else 0
        season_key = str(season_num)

        image_url = client.build_image_url(jellyfin_id, base_url_override=effective_base)

        grouped.setdefault(season_key, []).append({
            "id": int(proxy_id),
            "episode_num": episode_num,
            "season": season_num,
            "title": str(ep.get("Name") or f"Episode {episode_num or 0}"),
            "container_extension": "mp4",
            "custom_sid": None,
            "added": "0",
            "direct_source": "",
            "info": {
                "air_date": "",
                "rating": 0,
                "id": int(series_tmdb) if str(series_tmdb).isdigit() else 0,
                "movie_image": image_url,
                "duration_secs": 0,
                "duration": "",
                "plot": str(ep.get("Overview") or ""),
                "video_path": "",
            },
            "url": "",
            "plot": str(ep.get("Overview") or ""),
        })

    for season_key in grouped.keys():
        grouped[season_key] = sorted(grouped[season_key], key=lambda x: x.get("episode_num", 0))

    return grouped


def _playback_redirect(runtime_cfg: Dict[str, Any], request: Request, username: str, password: str, item_id: str):
    if not _proxy_credentials_ok(runtime_cfg, username, password):
        return JSONResponse({"error": "Ungültige Zugangsdaten."}, status_code=401)

    client = _make_jellyfin_client(runtime_cfg)
    jellyfin_id = _resolve_jellyfin_id(item_id)
    if not jellyfin_id:
        return JSONResponse({"error": "Ungültige Stream-ID."}, status_code=404)

    stream_url = _build_direct_stream_url(client, jellyfin_id, runtime_cfg, request)
    return RedirectResponse(stream_url, status_code=307)


def _live_playback_redirect(runtime_cfg: Dict[str, Any], request: Request, username: str, password: str, item_id: str):
    if not _proxy_credentials_ok(runtime_cfg, username, password):
        return JSONResponse({"error": "Ungültige Zugangsdaten."}, status_code=401)

    client = _make_jellyfin_client(runtime_cfg)
    jellyfin_id = _resolve_jellyfin_id(item_id)
    if not jellyfin_id:
        return JSONResponse({"error": "Ungültige Live-ID."}, status_code=404)

    stream_url = client.build_live_stream_url(
        jellyfin_id,
        base_url_override=_effective_jellyfin_base_url(runtime_cfg, request),
    )
    return RedirectResponse(stream_url, status_code=307)


def handle_movie_stream(runtime_cfg: Dict[str, Any], request: Request, username: str, password: str, item_id: str, ext: str):
    return _playback_redirect(runtime_cfg, request, username, password, item_id)


def handle_series_stream(runtime_cfg: Dict[str, Any], request: Request, username: str, password: str, item_id: str, ext: str):
    return _playback_redirect(runtime_cfg, request, username, password, item_id)


def handle_live_stream(runtime_cfg: Dict[str, Any], request: Request, username: str, password: str, item_id: str, ext: str):
    return _live_playback_redirect(runtime_cfg, request, username, password, item_id)


def handle_player_api(
    runtime_cfg: Dict[str, Any],
    request: Request,
    username: str,
    password: str,
    action: Optional[str] = None,
    category_id: Optional[str] = None,
    series_id: Optional[str] = None,
    stream_id: Optional[str] = None,
    limit: Optional[str] = None,
):
    try:
        if not _proxy_credentials_ok(runtime_cfg, username, password):
            return JSONResponse({
                "user_info": _user_info_fail(username),
                "server_info": _server_info(request),
            })

        client = _make_jellyfin_client(runtime_cfg)
        selected_movie_libs = _get_selected_movie_libraries(client, runtime_cfg)
        selected_series_libs = _get_selected_series_libraries(client, runtime_cfg)

        if action in (None, "", "get_account_info"):
            return JSONResponse({
                "user_info": _user_info_ok(username),
                "server_info": _server_info(request),
            })

        if action == "get_live_categories":
            channels = client.get_live_channels()
            return JSONResponse(_build_live_categories(channels))

        if action == "get_live_streams":
            channels = client.get_live_channels()
            resolved_live_category = _resolve_live_category_id(category_id or "") if category_id else ""

            results: List[Dict[str, Any]] = []
            for ch in channels:
                group_name = str(ch.get("group_name") or "LiveTV").strip() or "LiveTV"
                if resolved_live_category and group_name != resolved_live_category:
                    continue
                results.append(_live_item_to_xtream(client, ch, request, runtime_cfg))
            return JSONResponse(results)

        if action == "get_short_epg":
            if not stream_id:
                return JSONResponse({"epg_listings": []})

            jellyfin_live_id = _resolve_jellyfin_id(stream_id)
            channels = client.get_live_channels()
            target = None
            for ch in channels:
                if str(ch.get("Id") or "") == jellyfin_live_id:
                    target = ch
                    break

            if not target:
                return JSONResponse({"epg_listings": []})

            epg_limit = 10
            if str(limit or "").isdigit():
                epg_limit = max(1, min(50, int(limit)))

            return JSONResponse(_build_short_epg_for_stream(runtime_cfg, target, limit=epg_limit))

        if action == "get_simple_data_table":
            if not stream_id:
                return JSONResponse({"epg_listings": [], "now_playing": {}})

            jellyfin_live_id = _resolve_jellyfin_id(stream_id)
            channels = client.get_live_channels()
            target = None
            for ch in channels:
                if str(ch.get("Id") or "") == jellyfin_live_id:
                    target = ch
                    break

            if not target:
                return JSONResponse({"epg_listings": [], "now_playing": {}})

            return JSONResponse(_build_simple_data_table(runtime_cfg, target))

        if action == "get_vod_categories":
            return JSONResponse([_library_to_category(lib, "movie_category") for lib in selected_movie_libs])

        if action == "get_series_categories":
            return JSONResponse([_library_to_category(lib, "series_category") for lib in selected_series_libs])

        user_id = client.resolve_user_id()

        if action == "get_vod_streams":
            results: List[Dict[str, Any]] = []
            resolved_category_id = _resolve_category_id(category_id or "") if category_id else ""

            for lib in selected_movie_libs:
                if resolved_category_id and str(lib.get("id")) != str(resolved_category_id):
                    continue
                items = client.get_items(user_id, str(lib.get("id")), "Movie", recursive=True)
                for item in items:
                    results.append(_vod_item_to_xtream(client, lib, item, request, runtime_cfg))
            return JSONResponse(results)

        if action == "get_series":
            results: List[Dict[str, Any]] = []
            resolved_category_id = _resolve_category_id(category_id or "") if category_id else ""

            for lib in selected_series_libs:
                if resolved_category_id and str(lib.get("id")) != str(resolved_category_id):
                    continue
                items = client.get_items(user_id, str(lib.get("id")), "Series", recursive=True)
                for item in items:
                    results.append(_series_item_to_xtream(client, lib, item, request, runtime_cfg))
            return JSONResponse(results)

        if action == "get_series_info":
            if not series_id:
                return JSONResponse({"info": {}, "episodes": {}, "seasons": []})

            target_series_jf_id = _resolve_jellyfin_id(series_id)

            target_series: Optional[Dict[str, Any]] = None
            target_lib: Optional[Dict[str, Any]] = None

            for lib in selected_series_libs:
                items = client.get_items(user_id, str(lib.get("id")), "Series", recursive=True)
                for item in items:
                    if str(item.get("Id") or "") == str(target_series_jf_id):
                        target_series = item
                        target_lib = lib
                        break
                if target_series:
                    break

            if not target_series or not target_lib:
                return JSONResponse({"info": {}, "episodes": {}, "seasons": []})

            providers = _provider_ids(target_series)
            series_tmdb = str(providers.get("Tmdb") or "")
            episodes = client.get_series_episodes(user_id, str(target_series_jf_id))
            effective_base = _effective_jellyfin_base_url(runtime_cfg, request)
            grouped_episodes = _group_episodes_by_season(
                client,
                episodes,
                request,
                runtime_cfg,
                series_tmdb=series_tmdb,
            )

            cover_url = client.build_image_url(
                str(target_series.get("Id") or ""),
                base_url_override=effective_base,
            )

            library_id = str(target_lib.get("id") or "")
            proxy_category_id = _make_proxy_category_id(library_id, "series_category")

            seasons = []
            for season_key in sorted(grouped_episodes.keys(), key=lambda x: int(x) if str(x).isdigit() else 0):
                season_num = int(season_key) if str(season_key).isdigit() else 0
                seasons.append({
                    "name": f"Season {season_num}",
                    "episode_count": str(len(grouped_episodes.get(season_key, []))),
                    "overview": "",
                    "air_date": "",
                    "cover": cover_url,
                    "cover_tmdb": cover_url,
                    "season_number": season_num,
                    "cover_big": cover_url,
                    "releaseDate": _item_year(target_series),
                    "duration": "0",
                })

            info = {
                "name": str(target_series.get("Name") or ""),
                "cover": cover_url,
                "cover_big": cover_url,
                "plot": str(target_series.get("Overview") or ""),
                "cast": "",
                "director": "",
                "genre": "",
                "releaseDate": _item_year(target_series),
                "release_date": _item_year(target_series),
                "last_modified": "0",
                "rating": "0",
                "rating_5based": 0,
                "backdrop_path": [],
                "tmdb": series_tmdb,
                "tvdb_id": str(providers.get("Tvdb") or ""),
                "youtube_trailer": "",
                "episode_run_time": "0",
                "category_id": int(proxy_category_id),
                "category_ids": [int(proxy_category_id)],
            }

            return JSONResponse({
                "seasons": seasons,
                "info": info,
                "episodes": grouped_episodes,
            })

        return JSONResponse({"error": f"Unbekannte action: {action}"}, status_code=400)

    except Exception as exc:
        detail = {
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "request_mode": "local" if _is_local_request(request) else "external",
            "request_host": _request_host_with_port(request),
            "client_ip": _client_ip(request),
            "effective_jellyfin_url": _effective_jellyfin_base_url(runtime_cfg, request),
            "xmltv_url": _xmltv_url(runtime_cfg),
            "action": action,
            "category_id": category_id,
            "series_id": series_id,
            "stream_id": stream_id,
        }
        return JSONResponse(detail, status_code=500)