from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

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


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def write_text(path: Path, content: str):
    ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8")


def maybe_int(value: Any) -> Optional[int]:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except Exception:
        return None


def sanitize_filename(value: str) -> str:
    value = (value or "").strip()
    bad = '<>:"/\\|?*'
    for ch in bad:
        value = value.replace(ch, "_")
    while "  " in value:
        value = value.replace("  ", " ")
    return value.strip().rstrip(".")


def escape_xml(value: Any) -> str:
    s = str(value or "")
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
         .replace("'", "&apos;")
    )


def build_movie_folder_name(movie: Dict[str, Any]) -> str:
    name = sanitize_filename(movie.get("name") or "Unknown Movie")
    year = str(movie.get("year") or "").strip()
    tmdb = str(movie.get("tmdb") or "").strip()

    suffix = []
    if year:
        suffix.append(f"({year})")
    if tmdb:
        suffix.append(f"[tmdbid-{tmdb}]")

    return f"{name} {' '.join(suffix)}".strip()


def build_movie_nfo(movie: Dict[str, Any]) -> str:
    title = movie.get("name") or ""
    year = movie.get("year") or ""
    tmdb = str(movie.get("tmdb") or "").strip()
    plot = ""
    raw = movie.get("raw")
    if isinstance(raw, dict):
        plot = raw.get("plot") or raw.get("description") or ""

    lines = [
        "<movie>",
        f"  <title>{escape_xml(title)}</title>",
        f"  <year>{escape_xml(year)}</year>",
    ]
    if tmdb:
        lines.append(f'  <uniqueid type="tmdb" default="true">{escape_xml(tmdb)}</uniqueid>')
    if plot:
        lines.append(f"  <plot>{escape_xml(plot)}</plot>")
    lines.append("</movie>")
    return "\n".join(lines) + "\n"


def build_series_folder_name(series_obj: Dict[str, Any], info: Dict[str, Any]) -> str:
    base_name = info.get("name") or series_obj.get("name") or "Unknown Series"
    year = str(info.get("releaseDate") or info.get("release_date") or series_obj.get("year") or "").strip()
    tvdb = str(info.get("tvdb_id") or info.get("tvdb") or "").strip()

    result = sanitize_filename(base_name)
    suffix = []
    if year:
        suffix.append(f"({year[:4]})")
    if tvdb:
        suffix.append(f"[tvdbid-{tvdb}]")
    if suffix:
        result = f"{result} {' '.join(suffix)}"
    return result


def build_episode_nfo(series_title: str, episode: Dict[str, Any], season_no: int, episode_no: int) -> str:
    title = episode.get("title") or f"Episode {episode_no}"
    plot = episode.get("plot") or ""
    lines = [
        "<episodedetails>",
        f"  <title>{escape_xml(title)}</title>",
        f"  <showtitle>{escape_xml(series_title)}</showtitle>",
        f"  <season>{season_no}</season>",
        f"  <episode>{episode_no}</episode>",
    ]
    if plot:
        lines.append(f"  <plot>{escape_xml(plot)}</plot>")
    lines.append("</episodedetails>")
    return "\n".join(lines) + "\n"


def register_manifest_item(manifest: Dict[str, Any], item_key: str, item_data: Dict[str, Any]):
    items = manifest.setdefault("items", {})
    items[item_key] = item_data


def diff_manifests(old_manifest: Dict[str, Any], new_manifest: Dict[str, Any]) -> Dict[str, Any]:
    old_items = old_manifest.get("items", {}) if isinstance(old_manifest, dict) else {}
    new_items = new_manifest.get("items", {}) if isinstance(new_manifest, dict) else {}

    old_keys = set(old_items.keys())
    new_keys = set(new_items.keys())

    added = [new_items[k] for k in sorted(new_keys - old_keys)]
    removed = [old_items[k] for k in sorted(old_keys - new_keys)]

    return {
        "added": added,
        "removed": removed,
        "added_count": len(added),
        "removed_count": len(removed),
    }


def cleanup_empty_dirs_from_manifest(manifest: Dict[str, Any]):
    items = manifest.get("items", {}) if isinstance(manifest, dict) else {}
    parent_dirs = set()

    for item in items.values():
        if not isinstance(item, dict):
            continue
        path_str = item.get("path")
        if not path_str:
            continue
        p = Path(path_str)
        parent_dirs.add(p.parent)

    for folder in sorted(parent_dirs, key=lambda x: len(x.parts), reverse=True):
        try:
            current = folder
            for _ in range(6):
                if current.exists() and current.is_dir():
                    if any(current.iterdir()):
                        break
                    current.rmdir()
                current = current.parent
        except Exception:
            continue


def remove_obsolete_files(old_manifest: Dict[str, Any], new_manifest: Dict[str, Any]) -> List[str]:
    removed_paths: List[str] = []

    old_items = old_manifest.get("items", {}) if isinstance(old_manifest, dict) else {}
    new_items = new_manifest.get("items", {}) if isinstance(new_manifest, dict) else {}
    obsolete_keys = set(old_items.keys()) - set(new_items.keys())

    for key in obsolete_keys:
        item = old_items.get(key, {})
        path_str = item.get("path")
        if not path_str:
            continue
        path = Path(path_str)
        try:
            if path.exists():
                path.unlink()
                removed_paths.append(str(path))
        except Exception:
            continue

    cleanup_empty_dirs_from_manifest(old_manifest)
    return removed_paths


def reset_generated_output(config: Dict[str, Any], delete_runtime_state: bool = False) -> Dict[str, Any]:
    old_manifest = load_manifest()
    items = old_manifest.get("items", {})
    deleted = []

    for item in items.values():
        if not isinstance(item, dict):
            continue
        path_str = item.get("path")
        if not path_str:
            continue
        path = Path(path_str)
        try:
            if path.exists():
                path.unlink()
                deleted.append(str(path))
        except Exception:
            pass

    cleanup_empty_dirs_from_manifest(old_manifest)
    clear_manifest()

    if delete_runtime_state:
        clear_last_report()

    return {
        "deleted_files": len(deleted),
        "deleted_paths": deleted[:200],
    }


def status(phase: str, progress: int, message: str):
    set_job_status(phase=phase, progress=progress, message=message)
    append_job_log(message)


def run_export_job(config: Dict[str, Any]):
    started = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    set_job_status(
        running=True,
        started_at=started,
        finished_at=None,
        logs=[],
        error=None,
        phase="starting",
        progress=0,
        message="Starte Export ...",
    )

    connection = config.get("connection", {}) if isinstance(config, dict) else {}
    output = config.get("output", {}) if isinstance(config, dict) else {}
    selection = config.get("selection", {}) if isinstance(config, dict) else {}
    sync = config.get("sync", {}) if isinstance(config, dict) else {}

    base_url = connection.get("base_url", "")
    username = connection.get("username", "")
    password = connection.get("password", "")
    root_dir = Path(output.get("root_dir") or "/output")
    movies_dir = root_dir / (output.get("movies_dir") or "Movies")
    series_dir = root_dir / (output.get("series_dir") or "Series")
    livetv_file = root_dir / (output.get("livetv_file") or "livetv.m3u")

    selected_live_categories = set(selection.get("livetv_categories") or [])
    selected_movie_categories = set(selection.get("movie_categories") or [])
    selected_series_categories = set(selection.get("series_categories") or [])

    delete_removed = bool(sync.get("delete_removed", True))

    client = XtreamClient(base_url, username, password)

    status("connect", 5, "Verbindung wird geprüft ...")
    account_info = client.get_account_info()

    new_manifest: Dict[str, Any] = {"items": {}}
    old_manifest = load_manifest()

    report = {
        "started_at": started,
        "finished_at": None,
        "account": account_info,
        "summary": {
            "selected_livetv_categories": len(selected_live_categories),
            "selected_movie_categories": len(selected_movie_categories),
            "selected_series_categories": len(selected_series_categories),
            "livetv_channels": 0,
            "movies": 0,
            "series": 0,
            "episodes": 0,
            "written_files": 0,
            "deleted_files": 0,
        },
        "changelog": {
            "added": [],
            "removed": [],
        },
    }

    ensure_dir(root_dir)

    status("livetv", 15, "Lade LiveTV-Streams ...")
    livetv_streams: List[Dict[str, Any]] = []
    for category_id in selected_live_categories:
        livetv_streams.extend(client.get_live_streams(category_id))

    status("livetv_write", 25, "Schreibe LiveTV M3U ...")
    livetv_lines = ["#EXTM3U"]
    chno = 1001

    for item in livetv_streams:
        name = item.get("name") or "Unknown Channel"
        group_title = ""
        raw = item.get("raw")
        if isinstance(raw, dict):
            group_title = raw.get("category_name") or raw.get("group-title") or ""

        logo = item.get("stream_icon") or ""
        epg = item.get("epg_channel_id") or ""

        livetv_lines.append(
            f'#EXTINF:-1 tvg-id="{epg}" tvg-name="{name}" tvg-logo="{logo}" '
            f'tvg-chno="{chno}" group-title="{group_title}",{name}'
        )
        livetv_lines.append(item.get("url") or "")
        chno += 1

    write_text(livetv_file, "\n".join(livetv_lines) + "\n")
    register_manifest_item(
        new_manifest,
        f"livetv:m3u:{livetv_file.as_posix()}",
        {
            "type": "livetv_playlist",
            "name": livetv_file.name,
            "path": str(livetv_file),
        },
    )
    report["summary"]["livetv_channels"] = len(livetv_streams)
    report["summary"]["written_files"] += 1

    status("movies", 35, "Lade Filme ...")
    movie_items: List[Dict[str, Any]] = []
    for category_id in selected_movie_categories:
        movie_items.extend(client.get_vod_streams(category_id))

    status("movies_write", 50, "Schreibe Movie STRM/NFO ...")
    for movie in movie_items:
        folder_name = build_movie_folder_name(movie)
        movie_folder = movies_dir / folder_name
        ensure_dir(movie_folder)

        file_base = folder_name
        strm_path = movie_folder / f"{file_base}.strm"
        nfo_path = movie_folder / f"{file_base}.nfo"

        write_text(strm_path, (movie.get("url") or "").strip() + "\n")
        write_text(nfo_path, build_movie_nfo(movie))

        register_manifest_item(
            new_manifest,
            f"movie:{movie.get('id')}:strm",
            {"type": "movie_strm", "name": movie.get("name"), "path": str(strm_path)},
        )
        register_manifest_item(
            new_manifest,
            f"movie:{movie.get('id')}:nfo",
            {"type": "movie_nfo", "name": movie.get("name"), "path": str(nfo_path)},
        )

        report["summary"]["movies"] += 1
        report["summary"]["written_files"] += 2

    status("series", 60, "Lade Serien ...")
    series_list: List[Dict[str, Any]] = []
    for category_id in selected_series_categories:
        series_list.extend(client.get_series(category_id))

    report["summary"]["series"] = len(series_list)

    status("series_write", 70, "Schreibe Serien STRM/NFO ...")
    for idx, series_obj in enumerate(series_list, start=1):
        series_id = str(series_obj.get("id") or "").strip()
        if not series_id:
            continue

        info_payload = client.get_series_info(series_id)
        if not isinstance(info_payload, dict):
            continue

        info = info_payload.get("info")
        if not isinstance(info, dict):
            info = {}

        episodes = info_payload.get("episodes")
        if not isinstance(episodes, dict):
            episodes = {}

        series_folder_name = build_series_folder_name(series_obj, info)
        series_root = series_dir / series_folder_name
        ensure_dir(series_root)
        series_title = info.get("name") or series_obj.get("name") or "Unknown Series"

        for season_key, season_eps in episodes.items():
            if not isinstance(season_eps, list):
                continue

            season_no = maybe_int(season_key) or 0
            season_folder = series_root / f"Season {season_no}"
            ensure_dir(season_folder)

            for ep in season_eps:
                if not isinstance(ep, dict):
                    continue

                episode_no = maybe_int(ep.get("episode_num")) or 0
                episode_title = sanitize_filename(ep.get("title") or f"Episode {episode_no}")
                base_name = sanitize_filename(f"{series_title} - S{season_no:02d}E{episode_no:02d} - {episode_title}")

                strm_path = season_folder / f"{base_name}.strm"
                nfo_path = season_folder / f"{base_name}.nfo"

                write_text(strm_path, (ep.get("url") or "").strip() + "\n")
                write_text(nfo_path, build_episode_nfo(series_title, ep, season_no, episode_no))

                register_manifest_item(
                    new_manifest,
                    f"series:{series_id}:season:{season_no}:episode:{episode_no}:strm",
                    {"type": "series_strm", "name": base_name, "path": str(strm_path)},
                )
                register_manifest_item(
                    new_manifest,
                    f"series:{series_id}:season:{season_no}:episode:{episode_no}:nfo",
                    {"type": "series_nfo", "name": base_name, "path": str(nfo_path)},
                )

                report["summary"]["episodes"] += 1
                report["summary"]["written_files"] += 2

        if idx % 5 == 0:
            status("series_write", min(90, 70 + idx), f"Serien verarbeitet: {idx}/{len(series_list)}")

    deleted_paths: List[str] = []
    if delete_removed:
        status("cleanup", 92, "Entferne veraltete Dateien ...")
        deleted_paths = remove_obsolete_files(old_manifest, new_manifest)
        report["summary"]["deleted_files"] = len(deleted_paths)

    save_manifest(new_manifest)

    diff = diff_manifests(old_manifest, new_manifest)
    report["changelog"]["added"] = diff["added"][:500]
    report["changelog"]["removed"] = diff["removed"][:500]

    report["finished_at"] = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    save_last_report(report)

    status("done", 100, "Export abgeschlossen.")
    set_job_status(
        running=False,
        finished_at=report["finished_at"],
        phase="done",
        progress=100,
        message="Export abgeschlossen.",
        error=None,
    )
