from __future__ import annotations

from typing import Any, Dict, List, Optional
from ipaddress import ip_address, ip_network
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
import traceback

from .jellyfin_api import JellyfinClient


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


def _make_jellyfin_client(runtime_cfg: Dict[str, Any]) -> JellyfinClient:
    proxy = _proxy_cfg(runtime_cfg)
    base_url = proxy.get("jellyfin_base_url") or ""
    api_key = proxy.get("jellyfin_api_key") or ""
    if not base_url or not api_key:
        raise RuntimeError("Jellyfin Proxy ist nicht vollständig konfiguriert.")
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


def _get_selected_libraries(client: JellyfinClient, runtime_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    selected_ids = set(_selected_library_ids(runtime_cfg))
    libs = client.get_libraries()
    if not selected_ids:
        return []
    return [lib for lib in libs if str(lib.get("id")) in selected_ids]


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
        "allowed_output_formats": ["mp4", "mkv"],
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


def _library_to_category(lib: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "category_id": str(lib.get("id") or ""),
        "category_name": str(lib.get("name") or "Unbekannt"),
        "parent_id": 0,
    }


def _item_year(item: Dict[str, Any]) -> str:
    year = item.get("ProductionYear")
    return str(year) if year not in (None, "") else ""


def _provider_ids(item: Dict[str, Any]) -> Dict[str, Any]:
    raw = item.get("ProviderIds")
    return raw if isinstance(raw, dict) else {}


def _build_direct_stream_url(
    client: JellyfinClient,
    item_id: str,
    runtime_cfg: Dict[str, Any],
    request: Request,
) -> str:
    effective_base = _effective_jellyfin_base_url(runtime_cfg, request)
    stream_url = client.build_stream_url(item_id, "mp4", base_url_override=effective_base)
    return stream_url.replace("/stream.mp4?", "/stream?")


def _vod_item_to_xtream(
    client: JellyfinClient,
    lib: Dict[str, Any],
    item: Dict[str, Any],
    request: Request,
    runtime_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    item_id = str(item.get("Id") or "")
    title = str(item.get("Name") or "Unknown Movie")
    year = _item_year(item)
    providers = _provider_ids(item)
    effective_base = _effective_jellyfin_base_url(runtime_cfg, request)
    direct_stream_url = _build_direct_stream_url(client, item_id, runtime_cfg, request)

    return {
        "num": 1,
        "name": title,
        "stream_type": "movie",
        "stream_id": item_id,
        "stream_icon": client.build_image_url(item_id, base_url_override=effective_base),
        "rating": "",
        "rating_5based": 0,
        "added": "",
        "is_adult": "0",
        "category_id": str(lib.get("id") or ""),
        "category_ids": [str(lib.get("id") or "")],
        "container_extension": "mp4",
        "custom_sid": "",
        "direct_source": direct_stream_url,
        "year": year,
        "tmdb": str(providers.get("Tmdb") or ""),
        "plot": str(item.get("Overview") or ""),
    }


def _series_item_to_xtream(
    client: JellyfinClient,
    lib: Dict[str, Any],
    item: Dict[str, Any],
    request: Request,
    runtime_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    item_id = str(item.get("Id") or "")
    title = str(item.get("Name") or "Unknown Series")
    year = _item_year(item)
    effective_base = _effective_jellyfin_base_url(runtime_cfg, request)
    providers = _provider_ids(item)

    return {
        "num": 1,
        "name": title,
        "series_id": item_id,
        "cover": client.build_image_url(item_id, base_url_override=effective_base),
        "plot": str(item.get("Overview") or ""),
        "cast": "",
        "director": "",
        "genre": "",
        "releaseDate": year,
        "release_date": year,
        "last_modified": "",
        "rating": "",
        "rating_5based": 0,
        "backdrop_path": [],
        "youtube_trailer": "",
        "tmdb": str(providers.get("Tmdb") or ""),
        "episode_run_time": "0",
        "category_id": str(lib.get("id") or ""),
        "category_ids": [str(lib.get("id") or "")],
    }


def _group_episodes_by_season(
    client: JellyfinClient,
    episodes: List[Dict[str, Any]],
    request: Request,
    runtime_cfg: Dict[str, Any],
    series_tmdb: str = "",
) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    effective_base = _effective_jellyfin_base_url(runtime_cfg, request)

    for ep in episodes:
        if not isinstance(ep, dict):
            continue

        season_no = ep.get("ParentIndexNumber")
        episode_no = ep.get("IndexNumber")
        item_id = str(ep.get("Id") or "").strip()
        if not item_id:
            continue

        season_num = int(season_no) if isinstance(season_no, int) or str(season_no).isdigit() else 0
        episode_num = int(episode_no) if isinstance(episode_no, int) or str(episode_no).isdigit() else 0
        season_key = str(season_num)

        stream_url = _build_direct_stream_url(client, item_id, runtime_cfg, request)
        image_url = client.build_image_url(item_id, base_url_override=effective_base)

        grouped.setdefault(season_key, []).append({
            "id": item_id,
            "episode_num": episode_num,
            "season": season_num,
            "title": str(ep.get("Name") or f"Episode {episode_num or 0}"),
            "container_extension": "mp4",
            "custom_sid": None,
            "added": "",
            "direct_source": stream_url,
            "info": {
                "air_date": "",
                "rating": 0,
                "id": int(series_tmdb) if str(series_tmdb).isdigit() else 0,
                "movie_image": image_url,
                "duration_secs": 0,
                "duration": "",
                "plot": str(ep.get("Overview") or ""),
                "video_path": stream_url,
            },
            "url": stream_url,
            "plot": str(ep.get("Overview") or ""),
        })

    for season_key in grouped.keys():
        grouped[season_key] = sorted(grouped[season_key], key=lambda x: x.get("episode_num", 0))

    return grouped


def _playback_redirect(
    runtime_cfg: Dict[str, Any],
    request: Request,
    username: str,
    password: str,
    item_id: str,
) -> RedirectResponse | JSONResponse:
    if not _proxy_credentials_ok(runtime_cfg, username, password):
        return JSONResponse({"error": "Ungültige Zugangsdaten."}, status_code=401)

    client = _make_jellyfin_client(runtime_cfg)
    stream_url = _build_direct_stream_url(client, item_id, runtime_cfg, request)
    return RedirectResponse(stream_url, status_code=307)


def handle_movie_stream(
    runtime_cfg: Dict[str, Any],
    request: Request,
    username: str,
    password: str,
    item_id: str,
    ext: str,
):
    return _playback_redirect(runtime_cfg, request, username, password, item_id)


def handle_series_stream(
    runtime_cfg: Dict[str, Any],
    request: Request,
    username: str,
    password: str,
    item_id: str,
    ext: str,
):
    return _playback_redirect(runtime_cfg, request, username, password, item_id)


def handle_player_api(
    runtime_cfg: Dict[str, Any],
    request: Request,
    username: str,
    password: str,
    action: Optional[str] = None,
    category_id: Optional[str] = None,
    series_id: Optional[str] = None,
):
    try:
        if not _proxy_credentials_ok(runtime_cfg, username, password):
            return JSONResponse({
                "user_info": _user_info_fail(username),
                "server_info": _server_info(request),
            })

        client = _make_jellyfin_client(runtime_cfg)
        selected_libs = _get_selected_libraries(client, runtime_cfg)

        if action in (None, "", "get_account_info"):
            return JSONResponse({
                "user_info": _user_info_ok(username),
                "server_info": _server_info(request),
            })

        if action == "get_live_categories":
            return JSONResponse([])

        if action == "get_live_streams":
            return JSONResponse([])

        if action == "get_vod_categories":
            return JSONResponse([_library_to_category(lib) for lib in selected_libs])

        if action == "get_series_categories":
            return JSONResponse([_library_to_category(lib) for lib in selected_libs])

        user_id = client.resolve_user_id()

        if action == "get_vod_streams":
            results: List[Dict[str, Any]] = []
            for lib in selected_libs:
                if category_id and str(lib.get("id")) != str(category_id):
                    continue
                items = client.get_items(user_id, str(lib.get("id")), "Movie", recursive=True)
                for item in items:
                    results.append(_vod_item_to_xtream(client, lib, item, request, runtime_cfg))
            return JSONResponse(results)

        if action == "get_series":
            results: List[Dict[str, Any]] = []
            for lib in selected_libs:
                if category_id and str(lib.get("id")) != str(category_id):
                    continue
                items = client.get_items(user_id, str(lib.get("id")), "Series", recursive=True)
                for item in items:
                    results.append(_series_item_to_xtream(client, lib, item, request, runtime_cfg))
            return JSONResponse(results)

        if action == "get_series_info":
            if not series_id:
                return JSONResponse({"info": {}, "episodes": {}, "seasons": []})

            target_series: Optional[Dict[str, Any]] = None
            target_lib: Optional[Dict[str, Any]] = None

            for lib in selected_libs:
                items = client.get_items(user_id, str(lib.get("id")), "Series", recursive=True)
                for item in items:
                    if str(item.get("Id") or "") == str(series_id):
                        target_series = item
                        target_lib = lib
                        break
                if target_series:
                    break

            if not target_series or not target_lib:
                return JSONResponse({"info": {}, "episodes": {}, "seasons": []})

            providers = _provider_ids(target_series)
            series_tmdb = str(providers.get("Tmdb") or "")
            episodes = client.get_series_episodes(user_id, str(series_id))
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
                "last_modified": "",
                "rating": "",
                "rating_5based": 0,
                "backdrop_path": [],
                "tmdb": series_tmdb,
                "tvdb_id": str(providers.get("Tvdb") or ""),
                "youtube_trailer": "",
                "episode_run_time": "0",
                "category_id": str(target_lib.get("id") or ""),
                "category_ids": [str(target_lib.get("id") or "")],
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
            "action": action,
            "category_id": category_id,
            "series_id": series_id,
        }
        return JSONResponse(detail, status_code=500)