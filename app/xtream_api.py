from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

DEFAULT_TIMEOUT = 45
USER_AGENT = "xtream-strm-gui/1.0"


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


@dataclass
class XtreamClient:
    base_url: str
    username: str
    password: str
    timeout: int = DEFAULT_TIMEOUT

    def __post_init__(self):
        self.base_url = self._normalize_base_url(self.base_url)
        self.username = (self.username or "").strip()
        self.password = (self.password or "").strip()

        if not self.base_url or not self.username or not self.password:
            raise ValueError("base_url, username und password sind erforderlich.")

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        base_url = (base_url or "").strip().rstrip("/")

        if not base_url:
            return ""

        parsed = urlparse(base_url)
        if not parsed.scheme:
            base_url = "http://" + base_url

        return base_url.rstrip("/")

    def _player_api(self, action: Optional[str] = None, **params: Any) -> Any:
        query = {
            "username": self.username,
            "password": self.password,
        }
        if action:
            query["action"] = action
        query.update(params)

        url = f"{self.base_url}/player_api.php"
        response = self.session.get(url, params=query, timeout=self.timeout)
        response.raise_for_status()

        try:
            return response.json()
        except Exception as exc:
            raise RuntimeError(f"Ungültige JSON-Antwort von {response.url}") from exc

    def auth_check(self) -> Dict[str, Any]:
        data = self._player_api()
        if not isinstance(data, dict):
            raise RuntimeError("Ungültige Antwort vom Server.")

        user_info = data.get("user_info") or {}
        if not isinstance(user_info, dict):
            user_info = {}

        if str(user_info.get("auth")) != "1":
            raise RuntimeError("Login fehlgeschlagen: auth != 1")

        return data

    def get_account_info(self) -> Dict[str, Any]:
        data = self.auth_check()

        user_info = data.get("user_info") or {}
        server_info = data.get("server_info") or {}

        if not isinstance(user_info, dict):
            user_info = {}
        if not isinstance(server_info, dict):
            server_info = {}

        return {
            "auth": user_info.get("auth"),
            "status": user_info.get("status"),
            "exp_date": _safe_dt_from_unix(user_info.get("exp_date")),
            "created_at": _safe_dt_from_unix(user_info.get("created_at")),
            "max_connections": _safe_int(user_info.get("max_connections")),
            "active_connections": _safe_int(user_info.get("active_cons")),
            "is_trial": str(user_info.get("is_trial", "0")) == "1",
            "allowed_output_formats": user_info.get("allowed_output_formats") or [],
            "server_url": server_info.get("url"),
            "server_port": server_info.get("port"),
            "server_https_port": server_info.get("https_port"),
            "server_timezone": server_info.get("timezone"),
            "server_time_now": server_info.get("time_now"),
        }

    def get_live_categories(self) -> List[Dict[str, Any]]:
        data = self._player_api("get_live_categories") or []
        if not isinstance(data, list):
            return []

        result: List[Dict[str, Any]] = []
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
        data = self._player_api("get_vod_categories") or []
        if not isinstance(data, list):
            return []

        result: List[Dict[str, Any]] = []
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
        data = self._player_api("get_series_categories") or []
        if not isinstance(data, list):
            return []

        result: List[Dict[str, Any]] = []
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
        params: Dict[str, Any] = {}
        if category_id:
            params["category_id"] = category_id

        data = self._player_api("get_live_streams", **params) or []
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
                "url": self.make_live_url(stream_id, "ts"),
            })

        return result

    def get_vod_streams(self, category_id: Optional[str] = None) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {}
        if category_id:
            params["category_id"] = category_id

        data = self._player_api("get_vod_streams", **params) or []
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
                "url": self.make_vod_url(stream_id, container_extension),
            })

        return result

    def get_series(self, category_id: Optional[str] = None) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {}
        if category_id:
            params["category_id"] = category_id

        data = self._player_api("get_series", **params) or []
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

    def get_series_info(self, series_id: Any) -> Dict[str, Any]:
        data = self._player_api("get_series_info", series_id=series_id) or {}
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
                season_no = _safe_int(ep.get("season")) or _safe_int(season_key) or 0
                title = info_block.get("title") or ep.get("title") or f"Episode {episode_num or '?'}"

                season_list.append({
                    "id": str(episode_id),
                    "episode_num": episode_num,
                    "season": season_no,
                    "title": title,
                    "container_extension": ext,
                    "plot": info_block.get("plot"),
                    "releasedate": info_block.get("releasedate"),
                    "raw": ep,
                    "url": self.make_series_url(episode_id, ext),
                })

            if season_list:
                normalized_episodes[str(season_key)] = season_list

        return {
            "info": info,
            "episodes": normalized_episodes,
            "raw": data,
        }

    def load_catalog(self) -> Dict[str, Any]:
        return {
            "livetv_categories": self.get_live_categories(),
            "movie_categories": self.get_vod_categories(),
            "series_categories": self.get_series_categories(),
        }

    def make_live_url(self, stream_id: Any, extension: str = "ts") -> str:
        ext = (extension or "ts").lstrip(".")
        return f"{self.base_url}/live/{self.username}/{self.password}/{stream_id}.{ext}"

    def make_vod_url(self, stream_id: Any, extension: str = "mp4") -> str:
        ext = (extension or "mp4").lstrip(".")
        return f"{self.base_url}/movie/{self.username}/{self.password}/{stream_id}.{ext}"

    def make_series_url(self, episode_id: Any, extension: str = "mp4") -> str:
        ext = (extension or "mp4").lstrip(".")
        return f"{self.base_url}/series/{self.username}/{self.password}/{episode_id}.{ext}"