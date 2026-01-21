import json
import time
import hashlib
import re
from pathlib import Path

from .m3u_core import parse_m3u, classify_item, extract_show_season_episode, clean_lang_tags


def safe_name(s: str, max_len: int = 180) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    s = s.replace("\u200e", "").replace("\u200f", "")
    s = re.sub(r'[\/\\:*?"<>|]', "_", s)
    s = s.strip(" ._")
    if not s:
        s = "Unknown"
    if len(s) > max_len:
        s = s[:max_len].rstrip(" ._")
    return s


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def write_strm(path: Path, url: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    new_text = url.strip() + "\n"
    if path.exists():
        old = path.read_text(encoding="utf-8", errors="ignore")
        if old == new_text:
            return False
    path.write_text(new_text, encoding="utf-8")
    return True


def remove_if_empty_dirs(start_dir: Path, stop_at: Path):
    cur = start_dir
    while True:
        if cur == stop_at or len(cur.parts) < len(stop_at.parts):
            return
        try:
            cur.rmdir()
        except OSError:
            return
        cur = cur.parent


def allow_item(kind: str, group: str, tvg_name: str, show: str, allow_cfg: dict) -> bool:
    """
    Allowlist logic:
    - If a category is in full_categories => everything in that category is allowed (incl. new items)
    - Otherwise:
      - allow if category is in categories OR title is in titles
    - For series:
      - allow if show in shows OR episode-title in titles
    """
    allow = allow_cfg or {}

    if kind == "livetv":
        a = allow.get("livetv", {})
        if group in set(a.get("full_categories", [])):
            return True
        return (group in set(a.get("categories", []))) or (tvg_name in set(a.get("titles", [])))

    if kind == "movie":
        a = allow.get("movies", {})
        if group in set(a.get("full_categories", [])):
            return True
        return (group in set(a.get("categories", []))) or (tvg_name in set(a.get("titles", [])))

    if kind == "series":
        a = allow.get("series", {})
        return (show in set(a.get("shows", []))) or (tvg_name in set(a.get("titles", [])))

    return False


def run_sync(m3u_text: str, out_dir: Path, allow_cfg: dict, sync_delete: bool = True, prune_sidecars: bool = False):
    out_dir = out_dir.resolve()
    state_dir = out_dir / ".xtream_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = state_dir / "manifest.json"

    old_manifest = {}
    if manifest_path.exists():
        try:
            old_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            old_manifest = {}

    old_paths = set()
    if isinstance(old_manifest, dict):
        items = old_manifest.get("items", {})
        if isinstance(items, dict):
            for v in items.values():
                p = v.get("path")
                if p:
                    old_paths.add(p)

    desired_paths = set()
    new_manifest = {"generated_at": int(time.time()), "items": {}}

    created = 0
    updated = 0
    skipped = 0

    for it in parse_m3u(m3u_text):
        attrs = it["attrs"]
        url = it["url"]
        title = it["title"]
        group = attrs.get("group-title") or "Ungrouped"
        tvg_name = attrs.get("tvg-name") or title

        kind = classify_item(url, group, tvg_name, title)

        show = None
        season = None
        epn = None

        if kind == "series":
            show, season, epn, _ = extract_show_season_episode(tvg_name)
            if not show:
                show = clean_lang_tags(tvg_name)
                season, epn = 0, 0

            if not allow_item("series", group, tvg_name, show, allow_cfg):
                skipped += 1
                continue

            show_dir = safe_name(show)
            season_dir = f"Season {int(season):02d}"
            base = f"{show} - S{int(season):02d}E{int(epn):02d}"
            target = out_dir / "Series" / show_dir / season_dir / (safe_name(base) + ".strm")

        elif kind == "movie":
            if not allow_item("movie", group, tvg_name, None, allow_cfg):
                skipped += 1
                continue

            genre_dir = safe_name(group.replace("/", "_"))
            target = out_dir / "Movies" / genre_dir / (safe_name(clean_lang_tags(tvg_name)) + ".strm")

        else:
            if not allow_item("livetv", group, tvg_name, None, allow_cfg):
                skipped += 1
                continue

            cat_dir = safe_name(group)
            target = out_dir / "LiveTV" / cat_dir / (safe_name(tvg_name) + ".strm")

        desired_paths.add(str(target))
        key = sha256(url)

        changed = write_strm(target, url)
        if changed:
            if str(target) in old_paths:
                updated += 1
            else:
                created += 1

        new_manifest["items"][key] = {
            "kind": kind,
            "group": group,
            "tvg_name": tvg_name,
            "path": str(target),
            "url": url,
            "show": show,
            "season": season,
            "episode": epn,
        }

    deleted = 0
    sidecars_deleted = 0
    if sync_delete:
        removed = old_paths - desired_paths
        for p_str in sorted(removed):
            p = Path(p_str)
            if p.exists() and p.is_file() and p.suffix.lower() == ".strm":
                try:
                    p.unlink()
                    deleted += 1
                except Exception:
                    continue

                if prune_sidecars:
                    stem = p.with_suffix("")
                    for ext in [".nfo", ".jpg", ".jpeg", ".png", ".webp", ".srt", ".ass", ".sub"]:
                        side = Path(str(stem) + ext)
                        if side.exists() and side.is_file():
                            try:
                                side.unlink()
                                sidecars_deleted += 1
                            except Exception:
                                pass

                remove_if_empty_dirs(p.parent, out_dir)

    manifest_path.write_text(json.dumps(new_manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "created": created,
        "updated": updated,
        "skipped_not_allowed": skipped,
        "deleted": deleted,
        "sidecars_deleted": sidecars_deleted,
    }
