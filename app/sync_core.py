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
    """
    Copy src -> dst only if content differs (cheap check: size+mtime then bytes if needed).
    """
    dst.parent.mkdir(parents=True, exist_ok=True)

    if dst.exists():
        try:
            if dst.stat().st_size == src.stat().st_size:
                # fast path: if same size and same sha256, skip
                if sha256(src.read_bytes().hex()) == sha256(dst.read_bytes().hex()):
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


# -------------------------
# LiveTV Folder name (FIXED: uses your proven terminal logic)
# -------------------------
def channel_folder_from_name(name: str) -> str:
    """
    Uses simple separator cutting (no regex) + removes ONLY known country prefixes.
    Example: "DE: SAT 1 HD" -> "SAT 1 HD"
             "CH | SRF 1 HD" -> "SRF 1 HD"
             "DE_ VOX HEVC" -> "VOX HEVC"
             "DE- RTL 2 FHD" -> "RTL 2 FHD"
    """
    def strip_country_prefix(s: str) -> str:
        # only remove these exact prefixes (case-insensitive)
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
                out = t[sp+1:]
                continue
            return out
        return out

    s = (name or '').strip()

    # cut ONCE right of first matching separator, in priority
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

    # remove only known country prefixes
    s = strip_country_prefix(s)
    s = s.lstrip()
    s = ' '.join(s.split())

    return s


# -------------------------
# Picon Matching
# -------------------------
IGNORE_TOKENS = {
    # quality / variants
    "sd", "hd", "fhd", "uhd", "hevc", "hvec",
    "4k", "8k",
    # generic words
    "tv", "channel", "sender",
    "backup",
    # countries / regions (often prefixes)
    "de", "at", "ch", "ger", "eu",
}

def _split_alnum_boundaries(s: str) -> str:
    # "sat1hd" -> "sat 1 hd", "dazn2" -> "dazn 2", "laliga2" -> "laliga 2"
    s = re.sub(r"([a-zA-Z])([0-9])", r"\1 \2", s)
    s = re.sub(r"([0-9])([a-zA-Z])", r"\1 \2", s)
    return s

def _normalize_text_for_tokens(s: str) -> str:
    s = (s or "").strip()

    # cut right of separator once (priority)
    for sep in [":", "|", "_", "-"]:
        if sep in s:
            s = s.split(sep, 1)[1]
            break

    s = s.strip()
    s = s.replace("&", " and ")

    # remove "(1)" "(2)" etc
    s = re.sub(r"\(\s*\d+\s*\)", " ", s)

    s = _split_alnum_boundaries(s)

    # re-join 4k / 8k if split into "4 k"
    s = re.sub(r"\b4\s+k\b", "4k", s, flags=re.IGNORECASE)
    s = re.sub(r"\b8\s+k\b", "8k", s, flags=re.IGNORECASE)

    s = re.sub(r"[^a-zA-Z0-9äöüÄÖÜß ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s

def _tokens_from(s: str):
    s = _normalize_text_for_tokens(s)
    toks = [t for t in s.split(" ") if t and t not in IGNORE_TOKENS]
    return toks

def _score_tokens(name_toks, file_toks) -> float:
    ns = " ".join(name_toks)
    fs = " ".join(file_toks)
    if not ns or not fs:
        return 0.0
    overlap = len(set(name_toks) & set(file_toks))
    sim = SequenceMatcher(None, ns, fs).ratio()
    return overlap * 2.0 + sim

def build_picon_index(picon_dir: Path):
    """
    Returns list of (path, tokens) for all .png under picon_dir (recursive).
    """
    if not picon_dir.exists():
        return []
    files = [p for p in picon_dir.rglob("*.png") if p.is_file()]
    return [(p, _tokens_from(p.stem)) for p in files]

def find_best_picon(picon_index, channel_name: str):
    """
    Returns Path of best picon match or None.
    """
    nt = _tokens_from(channel_name)
    if not nt:
        return None

    best = (0.0, None)
    for p, ft in picon_index:
        s = _score_tokens(nt, ft)
        if s > best[0]:
            best = (s, p)

    # basic threshold: require at least 1 token overlap meaningfully
    if best[1] is None:
        return None
    if best[0] < 2.2:  # tuned: overlap*2 + sim -> needs overlap>=1 usually
        return None
    return best[1]


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
            # livetv
            if not allow_item("livetv", group, tvg_name, None, allow_cfg):
                skipped += 1
                continue

            cat_dir = safe_name(group)
            channel_folder = safe_name(channel_folder_from_name(tvg_name))
            channel_dir = out_dir / "LiveTV" / cat_dir / channel_folder

            # keep original file name (may contain prefix like DE:)
            target = channel_dir / (safe_name(tvg_name) + ".strm")

        desired_paths.add(str(target))
        key = sha256(url)

        changed = write_strm(target, url)
        if changed:
            if str(target) in old_paths:
                updated += 1
            else:
                created += 1

        # If LiveTV: copy best picon to poster.png in the same channel folder
        if kind != "series" and kind != "movie":
            if picon_index:
                best = find_best_picon(picon_index, tvg_name)
                if best is not None:
                    poster = target.parent / "poster.png"
                    try:
                        write_binary_if_changed(poster, best)
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