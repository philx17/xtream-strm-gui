from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional
import os
import shutil

from .xtream_api import XtreamClient
from .state_core import (
    append_job_log,
    set_job_status,
    save_last_report,
    load_manifest,
    save_manifest,
    clear_manifest,
    clear_last_report,
)



def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except Exception:
        return default


def _safe_dt_from_unix(value: Any) -> Optional[str]:
    ts = _safe_int(value)
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return None


def _clean_base_url(url: str) -> str:
    return (url or "").strip().rstrip("/")


@dataclass
class XtreamClient:
    base_url: str
    username: str
    password: str
    timeout: int = 45

    def __post_init__(self):
        self.base_url = _clean_base_url(self.base_url)
        self.username = (self.username or "").strip()
        self.password = (self.password or "").strip()

        if not self.base_url or not self.username or not self.password:
            raise ValueError("base_url, username und password sind erforderlich.")

    def _get_json(self, path: str = "/player_api.php", params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}{path}"
        full_params = {
            "username": self.username,
            "password": self.password,
        }
        if params:
            full_params.update(params)

        resp = requests.get(url, params=full_params, timeout=self.timeout)
        resp.raise_for_status()
        try:
            return resp.json()
        except Exception as exc:
            raise ValueError(f"Ungültige JSON-Antwort von {url}: {exc}") from exc

    def _build_stream_url(self, stream_type: str, stream_id: Any, extension: str) -> str:
        stream_id = str(stream_id).strip()
        extension = (extension or "").strip().lstrip(".")
        if stream_type == "movie":
            return f"{self.base_url}/movie/{self.username}/{self.password}/{stream_id}.{extension or 'mp4'}"
        if stream_type == "series":
            return f"{self.base_url}/series/{self.username}/{self.password}/{stream_id}.{extension or 'mp4'}"
        return f"{self.base_url}/live/{self.username}/{self.password}/{stream_id}.{extension or 'ts'}"

    def _build_series_episode_url(self, episode_id: Any, extension: str) -> str:
        episode_id = str(episode_id).strip()
        extension = (extension or "").strip().lstrip(".")
        return f"{self.base_url}/series/{self.username}/{self.password}/{episode_id}.{extension or 'mp4'}"

    def get_account_info(self) -> Dict[str, Any]:
        data = self._get_json(params={})
        user_info = data.get("user_info") if isinstance(data, dict) else {}
        server_info = data.get("server_info") if isinstance(data, dict) else {}

        if not isinstance(user_info, dict):
            user_info = {}
        if not isinstance(server_info, dict):
            server_info = {}

        auth = user_info.get("auth")
        status = user_info.get("status")
        exp_date = _safe_dt_from_unix(user_info.get("exp_date"))
        created_at = _safe_dt_from_unix(user_info.get("created_at"))
        max_connections = _safe_int(user_info.get("max_connections"))
        active_cons = _safe_int(user_info.get("active_cons"))
        is_trial = str(user_info.get("is_trial", "0")) == "1"

        return {
            "auth": auth,
            "status": status,
            "exp_date": exp_date,
            "created_at": created_at,
            "max_connections": max_connections,
            "active_connections": active_cons,
            "is_trial": is_trial,
            "allowed_output_formats": user_info.get("allowed_output_formats") or [],
            "server_url": server_info.get("url"),
            "server_port": server_info.get("port"),
            "server_https_port": server_info.get("https_port"),
            "server_timezone": server_info.get("timezone"),
            "server_time_now": server_info.get("time_now"),
        }

    def get_live_categories(self) -> List[Dict[str, Any]]:
        data = self._get_json(params={"action": "get_live_categories"})
        if not isinstance(data, list):
            return []
        result = []
        for row in data:
            if not isinstance(row, dict):
                continue
            result.append({
                "id": str(row.get("category_id", "")).strip(),
                "name": row.get("category_name") or "Unbekannt",
                "raw": row,
            })
        return result

    def get_vod_categories(self) -> List[Dict[str, Any]]:
        data = self._get_json(params={"action": "get_vod_categories"})
        if not isinstance(data, list):
            return []
        result = []
        for row in data:
            if not isinstance(row, dict):
                continue
            result.append({
                "id": str(row.get("category_id", "")).strip(),
                "name": row.get("category_name") or "Unbekannt",
                "raw": row,
            })
        return result

    def get_series_categories(self) -> List[Dict[str, Any]]:
        data = self._get_json(params={"action": "get_series_categories"})
        if not isinstance(data, list):
            return []
        result = []
        for row in data:
            if not isinstance(row, dict):
                continue
            result.append({
                "id": str(row.get("category_id", "")).strip(),
                "name": row.get("category_name") or "Unbekannt",
                "raw": row,
            })
        return result

    def get_live_streams(self, category_id: Optional[str] = None) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"action": "get_live_streams"}
        if category_id:
            params["category_id"] = category_id
        data = self._get_json(params=params)
        if not isinstance(data, list):
            return []
        result: List[Dict[str, Any]] = []
        for row in data:
            if not isinstance(row, dict):
                continue
            stream_id = row.get("stream_id")
            if stream_id in (None, ""):
                continue
            result.append({
                "id": str(stream_id),
                "name": row.get("name") or row.get("stream_display_name") or f"LiveTV {stream_id}",
                "category_id": str(row.get("category_id", "")).strip(),
                "stream_icon": row.get("stream_icon"),
                "epg_channel_id": row.get("epg_channel_id"),
                "tv_archive": row.get("tv_archive"),
                "raw": row,
                "url": self._build_stream_url("live", stream_id, "ts"),
            })
        return result

    def get_vod_streams(self, category_id: Optional[str] = None) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"action": "get_vod_streams"}
        if category_id:
            params["category_id"] = category_id
        data = self._get_json(params=params)
        if not isinstance(data, list):
            return []
        result: List[Dict[str, Any]] = []
        for row in data:
            if not isinstance(row, dict):
                continue
            stream_id = row.get("stream_id")
            if stream_id in (None, ""):
                continue
            container_extension = row.get("container_extension") or "mp4"
            result.append({
                "id": str(stream_id),
                "name": row.get("name") or f"Movie {stream_id}",
                "year": str(row.get("year") or "").strip(),
                "category_id": str(row.get("category_id", "")).strip(),
                "stream_icon": row.get("stream_icon"),
                "tmdb": row.get("tmdb"),
                "container_extension": container_extension,
                "raw": row,
                "url": self._build_stream_url("movie", stream_id, container_extension),
            })
        return result

    def get_series(self, category_id: Optional[str] = None) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"action": "get_series"}
        if category_id:
            params["category_id"] = category_id
        data = self._get_json(params=params)

        if not isinstance(data, list):
            return []

        result: List[Dict[str, Any]] = []
        for row in data:
            if not isinstance(row, dict):
                continue
            series_id = row.get("series_id")
            if series_id in (None, ""):
                continue
            result.append({
                "id": str(series_id),
                "name": row.get("name") or f"Series {series_id}",
                "year": str(row.get("year") or "").strip(),
                "category_id": str(row.get("category_id", "")).strip(),
                "cover": row.get("cover"),
                "plot": row.get("plot"),
                "tmdb": row.get("tmdb"),
                "raw": row,
            })
        return result

    def get_series_info(self, series_id: str) -> Dict[str, Any]:
        data = self._get_json(params={"action": "get_series_info", "series_id": series_id})
        if not isinstance(data, dict):
            return {}

        info = data.get("info")
        episodes = data.get("episodes")

        if not isinstance(info, dict):
            info = {}
        if not isinstance(episodes, dict):
            episodes = {}

        normalized_episodes: Dict[str, List[Dict[str, Any]]] = {}

        for season_key, season_items in episodes.items():
            if not isinstance(season_items, list):
                continue

            season_list: List[Dict[str, Any]] = []
            for ep in season_items:
                if not isinstance(ep, dict):
                    continue

                episode_id = ep.get("id")
                if episode_id in (None, ""):
                    continue

                info_block = ep.get("info")
                if not isinstance(info_block, dict):
                    info_block = {}

                ext = info_block.get("container_extension") or ep.get("container_extension") or "mp4"
                episode_num = _safe_int(ep.get("episode_num"))
                title = info_block.get("title") or ep.get("title") or f"Episode {episode_num or '?'}"

                season_list.append({
                    "id": str(episode_id),
                    "episode_num": episode_num,
                    "season": _safe_int(ep.get("season")) or _safe_int(season_key),
                    "title": title,
                    "container_extension": ext,
                    "plot": info_block.get("plot"),
                    "releasedate": info_block.get("releasedate"),
                    "raw": ep,
                    "url": self._build_series_episode_url(episode_id, ext),
                })

            if season_list:
                normalized_episodes[str(season_key)] = season_list

        return {
            "info": info,
            "episodes": normalized_episodes,
            "raw": data,
        }

    def load_catalog(self) -> Dict[str, Any]:
        live_categories = self.get_live_categories()
        vod_categories = self.get_vod_categories()
        series_categories = self.get_series_categories()

        return {
            "livetv_categories": live_categories,
            "movie_categories": vod_categories,
            "series_categories": series_categories,
        }
