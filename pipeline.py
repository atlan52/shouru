"""Render raw JSONL into curated per-platform markdown.

Reads `data/raw/{platform}_*.jsonl`, dedupes by id, sorts by engagement,
writes `data/curated/{platform}_top200.md` plus `_pipeline_index.md`.

Usage:
  python pipeline.py
"""
import json
from collections import defaultdict
from pathlib import Path
from config import RAW_DIR, CURATED_DIR


TOP_N_PER_PLATFORM = 200
BODY_PREVIEW_CHARS = 400


def _engagement_score(item: dict) -> int:
    e = item.get("engagement") or {}
    views = _as_int(e.get("views"))
    likes = _as_int(e.get("likes"))
    comments = _as_int(e.get("comments"))
    score = _as_int(e.get("score"))
    return views + likes * 20 + comments * 5 + score * 10


def _as_int(v) -> int:
    try:
        if v is None:
            return 0
        return int(v)
    except Exception:
        return 0


def _discover_platforms(raw_dir: Path) -> list[str]:
    names: set[str] = set()
    for p in raw_dir.glob("*.jsonl"):
        stem = p.stem
        if "_" in stem:
            platform = stem.rsplit("_", 1)[0]
        else:
            platform = stem
        if platform:
            names.add(platform)
    return sorted(names)


def _load_platform(raw_dir: Path, platform: str) -> list[dict]:
    seen: dict[str, dict] = {}
    for f in sorted(raw_dir.glob(f"{platform}_*.jsonl")):
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                id_ = item.get("id")
                if not id_:
                    continue
                prev = seen.get(id_)
                if prev is None or _engagement_score(item) >= _engagement_score(prev):
                    seen[id_] = item
        except Exception as e:
            print(f"[pipeline] read {f.name} err: {e}")
    return list(seen.values())


def _sanitize(s: str) -> str:
    return (s or "").replace("\r", " ").strip()


def _body_preview(item: dict, n: int = BODY_PREVIEW_CHARS) -> str:
    body = _sanitize(item.get("body") or "")
    body = " ".join(body.split())
    return body[:n]


def _render_platform_md(platform: str, items: list[dict]) -> str:
    items_sorted = sorted(items, key=_engagement_score, reverse=True)[:TOP_N_PER_PLATFORM]
    lines = []
    lines.append(f"# {platform} — top {len(items_sorted)} posts (income / earning method)\n")
    lines.append(f"_Total unique items collected: {len(items)}_\n")
    for it in items_sorted:
        title = _sanitize(it.get("title") or "(untitled)")
        author = _sanitize(it.get("author") or "")
        url = _sanitize(it.get("url") or "")
        lang = _sanitize(it.get("lang") or "")
        country = _sanitize(it.get("country_hint") or it.get("country") or "")
        e = it.get("engagement") or {}
        views = _as_int(e.get("views"))
        likes = _as_int(e.get("likes"))
        comments = _as_int(e.get("comments"))
        score = _as_int(e.get("score"))
        eng_parts = [f"views={views}", f"likes={likes}", f"comments={comments}"]
        if score:
            eng_parts.append(f"score={score}")
        preview = _body_preview(it)
        lines.append(f"## {title}")
        lines.append(f"- author: {author} | lang: {lang} | country_hint: {country}")
        lines.append(f"- engagement: {', '.join(eng_parts)}")
        lines.append(f"- url: {url}")
        lines.append(f"- body: {preview}")
        lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines)


def _render_index_md(totals: dict[str, dict]) -> str:
    lines = []
    lines.append("# Pipeline index — shouru raw corpus per-platform totals\n")
    lines.append("| platform | unique items | total views | total likes | total comments |")
    lines.append("| --- | ---: | ---: | ---: | ---: |")
    grand = defaultdict(int)
    for platform in sorted(totals.keys()):
        t = totals[platform]
        lines.append(
            f"| {platform} | {t['count']} | {t['views']} | {t['likes']} | {t['comments']} |"
        )
        grand["count"] += t["count"]
        grand["views"] += t["views"]
        grand["likes"] += t["likes"]
        grand["comments"] += t["comments"]
    lines.append(
        f"| **total** | **{grand['count']}** | **{grand['views']}** "
        f"| **{grand['likes']}** | **{grand['comments']}** |"
    )
    lines.append("")
    return "\n".join(lines)


def run():
    CURATED_DIR.mkdir(parents=True, exist_ok=True)
    platforms = _discover_platforms(RAW_DIR)
    if not platforms:
        print(f"[pipeline] no raw jsonl in {RAW_DIR}")
        return

    totals: dict[str, dict] = {}
    for platform in platforms:
        items = _load_platform(RAW_DIR, platform)
        if not items:
            print(f"[pipeline] {platform}: 0 items, skipping")
            continue
        md = _render_platform_md(platform, items)
        out = CURATED_DIR / f"{platform}_top200.md"
        out.write_text(md, encoding="utf-8")
        views = sum(_as_int((it.get("engagement") or {}).get("views")) for it in items)
        likes = sum(_as_int((it.get("engagement") or {}).get("likes")) for it in items)
        comments = sum(_as_int((it.get("engagement") or {}).get("comments")) for it in items)
        totals[platform] = {
            "count": len(items),
            "views": views,
            "likes": likes,
            "comments": comments,
        }
        print(f"[pipeline] wrote {out.name} ({len(items)} items)")

    idx = CURATED_DIR / "_pipeline_index.md"
    idx.write_text(_render_index_md(totals), encoding="utf-8")
    print(f"[pipeline] wrote {idx.name} ({len(totals)} platforms)")


if __name__ == "__main__":
    run()
