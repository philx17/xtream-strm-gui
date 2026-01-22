# app/changes.py
from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Iterable

def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except Exception:
        return default

def write_json(p: Path, obj) -> None:
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

def write_text(p: Path, text: str) -> None:
    p.write_text(text, encoding="utf-8")

def build_snapshot(run_items: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """
    run_items: iterable of dicts describing what you generated (one per strm)
    Must contain:
      - kind: livetv|movies|series
      - title: display title (tvg_name)
      - relpath: relative path inside out_dir (used as stable key)
      - group/show optional (for nicer grouping)
    """
    items = []
    for it in run_items:
        items.append({
            "kind": it.get("kind"),
            "title": it.get("title"),
            "relpath": it.get("relpath"),
            "group": it.get("group"),
            "show": it.get("show"),
            "season": it.get("season"),
        })
    return {"time": utc_iso(), "items": items}

def diff_added(prev_snap: Dict[str, Any], curr_snap: Dict[str, Any]) -> List[Dict[str, Any]]:
    prev_keys = set()
    for it in (prev_snap.get("items") or []):
        prev_keys.add(it.get("relpath") or it.get("title"))

    added = []
    for it in (curr_snap.get("items") or []):
        key = it.get("relpath") or it.get("title")
        if key and key not in prev_keys:
            added.append(it)
    return added

def summarize_added(added: List[Dict[str, Any]]) -> Dict[str, Any]:
    c = {"livetv": 0, "movies": 0, "series": 0, "total": 0}
    for it in added:
        k = it.get("kind")
        if k in ("livetv", "movies", "series"):
            c[k] += 1
            c["total"] += 1
    return c

def format_txt(counts: Dict[str, Any], added: List[Dict[str, Any]]) -> str:
    lines = []
    lines.append(f"Xtream STRM Sync – Neue Inhalte ({utc_iso()})")
    lines.append(f"Total: {counts['total']} | LiveTV: {counts['livetv']} | Movies: {counts['movies']} | Series: {counts['series']}")
    lines.append("")
    if counts["total"] == 0:
        lines.append("Keine neuen Inhalte.")
        return "\n".join(lines)

    # group by kind then by group/show
    def key_kind(it): return it.get("kind") or ""
    added_sorted = sorted(added, key=lambda it: (key_kind(it), (it.get("group") or it.get("show") or ""), (it.get("title") or "")))

    current_section = None
    current_group = None

    for it in added_sorted:
        kind = it.get("kind") or "unknown"
        group = it.get("group") or it.get("show") or "Ungrouped"
        title = it.get("title") or ""
        relpath = it.get("relpath") or ""

        if kind != current_section:
            lines.append("")
            lines.append(kind.upper())
            lines.append("-" * len(kind))
            current_section = kind
            current_group = None

        if group != current_group:
            lines.append(f"* {group}")
            current_group = group

        if relpath:
            lines.append(f"  - {title}  ({relpath})")
        else:
            lines.append(f"  - {title}")

    return "\n".join(lines)

def write_change_files(state_dir: Path, out_dir: Path, run_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Writes:
      - state_dir/last_snapshot.json
      - out_dir/changes_latest.json
      - out_dir/changes_latest.txt
      - out_dir/changes_history.jsonl (append)
    Returns dict for API/GUI.
    """
    ensure_dir(state_dir)
    ensure_dir(out_dir)

    snap_path = state_dir / "last_snapshot.json"
    prev = read_json(snap_path, {"time": None, "items": []})

    curr = build_snapshot(run_items)
    added = diff_added(prev, curr)
    counts = summarize_added(added)

    payload = {
        "time": curr["time"],
        "counts": counts,
        "added": added,  # only added
    }

    # write latest into out_dir (what you want to ship)
    write_json(out_dir / "changes_latest.json", payload)
    write_text(out_dir / "changes_latest.txt", format_txt(counts, added))

    # append history (optional but useful)
    hist = out_dir / "changes_history.jsonl"
    hist.write_text((hist.read_text("utf-8") if hist.exists() else "") + json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")

    # update snapshot for next run
    write_json(snap_path, curr)

    return payload
