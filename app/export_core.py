from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import re

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

SERIES_INFO_WORKERS = 5
SERIES_INFO_RETRIES = 2
SERIES_INFO_RETRY_SLEEP = 1
SERIES_BATCH_SIZE = 250
SERIES_BATCH_PAUSE = 0.0
SERIES_ERROR_COOLDOWN_THRESHOLD = 30
SERIES_ERROR_COOLDOWN_SECONDS = 4

MAX_SERIES_FOLDER_LEN = 100
MAX_EPISODE_BASENAME_LEN = 140


class ExportCancelled(Exception):
    pass


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
    return truncate_name(result, MAX_SERIES_FOLDER_LEN)


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


def normalize_id_set(values: Any) -> Set[str]:
    if not isinstance(values, (list, set, tuple)):
        return set()
    return {str(x).strip() for x in values if str(x).strip()}


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

        check_cancel()
        status("movies_load", 30, "Lade Filme ...")
        movie_items = client.get_vod_streams_multi(sorted(selected_movie_categories))
        movie_items = apply_item_excludes(movie_items, exclude_movie_ids)

        check_cancel()
        status("movies_write", 45, f"Schreibe Filme ({len(movie_items)}) ...")
        for idx, movie in enumerate(movie_items, start=1):
            check_cancel()
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

            if idx % 1000 == 0:
                set_job_status(phase="movies_write", progress=45, message=f"Filme verarbeitet: {idx}/{len(movie_items)}")

        check_cancel()
        status("series_load", 55, "Lade Serienliste ...")
        series_list = client.get_series_multi(sorted(selected_series_categories))
        series_list = apply_item_excludes(series_list, exclude_series_ids)
        report["summary"]["series"] = len(series_list)

        check_cancel()
        status("series_prepare", 62, f"Bereite Serieninfos vor ({len(series_list)} Serien) ...")

        def fetch_series_info(series_obj: Dict[str, Any]):
            series_id = str(series_obj.get("id") or "").strip()
            if not series_id:
                return None

            last_exc = None
            for attempt in range(1, SERIES_INFO_RETRIES + 1):
                try:
                    local_client = XtreamClient(base_url, username, password)
                    payload = local_client.get_series_info(series_id)
                    return series_obj, payload
                except Exception as exc:
                    last_exc = exc
                    if attempt < SERIES_INFO_RETRIES:
                        time.sleep(SERIES_INFO_RETRY_SLEEP * attempt)
            raise last_exc

        total_series = len(series_list)
        completed_series = 0
        failed_series = 0

        if total_series > 0:
            workers = max(1, min(SERIES_INFO_WORKERS, total_series))
            append_job_log(f"Serieninfos parallel mit {workers} Workern.")
            append_job_log(f"Retry-Logik aktiv: {SERIES_INFO_RETRIES} Versuche je Serie.")
            append_job_log(f"Batching aktiv: {SERIES_BATCH_SIZE} Serien pro Batch.")
            append_job_log("Pfadlängen-Schutz aktiv für Serienordner und Episodendateien.")

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

                        series_obj, info_payload = result
                        if not isinstance(info_payload, dict):
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

                        episodes = info_payload.get("episodes")
                        if not isinstance(episodes, dict):
                            episodes = {}

                        series_id = str(series_obj.get("id") or "").strip()
                        series_folder_name = build_series_folder_name(series_obj, info)
                        series_root = series_dir / series_folder_name
                        ensure_dir(series_root)
                        series_title = truncate_name(info.get("name") or series_obj.get("name") or "Unknown Series", 80)

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