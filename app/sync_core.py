import json
import time
import hashlib
import re
import shutil
from pathlib import Path
from difflib import SequenceMatcher

from .m3u_core import parse_m3u, classify_item, extract_show_season_episode, clean_lang_tags


# -------------------------
# Helpers: filenames
# -------------------------
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


def write_binary_if_changed(dst: Path, src: Path) -> bool:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        try:
            if dst.stat().st_size == src.stat().st_size:
                if dst.read_bytes() == src.read_bytes():
                    return False
        except Exception:
            pass
    shutil.copyfile(src, dst)
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


# -------------------------
# Allowlist
# -------------------------
def allow_item(kind: str, group: str, tvg_name: str, show: str, allow_cfg: dict) -> bool:
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


# -------------------------
# LiveTV Folder name (your proven terminal logic)
# -------------------------
def channel_folder_from_name(name: str) -> str:
    def strip_country_prefix(s: str) -> str:
        prefixes = ['DE', 'AT', 'CH', 'GER', 'EU', 'UK', 'US', 'FR', 'IT', 'ES', 'NL', 'PL']
        out = s
        for _ in range(2):
            t = out.lstrip()
            sp = t.find(' ')
            if sp == -1:
                return out
            token = t[:sp].strip()
            token_up = token.upper().rstrip(':|_-')
            if token_up in prefixes:
                out = t[sp + 1 :]
                continue
            return out
        return out

    s = (name or '').strip()

    if ':' in s:
        s = s.split(':', 1)[1]
    elif '|' in s:
        s = s.split('|', 1)[1]
    elif '_' in s:
        s = s.split('_', 1)[1]
    elif '-' in s:
        s = s.split('-', 1)[1]

    s = s.lstrip()
    s = ' '.join(s.split())

    s = strip_country_prefix(s)
    s = s.lstrip()
    s = ' '.join(s.split())

    return s


# -------------------------
# Movie Dedupe Key (ONLY movies)
# -------------------------
def movie_dedupe_key(tvg_name: str) -> str:
    s = clean_lang_tags(tvg_name or "").strip().lower()
    # remove typical quality/codec tokens
    s = re.sub(r"\b(sd|hd|fhd|uhd|hevc|h\.?265|h\.?264|4k|8k)\b", " ", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# -------------------------
# Picon Matching
# -------------------------
IGNORE_TOKENS = {
    "sd", "hd", "fhd", "uhd", "hevc", "hvec",
    "4k", "8k",
    "tv", "channel", "sender",
    "backup",
    "de", "at", "ch", "ger", "eu",
}

def _split_alnum_boundaries(s: str) -> str:
    s = re.sub(r"([a-zA-Z])([0-9])", r"\1 \2", s)
    s = re.sub(r"([0-9])([a-zA-Z])", r"\1 \2", s)
    return s

def _normalize_text_for_tokens(s: str) -> str:
    s = (s or "").strip()
    for sep in [":", "|", "_", "-"]:
        if sep in s:
            s = s.split(sep, 1)[1]
            break
    s = s.strip()
    s = s.replace("&", " and ")
    s = re.sub(r"\(\s*\d+\s*\)", " ", s)
    s = _split_alnum_boundaries(s)
    s = re.sub(r"\b4\s+k\b", "4k", s, flags=re.IGNORECASE)
    s = re.sub(r"\b8\s+k\b", "8k", s, flags=re.IGNORECASE)
    s = re.sub(r"[^a-zA-Z0-9äöüÄÖÜß ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s

def _tokens_from(s: str):
    s = _normalize_text_for_tokens(s)
    return [t for t in s.split(" ") if t and t not in IGNORE_TOKENS]

def _score_tokens(name_toks, file_toks) -> float:
    ns = " ".join(name_toks)
    fs = " ".join(file_toks)
    if not ns or not fs:
        return 0.0
    overlap = len(set(name_toks) & set(file_toks))
    sim = SequenceMatcher(None, ns, fs).ratio()
    return overlap * 2.0 + sim

def build_picon_index(picon_dir: Path):
    if not picon_dir.exists():
        return []
    files = [p for p in picon_dir.rglob("*.png") if p.is_file()]
    return [(p, _tokens_from(p.stem)) for p in files]

def find_best_picon(picon_index, channel_name: str):
    nt = _tokens_from(channel_name)
    if not nt:
        return None

    best_score = 0.0
    best_path = None
    for p, ft in picon_index:
        sc = _score_tokens(nt, ft)
        if sc > best_score:
            best_score = sc
            best_path = p

    if best_path is None:
        return None
    if best_score < 2.2:
        return None
    return best_path


# -------------------------
# Delete helpers (delete -poster/-backdrop/-logo etc.)
# -------------------------
_STEM_SIDECARS = [".nfo", ".jpg", ".jpeg", ".png", ".webp", ".srt", ".ass", ".sub"]
_FOLDER_ART = ["poster.png", "poster.jpg", "poster.jpeg", "folder.png", "folder.jpg", "folder.jpeg", "backdrop.png", "backdrop.jpg", "backdrop.jpeg"]

def delete_related_files_for_strm(strm_path: Path, prune_sidecars: bool):
    """
    When a .strm is removed:
    - if prune_sidecars: delete classic stem sidecars: <stem>.jpg, <stem>.nfo, ...
    - always delete Jellyfin-style artworks: <stem>-poster.jpg / -backdrop.jpg / -logo.png / -landscape.jpg ...
      (matching: "<stem>-*.{jpg,jpeg,png,webp}")
    - if folder has no other .strm after deletion: delete folder art (poster.png etc.)
    """
    try:
        parent = strm_path.parent
        stem = strm_path.with_suffix("")
        stem_str = str(stem)

        if prune_sidecars:
            for ext in _STEM_SIDECARS:
                side = Path(stem_str + ext)
                if side.exists() and side.is_file():
                    try:
                        side.unlink()
                    except Exception:
                        pass

        for p in parent.iterdir():
            if not p.is_file():
                continue
            suf = p.suffix.lower()
            if suf not in (".jpg", ".jpeg", ".png", ".webp"):
                continue
            if p.name.startswith(stem.name + "-"):
                try:
                    p.unlink()
                except Exception:
                    pass

        try:
            remaining = list(parent.glob("*.strm"))
        except Exception:
            remaining = []
        if len(remaining) == 0:
            for fn in _FOLDER_ART:
                q = parent / fn
                if q.exists() and q.is_file():
                    try:
                        q.unlink()
                    except Exception:
                        pass

    except Exception:
        pass


# -------------------------
# Sync
# -------------------------
def run_sync(
    m3u_text: str,
    out_dir: Path,
    allow_cfg: dict,
    sync_delete: bool = True,
    prune_sidecars: bool = False
):
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

    # picon support: /output/picons (inside out_dir)
    picon_dir = out_dir / "picons"
    picon_index = build_picon_index(picon_dir)

    # DEDUPE ONLY FOR MOVIES
    seen_movie_keys = set()

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

            mkey = movie_dedupe_key(tvg_name)
            if mkey and mkey in seen_movie_keys:
                continue
            if mkey:
                seen_movie_keys.add(mkey)

            genre_dir = safe_name(group.replace("/", "_"))
            target = out_dir / "Movies" / genre_dir / (safe_name(clean_lang_tags(tvg_name)) + ".strm")

        else:
            if not allow_item("livetv", group, tvg_name, None, allow_cfg):
                skipped += 1
                continue

            cat_dir = safe_name(group)
            channel_folder = safe_name(channel_folder_from_name(tvg_name))
            channel_dir = out_dir / "LiveTV" / cat_dir / channel_folder
            target = channel_dir / (safe_name(tvg_name) + ".strm")

        desired_paths.add(str(target))
        key = sha256(url)

        changed = write_strm(target, url)
        if changed:
            if str(target) in old_paths:
                updated += 1
            else:
                created += 1

        # LiveTV: copy best picon to poster.png AND backdrop.png in the same channel folder
        if kind == "livetv":
            if picon_index:
                best = find_best_picon(picon_index, tvg_name)
                if best is not None:
                    try:
                        poster = target.parent / "poster.png"
                        backdrop = target.parent / "backdrop.png"
                        write_binary_if_changed(poster, best)
                        write_binary_if_changed(backdrop, best)
                    except Exception:
                        pass

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

                try:
                    delete_related_files_for_strm(p, prune_sidecars=prune_sidecars)
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