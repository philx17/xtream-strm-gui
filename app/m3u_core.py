import re
from urllib.parse import urlparse

EXTINF_RE = re.compile(r"#EXTINF:(?P<dur>-?\d+)\s*(?P<attrs>[^,]*),(?P<title>.*)$")
LANG_TAG_RE = re.compile(r"\((DE|GER|DEU|EN|ENG|FR|ES|IT|TR|AR|RU|PL|NL)\)", re.IGNORECASE)
SERIES_GROUP_HINTS = ["series", "serien", "tv shows", "shows"]


def parse_attrs(attr_str: str) -> dict:
    attrs = {}
    for m in re.finditer(r'([A-Za-z0-9\-_]+)="([^"]*)"', attr_str):
        attrs[m.group(1)] = m.group(2)
    return attrs


def parse_m3u(m3u_text: str):
    lines = [ln.strip() for ln in m3u_text.splitlines() if ln.strip()]
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("#EXTINF"):
            m = EXTINF_RE.match(ln)
            if not m:
                i += 1
                continue
            attrs = parse_attrs(m.group("attrs") or "")
            title = (m.group("title") or "").strip()

            j = i + 1
            url = None
            while j < len(lines):
                if not lines[j].startswith("#"):
                    url = lines[j].strip()
                    break
                j += 1

            if url:
                yield {"title": title, "attrs": attrs, "url": url}
            i = j + 1 if j > i else i + 1
        else:
            i += 1


def has_episode_pattern(s: str) -> bool:
    t = (s or "").lower()
    return bool(re.search(r"(s\s*\d{1,2}\s*e\s*\d{1,2}|s\d{1,2}e\d{1,2}|\d{1,2}\s*x\s*\d{1,2})", t))


def url_ext(url: str) -> str:
    try:
        path = urlparse(url).path.lower()
        if "." in path:
            return path.rsplit(".", 1)[-1]
    except Exception:
        pass
    return ""


def is_series_group(group: str) -> bool:
    g = (group or "").lower()
    return any(h in g for h in SERIES_GROUP_HINTS)


def clean_lang_tags(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(LANG_TAG_RE, "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def extract_show_season_episode(raw_title: str):
    title = (raw_title or "").strip()

    # S01 E06
    m = re.search(
        r"^(?P<show>.*?)[\s\-_:|.]*S\s*(?P<s>\d{1,2})\s*E\s*(?P<e>\d{1,2})[\s\-_:|.]*?(?P<ep>.*)$",
        title,
        flags=re.IGNORECASE,
    )
    if m:
        show = clean_lang_tags(m.group("show").strip(" -_:|."))
        season = int(m.group("s"))
        epn = int(m.group("e"))
        ep_title = m.group("ep").strip(" -_:|.") or None
        return show, season, epn, ep_title

    # S01E06
    m = re.search(
        r"^(?P<show>.*?)[\s\-_:|.]*S(?P<s>\d{1,2})E(?P<e>\d{1,2})[\s\-_:|.]*?(?P<ep>.*)$",
        title,
        flags=re.IGNORECASE,
    )
    if m:
        show = clean_lang_tags(m.group("show").strip(" -_:|."))
        season = int(m.group("s"))
        epn = int(m.group("e"))
        ep_title = m.group("ep").strip(" -_:|.") or None
        return show, season, epn, ep_title

    # 1x06
    m = re.search(
        r"^(?P<show>.*?)[\s\-_:|.]*?(?P<s>\d{1,2})\s*x\s*(?P<e>\d{1,2})[\s\-_:|.]*?(?P<ep>.*)$",
        title,
        flags=re.IGNORECASE,
    )
    if m:
        show = clean_lang_tags(m.group("show").strip(" -_:|."))
        season = int(m.group("s"))
        epn = int(m.group("e"))
        ep_title = m.group("ep").strip(" -_:|.") or None
        return show, season, epn, ep_title

    return None, None, None, None


def classify_item(url: str, group: str, tvg_name: str, title: str) -> str:
    """
    Your rules:
    - series if group indicates series OR episode pattern in name
    - movie only if URL ends with .mkv or .mp4 (and not series)
    - else live tv
    """
    if is_series_group(group) or has_episode_pattern(tvg_name) or has_episode_pattern(title):
        return "series"

    ext = url_ext(url)
    if ext in ("mkv", "mp4"):
        return "movie"

    return "livetv"


def build_catalog(m3u_text: str):
    cat = {
        "livetv": {"categories": {}, "total": 0},
        "movies": {"categories": {}, "total": 0},
        "series": {"shows": {}, "total": 0},
    }

    for it in parse_m3u(m3u_text):
        attrs = it["attrs"]
        url = it["url"]
        title = it["title"]
        group = attrs.get("group-title") or "Ungrouped"
        tvg_name = attrs.get("tvg-name") or title
        logo = attrs.get("tvg-logo") or ""

        kind = classify_item(url, group, tvg_name, title)

        item = {
            "group": group,
            "tvg_name": tvg_name,
            "title": title,
            "url": url,
            "logo": logo,
        }

        if kind in ("livetv", "movie"):
            store_kind = "movies" if kind == "movie" else "livetv"
            cat[store_kind]["categories"].setdefault(group, []).append(item)
            cat[store_kind]["total"] += 1
        else:
            show, season, epn, ep_title = extract_show_season_episode(tvg_name)
            if not show:
                show = clean_lang_tags(tvg_name)
                season = 0
                epn = 0

            show_obj = cat["series"]["shows"].setdefault(show, {"seasons": {}, "total": 0})
            season_key = f"{int(season):02d}"
            show_obj["seasons"].setdefault(season_key, []).append(
                {
                    **item,
                    "show": show,
                    "season": int(season),
                    "episode": int(epn),
                    "ep_title": ep_title,
                }
            )
            show_obj["total"] += 1
            cat["series"]["total"] += 1

    return cat
