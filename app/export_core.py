from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import re
import threading
import json
import os
import hashlib
from .xtream_api import XtreamClient
from .state_core import (
    append_job_log,
    set_job_status,
    save_last_report,
    load_manifest,
    save_manifest,
    clear_manifest,
    clear_last_report,
    is_cancel_requested,
    clear_cancel_request,
    save_changelog_file,
)

SERIES_CACHE_TTL_SECONDS = 24 * 60 * 60  # auch mit last_modified 1x taeglich pruefen
MAX_SERIES_FOLDER_LEN = 100
SERIES_INFO_WORKERS = 2
SERIES_INFO_RETRIES = 1
SERIES_INFO_RETRY_SLEEP = 2.0
SERIES_BATCH_SIZE = 200
SERIES_BATCH_PAUSE = 10.0
SERIES_ERROR_COOLDOWN_THRESHOLD = 2
SERIES_ERROR_COOLDOWN_SECONDS = 30
SERIES_REQUEST_PAUSE = 0.10  # Pro Worker wie im Benchmark
SERIES_CACHE_TTL_SECONDS = 24 * 60 * 60  # auch mit last_modified 1x taeglich pruefen
MAX_SERIES_FOLDER_LEN = 100
MAX_EPISODE_BASENAME_LEN = 140

class ExportCancelled(Exception):
    pass
def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)
def write_text(path: Path, content: str):
    ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8")
def write_text_if_changed(path: Path, content: str) -> bool:
    ensure_dir(path.parent)
    try:
        if path.exists():
            old = path.read_text(encoding="utf-8")
            if old == content:
                return False
    except Exception:
        pass
    path.write_text(content, encoding="utf-8")
    return True
def maybe_int(value: Any) -> Optional[int]:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except Exception:
        return None
def sanitize_filename(value: str) -> str:
    value = (value or "").strip()
    bad = '<>:"/\\\\|?*'
    for ch in bad:
        value = value.replace(ch, "_")
    while "  " in value:
        value = value.replace("  ", " ")
    return value.strip().rstrip(".")
def truncate_name(value: str, max_len: int) -> str:
    value = sanitize_filename(value)
    if len(value) <= max_len:
        return value
    return value[:max_len].rstrip(" ._-")
def escape_xml(value: Any) -> str:
    s = str(value or "")
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
         .replace("'", "&apos;")
    )
def check_cancel():
    if is_cancel_requested():
        raise ExportCancelled("Export wurde vom Benutzer abgebrochen.")
def remove_series_title_prefix(series_title: str, episode_title: str) -> str:
    st = (series_title or "").strip()
    ep = (episode_title or "").strip()
    if not st or not ep:
        return ep
    ep_norm = ep.lower()
    st_norm = st.lower()
    if ep_norm.startswith(st_norm):
        ep = ep[len(st):].lstrip(" -:_")
        return ep or episode_title
    pattern = re.escape(st) + r"\s*[-:_]\s*"
    ep = re.sub(pattern, "", ep, count=1, flags=re.IGNORECASE).strip()
    return ep or episode_title
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
def build_series_folder_name(series_obj: Dict[str, Any], info: Dict[str, Any], force_xtream_id: bool = False) -> str:
    base_name = info.get("name") or series_obj.get("name") or "Unknown Series"
    year = str(
        info.get("releaseDate")
        or info.get("release_date")
        or series_obj.get("year")
        or ""
    ).strip()
    tvdb = str(info.get("tvdb_id") or info.get("tvdb") or "").strip()
    tmdb = str(info.get("tmdb_id") or info.get("tmdb") or "").strip()
    xtream_id = str(series_obj.get("id") or "").strip()
    result = sanitize_filename(base_name)
    suffix = []
    if year:
        suffix.append(f"({year[:4]})")
    if tvdb:
        suffix.append(f"[tvdbid-{tvdb}]")
    elif tmdb:
        suffix.append(f"[tmdbid-{tmdb}]")
    if force_xtream_id and xtream_id:
        suffix.append(f"[xtreamid-{xtream_id}]")
    if suffix:
        result = f"{result} {' '.join(suffix)}"
    return truncate_name(result, MAX_SERIES_FOLDER_LEN)
def build_tvshow_nfo(series_obj: Dict[str, Any], info: Dict[str, Any]) -> str:
    title = info.get("name") or series_obj.get("name") or "Unknown Series"
    year = str(
        info.get("releaseDate")
        or info.get("release_date")
        or series_obj.get("year")
        or ""
    ).strip()[:4]
    tvdb = str(info.get("tvdb_id") or info.get("tvdb") or "").strip()
    tmdb = str(info.get("tmdb_id") or info.get("tmdb") or "").strip()
    plot = str(info.get("plot") or info.get("description") or "").strip()
    lines = [
        "<tvshow>",
        f"  <title>{escape_xml(title)}</title>",
    ]
    if year:
        lines.append(f"  <year>{escape_xml(year)}</year>")
    if tvdb:
        lines.append(f'  <uniqueid type="tvdb" default="true">{escape_xml(tvdb)}</uniqueid>')
    if tmdb:
        default = "false" if tvdb else "true"
        lines.append(f'  <uniqueid type="tmdb" default="{default}">{escape_xml(tmdb)}</uniqueid>')
    if plot:
        lines.append(f"  <plot>{escape_xml(plot)}</plot>")
    lines.append("</tvshow>")
    return "\n".join(lines) + "\n"
def build_episode_basename(series_title: str, episode: Dict[str, Any], season_no: int, episode_no: int) -> str:
    raw_title = episode.get("title") or f"Episode {episode_no}"
    clean_episode_title = remove_series_title_prefix(series_title, raw_title)
    clean_episode_title = sanitize_filename(clean_episode_title)
    if not clean_episode_title:
        clean_episode_title = f"Episode {episode_no}"
    base_name = f"{series_title} - S{season_no:02d}E{episode_no:02d} - {clean_episode_title}"
    return truncate_name(base_name, MAX_EPISODE_BASENAME_LEN)
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
def build_series_episode_manifest_base_key(series_id: str, episode: Dict[str, Any], season_no: int, episode_no: int) -> str:
    episode_id = str(episode.get("id") or "").strip()
    if episode_id:
        return f"series:{series_id}:episode_id:{episode_id}"
    return f"series:{series_id}:season:{season_no}:episode:{episode_no}"
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
# WICHTIG:
# Wenn ein alter Manifest-Key auf eine Datei zeigt, die im neuen Manifest
# weiterhin existiert, darf sie NICHT gelöscht werden.
    new_paths = set()
    for item in new_items.values():
        if isinstance(item, dict) and item.get("path"):
            new_paths.add(str(item.get("path")))
    for key in obsolete_keys:
        item = old_items.get(key, {})
        path_str = item.get("path")
        if not path_str:
            continue
        if str(path_str) in new_paths:
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
def normalize_id_set(values: Any) -> Set[str]:
    if not isinstance(values, (list, set, tuple)):
        return set()
    return {str(x).strip() for x in values if str(x).strip()}
def selected_categories_only(items: List[Dict[str, Any]], allowed: Set[str]) -> List[Dict[str, Any]]:
    """Zusaetzliche Absicherung der GUI-Auswahl nach dem XtreamClient-Filter.

    Fehlt eine Kategorie im normalisierten Element, vertrauen wir dem
    bereits kategoriebasiert abgefragten XtreamClient, statt legitime
    Treffer unbemerkt zu verwerfen.
    """
    if not allowed:
        return items
    kept = []
    for item in items:
        if not isinstance(item, dict):
            continue
        raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
        category_values = []
        for obj in (item, raw):
            for key in ("category_id", "category_ids"):
                value = obj.get(key)
                if isinstance(value, (list, tuple, set)):
                    category_values.extend(str(v).strip() for v in value if v is not None)
                elif value not in (None, ""):
                    category_values.append(str(value).strip())
        if not category_values or any(v in allowed for v in category_values):
            kept.append(item)
    return kept


def series_last_modified(item: Dict[str, Any]) -> str:
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    value = raw.get("last_modified") or item.get("last_modified")
    return str(value).strip() if value not in (None, "") else ""


def read_series_cache(path: Path, modified: str) -> Optional[Dict[str, Any]]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("version") != 1:
            return None
        saved_marker = str(record.get("last_modified") or "")
        if time.time() - float(record.get("saved_at", 0)) > SERIES_CACHE_TTL_SECONDS:
            return None
        if modified and saved_marker != modified:
            return None
        payload = record.get("payload")
        if isinstance(payload, dict) and isinstance(payload.get("episodes"), dict):
            return payload
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return None


def save_series_cache(path: Path, modified: str, payload: Dict[str, Any]) -> None:
    ensure_dir(path.parent)
    content = json.dumps({
        "version": 1,
        "saved_at": time.time(),
        "last_modified": modified,
        "payload": payload,
    }, ensure_ascii=False, separators=(",", ":"))
    # URLs enthalten gegebenenfalls Zugangsdaten: Cachedateien nur fuer Besitzer.
    tmp = path.with_suffix(".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, path)


def apply_item_excludes(items: List[Dict[str, Any]], exclude_ids: Set[str]) -> List[Dict[str, Any]]:
    if not items:
        return []
    by_id: Dict[str, Dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            continue
        by_id[item_id] = item
    result: List[Dict[str, Any]] = []
    for item_id, item in by_id.items():
        if item_id in exclude_ids:
            continue
        result.append(item)
    return result
def _chunks(seq: List[Dict[str, Any]], size: int) -> List[List[Dict[str, Any]]]:
    return [seq[i:i + size] for i in range(0, len(seq), size)]
def movie_debug_log(message: str):
    print(f"[MOVIE DEBUG] {message}", flush=True)
def series_debug_log(message: str):
    print(f"[SERIES DEBUG] {message}", flush=True)
def movie_quality_score(name: str, url: str) -> int:
    text = f"{name or ''} {url or ''}".upper()
    score = 0
    if "8K" in text or "4320" in text:
        score += 8000
    elif "4K" in text or "UHD" in text or "2160" in text:
        score += 4000
    elif "FHD" in text or "1080" in text:
        score += 3000
    elif "HD" in text or "720" in text:
        score += 2000
    elif "SD" in text:
        score += 1000
# kleine Anbieter-Priorität, falls Qualität gleich ist
    if "AMZ" in text or "AMAZON" in text:
        score += 40
    elif "D+" in text or "DISNEY" in text:
        score += 30
    elif "NF" in text or "NETFLIX" in text:
        score += 20
    return score
def run_export_job(config: Dict[str, Any]):
    clear_cancel_request()
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
    try:
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
        selected_live_categories = normalize_id_set(selection.get("livetv_categories"))
        selected_movie_categories = normalize_id_set(selection.get("movie_categories"))
        selected_series_categories = normalize_id_set(selection.get("series_categories"))
        exclude_live_ids = normalize_id_set(selection.get("livetv_exclude_ids"))
        exclude_movie_ids = normalize_id_set(selection.get("movie_exclude_ids"))
        exclude_series_ids = normalize_id_set(selection.get("series_exclude_ids"))
        delete_removed = bool(sync.get("delete_removed", True))
        client = XtreamClient(base_url, username, password)
        check_cancel()
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
                "skipped_unchanged_files": 0,
                "deleted_files": 0,
                "excluded_livetv": len(exclude_live_ids),
                "excluded_movies": len(exclude_movie_ids),
                "excluded_series": len(exclude_series_ids),
                "series_info_workers": SERIES_INFO_WORKERS,
                "series_info_retries": SERIES_INFO_RETRIES,
                "series_batch_size": SERIES_BATCH_SIZE,
            },
            "changelog": {
                "added": [],
                "removed": [],
            },
        }
        ensure_dir(root_dir)
        check_cancel()
        status("livetv_load", 12, "Lade LiveTV-Streams ...")
        livetv_streams = client.get_live_streams_multi(sorted(selected_live_categories))
        livetv_streams = selected_categories_only(livetv_streams, selected_live_categories)
        livetv_streams = apply_item_excludes(livetv_streams, exclude_live_ids)
        check_cancel()
        status("livetv_write", 22, f"Schreibe LiveTV M3U ({len(livetv_streams)} Sender) ...")
        livetv_lines = ["#EXTM3U"]
        chno = 1001
        for item in livetv_streams:
            check_cancel()
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
        livetv_written = write_text_if_changed(livetv_file, "\n".join(livetv_lines) + "\n")
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
        if livetv_written:
            report["summary"]["written_files"] += 1
        else:
            report["summary"]["skipped_unchanged_files"] += 1
        check_cancel()
        append_job_log("Pause nach LiveTV: 5 Sekunden ...")
        time.sleep(5)
        check_cancel()
        status("movies_load", 30, "Lade Filme ...")
        movie_items = client.get_vod_streams_multi(sorted(selected_movie_categories))
        movie_items = selected_categories_only(movie_items, selected_movie_categories)
        movie_items = apply_item_excludes(movie_items, exclude_movie_ids)
        check_cancel()
        status("movies_write", 45, f"Schreibe Filme ({len(movie_items)}) ...")
        movie_debug = {
            "api_movies": len(movie_items),
            "unique_folder_paths": 0,
            "unique_strm_paths": 0,
            "actual_folders_after_write": 0,
            "folder_collisions": 0,
            "strm_collisions": 0,
            "same_link_duplicates": 0,
            "different_link_versions": 0,
            "quality_replacements": 0,
            "skipped_lower_quality": 0,
            "same_quality_kept_first": 0,
            "write_errors": 0,
        }
        movie_folder_seen: Dict[str, Dict[str, Any]] = {}
        movie_choice: Dict[str, Dict[str, Any]] = {}
        movie_folder_collisions: List[Dict[str, Any]] = []
        movie_same_link_examples: List[Dict[str, Any]] = []
        movie_different_link_examples: List[Dict[str, Any]] = []
        movie_quality_replace_examples: List[Dict[str, Any]] = []
        movie_lower_quality_examples: List[Dict[str, Any]] = []
        movie_write_errors: List[Dict[str, Any]] = []
        movie_debug_log(f"API-Filme nach Excludes: {len(movie_items)}")
        movie_debug_log(f"Movies-Zielordner: {movies_dir}")
        movie_debug_log("Dedupe aktiv: gleicher STRM-Link = skip, anderer STRM-Link = Qualitätsvergleich")
        for idx, movie in enumerate(movie_items, start=1):
            check_cancel()
            movie_id = str(movie.get("id") or "").strip()
            movie_name = str(movie.get("name") or "Unknown Movie").strip()
            movie_year = str(movie.get("year") or "").strip()
            movie_tmdb = str(movie.get("tmdb") or "").strip()
            folder_name = build_movie_folder_name(movie)
            movie_folder = movies_dir / folder_name
            file_base = folder_name
            strm_path = movie_folder / f"{file_base}.strm"
            nfo_path = movie_folder / f"{file_base}.nfo"
            folder_key = str(movie_folder)
            strm_key = str(strm_path)
            movie_url = (movie.get("url") or "").strip()
            movie_url_content = movie_url + "\n"
            movie_nfo_content = build_movie_nfo(movie)
            score = movie_quality_score(movie_name, movie_url)
            current_info = {
                "idx": idx,
                "id": movie_id,
                "name": movie_name,
                "year": movie_year,
                "tmdb": movie_tmdb,
                "folder": folder_key,
                "strm": strm_key,
                "url": movie_url,
                "score": score,
            }
            if folder_key in movie_folder_seen:
                movie_debug["folder_collisions"] += 1
                collision = {
                    "path": folder_key,
                    "first": movie_folder_seen[folder_key],
                    "second": current_info,
                }
                movie_folder_collisions.append(collision)
                movie_debug_log(
                    f"ORDNER-DUBLETTE #{movie_debug['folder_collisions']}: "
                    f"{folder_key} | "
                    f"first=[{collision['first'].get('idx')}] "
                    f"id={collision['first'].get('id')} score={collision['first'].get('score')} "
                    f"name={collision['first'].get('name')} | "
                    f"second=[{idx}] id={movie_id} score={score} name={movie_name}"
                )
            else:
                movie_folder_seen[folder_key] = current_info
            try:
                ensure_dir(movie_folder)
                if strm_key not in movie_choice:
                    movie_choice[strm_key] = {
                        **current_info,
                        "nfo": str(nfo_path),
                    }
                    movie_strm_written = write_text_if_changed(strm_path, movie_url_content)
                    movie_nfo_written = write_text_if_changed(nfo_path, movie_nfo_content)
                    movie_debug_log(
                        f"NEUER FILM: [{idx}] id={movie_id} score={score} "
                        f"name={movie_name} -> {strm_key}"
                    )
                    if movie_strm_written:
                        report["summary"]["written_files"] += 1
                    else:
                        report["summary"]["skipped_unchanged_files"] += 1
                    if movie_nfo_written:
                        report["summary"]["written_files"] += 1
                    else:
                        report["summary"]["skipped_unchanged_files"] += 1
                else:
                    old = movie_choice[strm_key]
                    movie_debug["strm_collisions"] += 1
                    if old.get("url") == movie_url:
                        movie_debug["same_link_duplicates"] += 1
                        example = {
                            "path": strm_key,
                            "first": old,
                            "second": current_info,
                        }
                        movie_same_link_examples.append(example)
                        movie_debug_log(
                            f"GLEICHER STRM-LINK SKIP #{movie_debug['same_link_duplicates']}: "
                            f"{strm_key} | "
                            f"kept=[{old.get('idx')}] id={old.get('id')} score={old.get('score')} "
                            f"name={old.get('name')} | "
                            f"skip=[{idx}] id={movie_id} score={score} name={movie_name}"
                        )
                    else:
                        movie_debug["different_link_versions"] += 1
                        example = {
                            "path": strm_key,
                            "first": old,
                            "second": current_info,
                        }
                        movie_different_link_examples.append(example)
                        if score > int(old.get("score") or 0):
                            movie_debug["quality_replacements"] += 1
                            movie_debug_log(
                                f"BESSERE VERSION ERSETZT #{movie_debug['quality_replacements']}: "
                                f"{strm_key}\n"
                                f"  ALT: [{old.get('idx')}] id={old.get('id')} "
                                f"score={old.get('score')} name={old.get('name')}\n"
                                f"  NEU: [{idx}] id={movie_id} score={score} name={movie_name}"
                            )
                            movie_quality_replace_examples.append(example)
                            movie_choice[strm_key] = {
                                **current_info,
                                "nfo": str(nfo_path),
                            }
                            movie_strm_written = write_text_if_changed(strm_path, movie_url_content)
                            movie_nfo_written = write_text_if_changed(nfo_path, movie_nfo_content)
                            if movie_strm_written:
                                report["summary"]["written_files"] += 1
                            else:
                                report["summary"]["skipped_unchanged_files"] += 1
                            if movie_nfo_written:
                                report["summary"]["written_files"] += 1
                            else:
                                report["summary"]["skipped_unchanged_files"] += 1
                        elif score < int(old.get("score") or 0):
                            movie_debug["skipped_lower_quality"] += 1
                            movie_debug_log(
                                f"SCHLECHTERE VERSION SKIP #{movie_debug['skipped_lower_quality']}: "
                                f"{strm_key}\n"
                                f"  BEHALTEN: [{old.get('idx')}] id={old.get('id')} "
                                f"score={old.get('score')} name={old.get('name')}\n"
                                f"  SKIP:     [{idx}] id={movie_id} score={score} name={movie_name}"
                            )
                            movie_lower_quality_examples.append(example)
                        else:
                            movie_debug["same_quality_kept_first"] += 1
                            movie_debug_log(
                                f"GLEICHE QUALITÄT - ERSTE VERSION BLEIBT #{movie_debug['same_quality_kept_first']}: "
                                f"{strm_key}\n"
                                f"  BEHALTEN: [{old.get('idx')}] id={old.get('id')} "
                                f"score={old.get('score')} name={old.get('name')}\n"
                                f"  SKIP:     [{idx}] id={movie_id} score={score} name={movie_name}"
                            )
# WICHTIG:
# Manifest nach Zielpfad, nicht nach Stream-ID.
# Dadurch löschen alte Dubletten-Keys später keine noch gültigen Dateien.
                register_manifest_item(
                    new_manifest,
                    f"movie:path:{strm_key}:strm",
                    {
                        "type": "movie_strm",
                        "name": movie_choice[strm_key].get("name"),
                        "path": str(strm_path),
                    },
                )
                register_manifest_item(
                    new_manifest,
                    f"movie:path:{str(nfo_path)}:nfo",
                    {
                        "type": "movie_nfo",
                        "name": movie_choice[strm_key].get("name"),
                        "path": str(nfo_path),
                    },
                )
# report["summary"]["movies"] += 1
            except Exception as exc:
                movie_debug["write_errors"] += 1
                error_info = {
                    "idx": idx,
                    "id": movie_id,
                    "name": movie_name,
                    "folder": folder_key,
                    "strm": strm_key,
                    "error": str(exc),
                }
                movie_write_errors.append(error_info)
                movie_debug_log(
                    f"SCHREIBFEHLER #{movie_debug['write_errors']}: "
                    f"[{idx}] id={movie_id} name={movie_name} path={strm_key} error={exc}"
                )
                continue
            if idx % 1000 == 0:
                set_job_status(
                    phase="movies_write",
                    progress=45,
                    message=f"Filme verarbeitet: {idx}/{len(movie_items)}"
                )
        report["summary"]["movies"] = len(movie_choice)
        movie_debug["unique_folder_paths"] = len(movie_folder_seen)
        movie_debug["unique_strm_paths"] = len(movie_choice)
        try:
            movie_debug["actual_folders_after_write"] = sum(
                1 for p in movies_dir.iterdir() if p.is_dir()
            ) if movies_dir.exists() else 0
        except Exception as exc:
            movie_debug_log(f"Konnte echte Ordneranzahl nicht zählen: {exc}")
            movie_debug["actual_folders_after_write"] = -1
        movie_debug_log("========== MOVIE DEBUG SUMMARY ==========")
        movie_debug_log(f"API-Filme verarbeitet: {movie_debug['api_movies']}")
        movie_debug_log(f"Report-Filme gezählt: {report['summary']['movies']}")
        movie_debug_log(f"Eindeutige Zielordner laut Berechnung: {movie_debug['unique_folder_paths']}")
        movie_debug_log(f"Eindeutige STRM-Pfade laut Berechnung: {movie_debug['unique_strm_paths']}")
        movie_debug_log(f"Echte Ordner im Movies-Zielordner: {movie_debug['actual_folders_after_write']}")
        movie_debug_log(f"Ordner-Dubletten/Kollisionen: {movie_debug['folder_collisions']}")
        movie_debug_log(f"STRM-Kollisionen gesamt: {movie_debug['strm_collisions']}")
        movie_debug_log(f"Identische Dubletten gleicher STRM-Link: {movie_debug['same_link_duplicates']}")
        movie_debug_log(f"Alternative Versionen mit anderem STRM-Link: {movie_debug['different_link_versions']}")
        movie_debug_log(f"Bessere Versionen ersetzt: {movie_debug['quality_replacements']}")
        movie_debug_log(f"Schlechtere Versionen ignoriert: {movie_debug['skipped_lower_quality']}")
        movie_debug_log(f"Gleiche Qualität - erste Version behalten: {movie_debug['same_quality_kept_first']}")
        movie_debug_log(f"Schreibfehler: {movie_debug['write_errors']}")
        if movie_same_link_examples:
            movie_debug_log("Beispiele identische Dubletten gleicher STRM-Link:")
            for c in movie_same_link_examples[:50]:
                movie_debug_log(
                    f"  PFAD: {c['path']} | "
                    f"KEEP id={c['first'].get('id')} score={c['first'].get('score')} name={c['first'].get('name')} | "
                    f"SKIP id={c['second'].get('id')} score={c['second'].get('score')} name={c['second'].get('name')}"
                )
        if movie_different_link_examples:
            movie_debug_log("Beispiele alternative Versionen mit anderem STRM-Link:")
            for c in movie_different_link_examples[:50]:
                movie_debug_log(
                    f"  PFAD: {c['path']} | "
                    f"FIRST id={c['first'].get('id')} score={c['first'].get('score')} name={c['first'].get('name')} | "
                    f"SECOND id={c['second'].get('id')} score={c['second'].get('score')} name={c['second'].get('name')}"
                )
        if movie_quality_replace_examples:
            movie_debug_log("Beispiele bessere Version ersetzt:")
            for c in movie_quality_replace_examples[:50]:
                movie_debug_log(
                    f"  PFAD: {c['path']} | "
                    f"ALT id={c['first'].get('id')} score={c['first'].get('score')} name={c['first'].get('name')} | "
                    f"NEU id={c['second'].get('id')} score={c['second'].get('score')} name={c['second'].get('name')}"
                )
        if movie_lower_quality_examples:
            movie_debug_log("Beispiele schlechtere Version ignoriert:")
            for c in movie_lower_quality_examples[:50]:
                movie_debug_log(
                    f"  PFAD: {c['path']} | "
                    f"KEEP id={c['first'].get('id')} score={c['first'].get('score')} name={c['first'].get('name')} | "
                    f"SKIP id={c['second'].get('id')} score={c['second'].get('score')} name={c['second'].get('name')}"
                )
        if movie_write_errors:
            movie_debug_log("Beispiele Schreibfehler:")
            for e in movie_write_errors[:50]:
                movie_debug_log(
                    f"  id={e.get('id')} name={e.get('name')} path={e.get('strm')} error={e.get('error')}"
                )
        movie_debug_log("=========================================")
        report["movie_debug"] = {
            **movie_debug,
            "folder_collision_examples": movie_folder_collisions[:100],
            "same_link_duplicate_examples": movie_same_link_examples[:100],
            "different_link_version_examples": movie_different_link_examples[:100],
            "quality_replace_examples": movie_quality_replace_examples[:100],
            "lower_quality_examples": movie_lower_quality_examples[:100],
            "write_error_examples": movie_write_errors[:100],
        }
        check_cancel()

        append_job_log("Pause nach Filmverarbeitung: 5 Sekunden ...")
        time.sleep(5)

        check_cancel()
        status("series_load", 55, "Lade Serienliste ...")
        series_list = client.get_series_multi(sorted(selected_series_categories))
        series_list = selected_categories_only(series_list, selected_series_categories)
        series_list = apply_item_excludes(series_list, exclude_series_ids)
        report["summary"]["series"] = len(series_list)
        series_debug = {
            "api_series_after_excludes": len(series_list),
            "missing_series_id": 0,
            "info_ok": 0,
            "info_failed": 0,
            "info_invalid": 0,
            "episodes_invalid": 0,
            "episodes_empty": 0,
            "series_with_episodes": 0,
            "series_without_written_episodes": 0,
            "series_folders_created_or_used": 0,
            "unique_series_folder_paths": 0,
            "series_folder_collisions": 0,
            "episode_items_total": 0,
            "episode_write_errors": 0,
            "tvshow_nfo_written": 0,
            "tvshow_nfo_skipped": 0,
        }
        series_folder_seen: Dict[str, Dict[str, Any]] = {}
        series_folder_collisions: List[Dict[str, Any]] = []
        series_no_episode_examples: List[Dict[str, Any]] = []
        series_info_failed_examples: List[Dict[str, Any]] = []
        series_episode_write_errors: List[Dict[str, Any]] = []
        series_debug_log(f"API-Serien nach Excludes: {len(series_list)}")
        series_debug_log(f"Series-Zielordner: {series_dir}")
        check_cancel()
        status("series_prepare", 62, f"Bereite Serieninfos vor ({len(series_list)} Serien) ...")
        # Der Cache gehoert zum Exportziel und bleibt bei Neustarts erhalten.
        # Provider/Zugangsdaten im Hash verhindern Cache-Vermischung.
        cache_identity = hashlib.sha256(
            f"{base_url.rstrip('/')}\0{username}\0{password}".encode("utf-8")
        ).hexdigest()[:20]
        series_cache_dir = root_dir / ".xtream_cache" / cache_identity / "series_info"
        ensure_dir(series_cache_dir)
        cached_series_count = 0
        fetched_series_count = 0
        worker_local = threading.local()
        def get_worker_client() -> XtreamClient:
            client = getattr(worker_local, "client", None)
            if client is None:
                client = XtreamClient(base_url, username, password)
                worker_local.client = client
            return client
        def fetch_series_info(series_obj: Dict[str, Any]):
            series_id = str(series_obj.get("id") or "").strip()
            if not series_id:
                raise ValueError("Serienobjekt ohne ID")
            # IDs des Clients stammen aus der API, aber Dateinamen trotzdem absichern.
            safe_id = re.sub(r"[^0-9A-Za-z_-]", "_", series_id)
            cache_file = series_cache_dir / f"{safe_id}.json"
            modified = series_last_modified(series_obj)
            cached_payload = read_series_cache(cache_file, modified)
            if cached_payload is not None:
                return series_obj, cached_payload, True

            last_exc = None
            for attempt in range(1, SERIES_INFO_RETRIES + 1):
                try:
                    local_client = get_worker_client()
                    payload = local_client.get_series_info(series_id)
                    # Eine leere/kaputte Antwort darf nie als valider Cache gelten.
                    if not isinstance(payload, dict) or not isinstance(payload.get("episodes"), dict):
                        raise ValueError("Ungueltige Serieninfo: episodes fehlt oder ist kein Objekt")
                    try:
                        save_series_cache(cache_file, modified, payload)
                    except Exception as cache_exc:
                        series_debug_log(f"Cache-Schreibfehler fuer Serie {series_id}: {type(cache_exc).__name__}")
                    return series_obj, payload, False
                except Exception as exc:
                    last_exc = exc
                    if hasattr(worker_local, "client"):
                        delattr(worker_local, "client")
                    if attempt < SERIES_INFO_RETRIES:
                        time.sleep(SERIES_INFO_RETRY_SLEEP * attempt)
                finally:
                    # Entspricht dem erfolgreichen Test: 100 ms je Worker.
                    time.sleep(SERIES_REQUEST_PAUSE)
            raise last_exc
        total_series = len(series_list)
        completed_series = 0
        failed_series = 0
        if total_series > 0:
            workers = max(1, min(SERIES_INFO_WORKERS, total_series))
            append_job_log(f"Serieninfos parallel mit {workers} Workern.")
            append_job_log("Worker-Client-Reuse aktiv: pro Worker ein langlebiger XtreamClient.")
            append_job_log(f"Episodencache aktiv: {series_cache_dir}")
            append_job_log(f"Anfragenpause pro Worker: {SERIES_REQUEST_PAUSE:.2f}s")
            append_job_log(f"Retry-Logik aktiv: {SERIES_INFO_RETRIES} Versuche je Serie.")
            append_job_log(f"Batching aktiv: {SERIES_BATCH_SIZE} Serien pro Batch.")
            append_job_log("Pfadlängen-Schutz aktiv für Serienordner und Episodendateien.")
            append_job_log("Inkrementelles Schreiben aktiv: unveränderte STRM/NFO-Dateien werden übersprungen.")
            append_job_log("Serien-Manifest-Key bevorzugt episode.id, Fallback auf season/episode.")
            series_batches = _chunks(series_list, SERIES_BATCH_SIZE)
            for batch_index, batch in enumerate(series_batches, start=1):
                check_cancel()
                batch_failed = 0
                status(
                    "series_batch",
                    min(90, 62 + int((completed_series / max(1, total_series)) * 25)),
                    f"Verarbeite Batch {batch_index}/{len(series_batches)} ({len(batch)} Serien) ..."
                )
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    future_map = {
                        executor.submit(fetch_series_info, series_obj): series_obj
                        for series_obj in batch
                    }
                    for future in as_completed(future_map):
                        check_cancel()
                        series_obj = future_map[future]
                        completed_series += 1
                        try:
                            result = future.result()
                        except Exception as exc:
                            failed_series += 1
                            batch_failed += 1
                            series_debug["info_failed"] += 1
                            series_info_failed_examples.append({
                                "id": str(series_obj.get("id") or ""),
                                "name": str(series_obj.get("name") or ""),
                                "error": str(exc),
                            })
                            if failed_series <= 25 or failed_series % 100 == 0:
                                append_job_log(
                                    f"Serieninfo fehlgeschlagen für {series_obj.get('name') or series_obj.get('id')}: {exc}"
                                )
                            progress = min(90, 65 + int((completed_series / total_series) * 25))
                            if completed_series <= 20 or completed_series % 100 == 0:
                                status("series_write", progress, f"Serien verarbeitet: {completed_series}/{total_series}")
                            else:
                                set_job_status(
                                phase="series_write",
                                progress=progress,
                                message=f"Serien verarbeitet: {completed_series}/{total_series}"
                                )
                            continue
                        if not result:
                            series_debug["info_invalid"] += 1
                            series_no_episode_examples.append({
                                "id": str(series_obj.get("id") or ""),
                                "name": str(series_obj.get("name") or ""),
                                "reason": "no_result",
                            })
                            progress = min(90, 65 + int((completed_series / total_series) * 25))
                            if completed_series <= 20 or completed_series % 100 == 0:
                                status("series_write", progress, f"Serien verarbeitet: {completed_series}/{total_series}")
                            else:
                                set_job_status(
                                phase="series_write",
                                progress=progress,
                                message=f"Serien verarbeitet: {completed_series}/{total_series}"
                                )
                            continue
                        series_obj, info_payload, from_cache = result
                        if from_cache:
                            cached_series_count += 1
                        else:
                            fetched_series_count += 1
                        if not isinstance(info_payload, dict):
                            series_debug["info_invalid"] += 1
                            series_no_episode_examples.append({
                                "id": str(series_obj.get("id") or ""),
                                "name": str(series_obj.get("name") or ""),
                                "reason": "info_payload_not_dict",
                            })
                            progress = min(90, 65 + int((completed_series / total_series) * 25))
                            if completed_series <= 20 or completed_series % 100 == 0:
                                status("series_write", progress, f"Serien verarbeitet: {completed_series}/{total_series}")
                            else:
                                set_job_status(
                                phase="series_write",
                                progress=progress,
                                message=f"Serien verarbeitet: {completed_series}/{total_series}"
                                )
                            continue
                        info = info_payload.get("info")
                        if not isinstance(info, dict):
                            info = {}
                        series_debug["info_ok"] += 1
                        episodes = info_payload.get("episodes")
                        if not isinstance(episodes, dict):
                            series_debug["episodes_invalid"] += 1
                            series_no_episode_examples.append({
                                "id": str(series_obj.get("id") or ""),
                                "name": str(series_obj.get("name") or ""),
                                "reason": f"episodes_not_dict:{type(episodes).__name__}",
                            })
                            episodes = {}
                        episode_count_for_series = 0
                        for _season_key, _season_eps in episodes.items():
                            if isinstance(_season_eps, list):
                                episode_count_for_series += len([x for x in _season_eps if isinstance(x, dict)])
                        series_debug["episode_items_total"] += episode_count_for_series
                        if episode_count_for_series <= 0:
                            series_debug["episodes_empty"] += 1
                            series_no_episode_examples.append({
                                "id": str(series_obj.get("id") or ""),
                                "name": str(series_obj.get("name") or ""),
                                "folder_name": build_series_folder_name(series_obj, info),
                                "reason": "episodes_empty",
                            })
                        else:
                            series_debug["series_with_episodes"] += 1
                        series_id = str(series_obj.get("id") or "").strip()
                        series_name = str(info.get("name") or series_obj.get("name") or "Unknown Series")
                        series_folder_name = build_series_folder_name(series_obj, info, force_xtream_id=False)
                        series_root = series_dir / series_folder_name
                        series_folder_key = str(series_root)
# Wenn derselbe Zielordner schon von einer anderen Serie verwendet wird,
# wird diese Serie eindeutig mit [xtreamid-...] geschrieben.
                        if series_folder_key in series_folder_seen:
                            series_folder_name = build_series_folder_name(series_obj, info, force_xtream_id=True)
                            series_root = series_dir / series_folder_name
                            series_folder_key = str(series_root)
                        if series_folder_key in series_folder_seen:
                            series_debug["series_folder_collisions"] += 1
                            collision = {
                                "path": series_folder_key,
                                "first": series_folder_seen[series_folder_key],
                                "second": {
                                    "id": series_id,
                                    "name": series_name,
                                },
                            }
                            series_folder_collisions.append(collision)
                            series_debug_log(
                                f"ORDNER-DUBLETTE #{series_debug['series_folder_collisions']}: "
                                f"{series_folder_key} | "
                                f"first id={collision['first'].get('id')} name={collision['first'].get('name')} | "
                                f"second id={series_id} name={series_name}"
                            )
                        else:
                            series_folder_seen[series_folder_key] = {
                                "id": series_id,
                                "name": series_name,
                            }
                        ensure_dir(series_root)
                        series_debug["series_folders_created_or_used"] += 1
                        series_title = truncate_name(series_name, 80)
                        written_episodes_for_series = 0
                        tvshow_nfo_path = series_root / "tvshow.nfo"
                        tvshow_nfo_written = write_text_if_changed(
                            tvshow_nfo_path,
                            build_tvshow_nfo(series_obj, info)
                        )
                        register_manifest_item(
                            new_manifest,
                            f"series:{series_id}:tvshow_nfo",
                            {
                                "type": "series_tvshow_nfo",
                                "name": series_name,
                                "path": str(tvshow_nfo_path),
                            },
                        )
                        if tvshow_nfo_written:
                            series_debug["tvshow_nfo_written"] += 1
                            report["summary"]["written_files"] += 1
                        else:
                            series_debug["tvshow_nfo_skipped"] += 1
                            report["summary"]["skipped_unchanged_files"] += 1
                        for season_key, season_eps in episodes.items():
                            check_cancel()
                            if not isinstance(season_eps, list):
                                continue
                            season_no = maybe_int(season_key) or 0
                            season_folder = series_root / f"Season {season_no}"
                            ensure_dir(season_folder)
                            for ep in season_eps:
                                check_cancel()
                                if not isinstance(ep, dict):
                                    continue
                                episode_no = maybe_int(ep.get("episode_num")) or 0
                                base_name = build_episode_basename(series_title, ep, season_no, episode_no)
                                strm_path = season_folder / f"{base_name}.strm"
                                nfo_path = season_folder / f"{base_name}.nfo"
                                ep_url_content = (ep.get("url") or "").strip() + "\n"
                                ep_nfo_content = build_episode_nfo(series_title, ep, season_no, episode_no)
                                try:
                                    ep_strm_written = write_text_if_changed(strm_path, ep_url_content)
                                    ep_nfo_written = write_text_if_changed(nfo_path, ep_nfo_content)
                                    written_episodes_for_series += 1
                                except Exception as exc:
                                    series_debug["episode_write_errors"] += 1
                                    series_episode_write_errors.append({
                                        "series_id": series_id,
                                        "series_name": series_name,
                                        "episode": base_name,
                                        "strm": str(strm_path),
                                        "error": str(exc),
                                    })
                                    series_debug_log(
                                        f"EPISODEN-SCHREIBFEHLER #{series_debug['episode_write_errors']}: "
                                        f"series_id={series_id} series={series_name} episode={base_name} error={exc}"
                                    )
                                    continue
                                base_manifest_key = build_series_episode_manifest_base_key(
                                    series_id=series_id,
                                    episode=ep,
                                    season_no=season_no,
                                    episode_no=episode_no,
                                )
                                register_manifest_item(
                                    new_manifest,
                                    f"{base_manifest_key}:strm",
                                    {"type": "series_strm", "name": base_name, "path": str(strm_path)},
                                )
                                register_manifest_item(
                                    new_manifest,
                                    f"{base_manifest_key}:nfo",
                                    {"type": "series_nfo", "name": base_name, "path": str(nfo_path)},
                                )
                                report["summary"]["episodes"] += 1
                                if ep_strm_written:
                                    report["summary"]["written_files"] += 1
                                else:
                                    report["summary"]["skipped_unchanged_files"] += 1
                                if ep_nfo_written:
                                    report["summary"]["written_files"] += 1
                                else:
                                    report["summary"]["skipped_unchanged_files"] += 1
                        if written_episodes_for_series <= 0:
                            series_debug["series_without_written_episodes"] += 1
                        progress = min(90, 65 + int((completed_series / total_series) * 25))
                        if completed_series <= 20 or completed_series % 100 == 0:
                            status("series_write", progress, f"Serien verarbeitet: {completed_series}/{total_series}")
                        else:
                            set_job_status(
                                phase="series_write",
                                progress=progress,
                                message=f"Serien verarbeitet: {completed_series}/{total_series}"
                            )
                if batch_failed >= SERIES_ERROR_COOLDOWN_THRESHOLD:
                    append_job_log(
                        f"Viele Fehler im Batch {batch_index}: {batch_failed}. Cooldown {SERIES_ERROR_COOLDOWN_SECONDS}s."
                    )
                    time.sleep(SERIES_ERROR_COOLDOWN_SECONDS)
                if batch_index < len(series_batches):
                    append_job_log(
                        f"Batch {batch_index}/{len(series_batches)} abgeschlossen. Pause {SERIES_BATCH_PAUSE}s."
                    )
                    time.sleep(SERIES_BATCH_PAUSE)
        else:
            status("series_write", 90, "Keine Serien zu verarbeiten.")
        check_cancel()
        deleted_paths: List[str] = []
        series_debug["unique_series_folder_paths"] = len(series_folder_seen)
        try:
            actual_series_folders = sum(
                1 for p in series_dir.iterdir() if p.is_dir()
            ) if series_dir.exists() else 0
        except Exception as exc:
            series_debug_log(f"Konnte echte Serienordneranzahl nicht zählen: {exc}")
            actual_series_folders = -1
        series_debug["actual_series_folders_after_write"] = actual_series_folders
        series_debug_log(f"Serieninfos aus Cache: {cached_series_count}; via API: {fetched_series_count}")
        series_debug_log("========== SERIES DEBUG SUMMARY ==========")
        series_debug_log(f"API-Serien nach Excludes: {series_debug['api_series_after_excludes']}")
        series_debug_log(f"Report-Serien aktuell: {report['summary']['series']}")
        series_debug_log(f"Serien ohne ID: {series_debug['missing_series_id']}")
        series_debug_log(f"Serieninfo OK: {series_debug['info_ok']}")
        series_debug_log(f"Serieninfo fehlgeschlagen: {series_debug['info_failed']}")
        series_debug_log(f"Serieninfo ungültig/leer: {series_debug['info_invalid']}")
        series_debug_log(f"Episodes ungültig: {series_debug['episodes_invalid']}")
        series_debug_log(f"Serien ohne Episoden: {series_debug['episodes_empty']}")
        series_debug_log(f"Serien mit Episoden: {series_debug['series_with_episodes']}")
        series_debug_log(f"Serien ohne geschriebene Episoden: {series_debug['series_without_written_episodes']}")
        series_debug_log(f"Episodenobjekte total laut API: {series_debug['episode_items_total']}")
        series_debug_log(f"Eindeutige Serien-Zielordner laut Berechnung: {series_debug['unique_series_folder_paths']}")
        series_debug_log(f"Echte Serienordner im Zielordner: {series_debug['actual_series_folders_after_write']}")
        series_debug_log(f"Serienordner-Dubletten/Kollisionen: {series_debug['series_folder_collisions']}")
        series_debug_log(f"Episoden-Schreibfehler: {series_debug['episode_write_errors']}")
        series_debug_log(f"tvshow.nfo neu/aktualisiert: {series_debug['tvshow_nfo_written']}")
        series_debug_log(f"tvshow.nfo unverändert/übersprungen: {series_debug['tvshow_nfo_skipped']}")
        if series_no_episode_examples:
            series_debug_log("Beispiele Serien ohne/ungültige Episoden:")
            for x in series_no_episode_examples[:50]:
                series_debug_log(
                    f"  id={x.get('id')} name={x.get('name')} reason={x.get('reason')} folder={x.get('folder_name', '-')}"
                )
        if series_info_failed_examples:
            series_debug_log("Beispiele Serieninfo-Fehler:")
            for x in series_info_failed_examples[:50]:
                series_debug_log(
                    f"  id={x.get('id')} name={x.get('name')} error={x.get('error')}"
                )
        if series_folder_collisions:
            series_debug_log("Beispiele Serienordner-Dubletten:")
            for c in series_folder_collisions[:50]:
                series_debug_log(
                    f"  PFAD: {c['path']} | "
                    f"FIRST id={c['first'].get('id')} name={c['first'].get('name')} | "
                    f"SECOND id={c['second'].get('id')} name={c['second'].get('name')}"
                )
        if series_episode_write_errors:
            series_debug_log("Beispiele Episoden-Schreibfehler:")
            for e in series_episode_write_errors[:50]:
                series_debug_log(
                    f"  series_id={e.get('series_id')} series={e.get('series_name')} "
                    f"episode={e.get('episode')} path={e.get('strm')} error={e.get('error')}"
                )
        series_debug_log("==========================================")
        report["series_debug"] = {
            **series_debug,
            "info_cache_hits": cached_series_count,
            "info_api_fetched": fetched_series_count,
            "no_episode_examples": series_no_episode_examples[:100],
            "info_failed_examples": series_info_failed_examples[:100],
            "folder_collision_examples": series_folder_collisions[:100],
            "episode_write_error_examples": series_episode_write_errors[:100],
        }
        # WICHTIG: Niemals vorhandene Dateien aufgrund fehlender API-Daten
        # oder Schreibfehler beim aktuellen Durchlauf entfernen.
        incomplete_export = bool(
            failed_series
            or series_debug["info_invalid"]
            or series_debug["episodes_invalid"]
            or series_debug["missing_series_id"]
            or series_debug["episode_write_errors"]
            or movie_debug["write_errors"]
            or series_debug["episodes_empty"]
        )
        if incomplete_export:
            append_job_log(
                "WARNUNG: Unvollstaendiger Export erkannt. "
                "Alte Manifest-Eintraege bleiben erhalten; keine Bereinigung."
            )
            for old_key, old_item in old_manifest.get("items", {}).items():
                new_manifest["items"].setdefault(old_key, old_item)
        if delete_removed and not incomplete_export:
            status("cleanup", 92, "Entferne veraltete Dateien ...")
            deleted_paths = remove_obsolete_files(old_manifest, new_manifest)
            report["summary"]["deleted_files"] = len(deleted_paths)
        save_manifest(new_manifest)
        diff = diff_manifests(old_manifest, new_manifest)
        report["changelog"]["added"] = diff["added"][:500]
        report["changelog"]["removed"] = diff["removed"][:500]
        report["finished_at"] = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        save_last_report(report)
        save_changelog_file(report)
        status("done", 100, "Export abgeschlossen.")
        set_job_status(
            running=False,
            finished_at=report["finished_at"],
            phase="done",
            progress=100,
            message="Export abgeschlossen.",
            error=None,
            cancel_requested=False,
        )
    except ExportCancelled:
        finished = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        append_job_log("Export wurde abgebrochen.")
        set_job_status(
            running=False,
            finished_at=finished,
            phase="cancelled",
            progress=100,
            message="Export abgebrochen.",
            error=None,
            cancel_requested=False,
        )
        raise
