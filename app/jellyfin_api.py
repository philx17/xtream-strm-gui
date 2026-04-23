from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlencode
import requests

DEFAULT_TIMEOUT = 20
USER_AGENT = "xtream-strm-gui/1.0"


class JellyfinClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = DEFAULT_TIMEOUT):
        self.base_url = self._normalize_base_url(base_url)
        self.api_key = (api_key or "").strip()
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "X-Emby-Token": self.api_key,
            "Accept": "application/json",
        })

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        base_url = (base_url or "").strip().rstrip("/")
        parsed = urlparse(base_url)
        if not parsed.scheme:
            base_url = "http://" + base_url
        return base_url.rstrip("/")

    def _get(self, path: str, **params: Any) -> Any:
        url = f"{self.base_url}{path}"
        response = self.session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        try:
            return response.json()
        except Exception as exc:
            raise RuntimeError(f"Ungültige JSON-Antwort von {response.url}") from exc

    def get_system_info(self) -> Dict[str, Any]:
        return self._get("/System/Info/Public") or {}

    def test_connection(self) -> Dict[str, Any]:
        info = self.get_system_info()
        if not isinstance(info, dict):
            raise RuntimeError("Jellyfin Antwort ist ungültig.")
        return info

    def get_users(self) -> List[Dict[str, Any]]:
        data = self._get("/Users")
        return data if isinstance(data, list) else []

    def resolve_user_id(self, preferred_name: Optional[str] = None) -> str:
        users = self.get_users()
        if not users:
            raise RuntimeError("Keine Jellyfin Benutzer gefunden.")

        if preferred_name:
            wanted = preferred_name.strip().lower()
            for user in users:
                name = str(user.get("Name") or "").strip().lower()
                if name == wanted:
                    user_id = str(user.get("Id") or "").strip()
                    if user_id:
                        return user_id

        for user in users:
            user_id = str(user.get("Id") or "").strip()
            if user_id:
                return user_id

        raise RuntimeError("Keine gültige Jellyfin Benutzer-ID gefunden.")

    def get_libraries(self) -> List[Dict[str, Any]]:
        data = self._get("/Library/VirtualFolders")
        if not isinstance(data, list):
            return []

        result: List[Dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                continue

            name = item.get("Name") or "Unbekannt"
            locations = item.get("Locations") or []
            collection_type = item.get("CollectionType") or ""
            item_id = item.get("ItemId") or name

            result.append({
                "id": str(item_id),
                "name": str(name),
                "collection_type": str(collection_type or ""),
                "locations": locations if isinstance(locations, list) else [],
                "raw": item,
            })

        return result

    def get_items(
        self,
        user_id: str,
        parent_id: str,
        include_item_types: str,
        recursive: bool = True,
    ) -> List[Dict[str, Any]]:
        start_index = 0
        limit = 200
        results: List[Dict[str, Any]] = []

        while True:
            data = self._get(
                f"/Users/{user_id}/Items",
                ParentId=parent_id,
                Recursive=str(bool(recursive)).lower(),
                IncludeItemTypes=include_item_types,
                Fields="Overview,PrimaryImageAspectRatio,ProviderIds,ProductionYear,PremiereDate,RunTimeTicks,Path,ChannelMappingInfo",
                SortBy="SortName",
                SortOrder="Ascending",
                StartIndex=start_index,
                Limit=limit,
            )

            if not isinstance(data, dict):
                break

            items = data.get("Items") or []
            if not isinstance(items, list):
                items = []

            results.extend(x for x in items if isinstance(x, dict))

            if len(items) < limit:
                break

            start_index += limit

        return results

    def get_series_episodes(self, user_id: str, series_id: str) -> List[Dict[str, Any]]:
        return self.get_items(
            user_id=user_id,
            parent_id=series_id,
            include_item_types="Episode",
            recursive=True,
        )

    def get_live_channels(self) -> List[Dict[str, Any]]:
        data = self._get(
            "/LiveTv/Channels",
            EnableUserData="false",
            EnableImages="true",
            Fields="ChannelMappingInfo",
        )

        items = data.get("Items", []) if isinstance(data, dict) else []
        result: List[Dict[str, Any]] = []

        for item in items:
            if not isinstance(item, dict):
                continue

            channel_id = str(item.get("Id") or "").strip()
            if not channel_id:
                continue

            channel_number = item.get("ChannelNumber")
            if channel_number in (None, ""):
                channel_number = 0

            tag_items = item.get("TagItems")
            group_name = None
            if isinstance(tag_items, list) and tag_items:
                first_tag = tag_items[0]
                if isinstance(first_tag, dict):
                    group_name = first_tag.get("Name")

            group_name = group_name or item.get("GroupName") or "LiveTV"

            result.append({
                "Id": channel_id,
                "Name": item.get("Name") or "Unknown Channel",
                "Number": channel_number,
                "group_name": str(group_name).strip() or "LiveTV",
                "epg_channel_id": str(item.get("ExternalId") or ""),
                "raw": item,
            })

        return result

    def build_image_url(self, item_id: str, base_url_override: Optional[str] = None) -> str:
        if not item_id:
            return ""
        base = (base_url_override or self.base_url).rstrip("/")
        return f"{base}/Items/{item_id}/Images/Primary?api_key={self.api_key}"

    def build_stream_url(
        self,
        item_id: str,
        container: str = "mp4",
        base_url_override: Optional[str] = None,
    ) -> str:
        item_id = str(item_id or "").strip()
        container = (container or "mp4").lstrip(".")
        if not item_id:
            return ""
        base = (base_url_override or self.base_url).rstrip("/")
        query = urlencode({
            "static": "true",
            "api_key": self.api_key,
        })
        return f"{base}/Videos/{item_id}/stream.{container}?{query}"

    def build_live_stream_url(
        self,
        channel_id: str,
        base_url_override: Optional[str] = None,
    ) -> str:
        channel_id = str(channel_id or "").strip()
        if not channel_id:
            return ""
        base = (base_url_override or self.base_url).rstrip("/")
        query = urlencode({
            "static": "true",
            "api_key": self.api_key,
        })
        return f"{base}/Videos/{channel_id}/stream?{query}"