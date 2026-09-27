#!/usr/bin/env python3
"""Match games to SlotCatalog/BWB cover art, download into thumbs/, stamp JSON."""
from __future__ import annotations

import html as htmlmod
import json
import re
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
GAMES_DIR = ROOT / "games"
THUMBS = ROOT / "thumbs"
SOURCES_SC = ROOT / "sources" / "slotcatalog"
MAP_DIR = Path("/tmp/scmaps")
REPORT = ROOT / "thumbs" / "_report.json"

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://slotcatalog.com/",
    "Accept": "*/*",
}
BWB_UA = {
    "User-Agent": UA["User-Agent"],
    "Referer": "https://www.bigwinboard.com/",
    "Accept": "*/*",
}

PROVIDER_SITEMAP = {
    "Pragmatic Play": ["pragmatic-play.xml", "reel-kingdom.xml"],
    "Hacksaw Gaming": ["hacksaw-gaming.xml", "backseat-gaming.xml"],
    "Backseat Gaming": ["backseat-gaming.xml", "hacksaw-gaming.xml"],
    "Nolimit City": ["nolimit-city.xml"],
}

OG_RE = re.compile(
    r'property=["\']og:image["\']\s+content=["\']([^"\']+)|'
    r'content=["\']([^"\']+)["\']\s+property=["\']og:image["\']',
    re.I,
)


def norm(s: str) -> str:
    s = htmlmod.unescape(s or "").lower()
    s = re.sub(r"[’'`]", "", s)
    s = re.sub(r"&", "and", s)
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s


def http_get(url: str, headers: dict, timeout: float = 30) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(), resp.geturl()


def load_sitemaps() -> dict[str, dict[str, str]]:
    """provider -> norm -> page url"""
    out: dict[str, dict[str, str]] = defaultdict(dict)
    file_to_provs = {
        "pragmatic-play.xml": ["Pragmatic Play"],
        "reel-kingdom.xml": ["Pragmatic Play"],
        "hacksaw-gaming.xml": ["Hacksaw Gaming", "Backseat Gaming"],
        "backseat-gaming.xml": ["Backseat Gaming", "Hacksaw Gaming"],
        "nolimit-city.xml": ["Nolimit City"],
    }
    for fname, provs in file_to_provs.items():
        path = MAP_DIR / fname
        if not path.exists():
            continue
        for url in re.findall(r"<loc>([^<]+)</loc>", path.read_text()):
            if "/slots/" not in url:
                continue
            slug = url.rstrip("/").split("/")[-1]
            n = norm(slug)
            variants = {n}
            for suf in (
                "hacksawgaming",
                "pragmaticplay",
                "nolimitcity",
                "backseatgaming",
                "slot",
                "reelkingdom",
            ):
                if n.endswith(suf) and len(n) > len(suf) + 2:
                    variants.add(n[: -len(suf)])
            for prov in provs:
                for v in variants:
                    out[prov].setdefault(v, url)
    return out


def load_local_ogs() -> dict[str, str]:
    """norm title/stem -> image url"""
    mapping: dict[str, str] = {}
    for p in SOURCES_SC.glob("*.html"):
        text = p.read_text(errors="ignore")
        m = OG_RE.search(text)
        if not m:
            continue
        og = m.group(1) or m.group(2)
        if not og or "/menu/" in og or "gameburger" in og:
            continue
        mapping[norm(p.stem)] = og
        h1 = re.search(r"<h1[^>]*>([^<]+)</h1>", text)
        if h1:
            raw = htmlmod.unescape(h1.group(1))
            raw = re.split(
                r"\s+(?:Slot|Demo|Review|Free|by)\b", raw, maxsplit=1, flags=re.I
            )[0].strip()
            if raw:
                mapping.setdefault(norm(raw), og)
        # title tag
        title = re.search(r"<title>([^<]+)</title>", text, re.I)
        if title:
            raw = htmlmod.unescape(title.group(1))
            raw = re.split(
                r"\s+(?:Slot|Demo|Review|Free|ᐈ)\b", raw, maxsplit=1, flags=re.I
            )[0].strip()
            if raw:
                mapping.setdefault(norm(raw), og)
    return mapping


def title_candidates(title: str, slug: str) -> list[str]:
    cands = [title]
    cands.append(re.sub(r"\s+Slot$", "", title, flags=re.I))
    cands.append("The " + title)
    cands.append(title.replace("&", "and"))
    cands.append(title.replace("Xtreme", "Extreme"))
    cands.append(title.replace(" and ", " & "))
    # Day at Races -> Day At The Races
    cands.append(title.replace("Day at Races", "Day At The Races"))
    cands.append(title.replace("Big Bass & The", "Big Bass and the"))
    cands.append(title.replace("Hold & Spin", "Hold and Spin"))
    cands.append(title.replace("Hold & Spinner", "Hold and Spinner"))
    # slug without provider
    sn = slug
    for pref in ("pragmatic-", "hacksaw-", "backseat-", "nolimit-"):
        if sn.startswith(pref):
            sn = sn[len(pref) :]
            break
    cands.append(sn.replace("-", " "))
    # Book of Fallen -> Book of the Fallen
    if " of " in title and " of the " not in title.lower():
        cands.append(title.replace(" of ", " of the ", 1))
    # The Haunted Circus -> Haunted Circus
    if title.lower().startswith("the "):
        cands.append(title[4:])
    out = []
    seen = set()
    for c in cands:
        n = norm(c)
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def resolve_page_or_image(
    game: dict, sitemaps: dict, local_ogs: dict
) -> tuple[str | None, str | None, str]:
    """Return (image_url_or_none, page_url_or_none, source_tag)."""
    ident = game["identity"]
    title = ident["title"]
    slug = ident["slug"]
    provider = ident["provider"]
    cands = title_candidates(title, slug)

    # 1) local HTML og
    for c in cands:
        if c in local_ogs:
            return local_ogs[c], None, "slotcatalog_local"

    # 2) explicit slotcatalog_url in record
    sc_url = ident.get("slotcatalog_url")
    if sc_url:
        return None, sc_url, "slotcatalog_url"

    # 3) local evidence path
    for ev in game.get("evidence") or []:
        lp = ev.get("local_path") or ""
        if lp.startswith("sources/slotcatalog/") and lp.endswith(".html"):
            p = ROOT / lp
            if p.exists():
                text = p.read_text(errors="ignore")
                m = OG_RE.search(text)
                if m:
                    og = m.group(1) or m.group(2)
                    if og and "/menu/" not in og:
                        return og, None, "slotcatalog_evidence"

    # 4) sitemaps
    sm = sitemaps.get(provider) or {}
    for c in cands:
        if c in sm:
            return None, sm[c], "slotcatalog_sitemap"

    # cross-provider last resort (Backseat listed under Hacksaw etc.)
    for prov, sm2 in sitemaps.items():
        if prov == provider:
            continue
        for c in cands:
            if c in sm2:
                return None, sm2[c], "slotcatalog_sitemap_cross"

    return None, None, "unresolved"


def extract_og(html_bytes: bytes) -> str | None:
    text = html_bytes.decode("utf-8", "ignore")
    m = OG_RE.search(text)
    if not m:
        return None
    og = m.group(1) or m.group(2)
    if not og or "/menu/" in og or "gameburger" in og:
        return None
    return og


def prefer_thumb(url: str) -> str:
    """Prefer _s thumb variant when URL looks like a full shot."""
    if "_s." in url:
        return url
    # Gates-of-Olympus-1.jpg -> Gates-of-Olympus-1_s.jpg
    m = re.match(r"^(https://slotcatalog\.com/userfiles/image/games/.+?)(\.(?:jpg|jpeg|png|webp))$", url, re.I)
    if m:
        return m.group(1) + "_s" + m.group(2)
    return url


def download_image(url: str, headers: dict) -> bytes | None:
    try_urls = [url]
    pref = prefer_thumb(url)
    if pref != url:
        try_urls.insert(0, pref)
    # also try alternate extensions
    extras = []
    for u in list(try_urls):
        if u.lower().endswith(".jpg"):
            extras += [u[:-4] + ".png", u[:-4] + ".webp", u[:-4] + ".JPG"]
        elif u.lower().endswith(".png"):
            extras += [u[:-4] + ".jpg", u[:-4] + ".webp"]
        elif u.lower().endswith(".webp"):
            extras += [u[:-5] + ".jpg", u[:-5] + ".png"]
    try_urls += extras
    seen = set()
    for u in try_urls:
        if u in seen:
            continue
        seen.add(u)
        try:
            data, _ = http_get(u, headers, timeout=40)
            if len(data) < 800:
                continue
            # validate image
            im = Image.open(BytesIO(data))
            im.verify()
            return data
        except Exception:
            continue
    return None


def to_webp(data: bytes, dest: Path, max_w: int = 640) -> None:
    im = Image.open(BytesIO(data))
    im = im.convert("RGB")
    w, h = im.size
    if w > max_w:
        nh = int(h * (max_w / w))
        im = im.resize((max_w, nh), Image.Resampling.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    im.save(dest, "WEBP", quality=82, method=4)


def bwb_lookup(title: str, provider: str) -> str | None:
    """Try Big Win Board WP JSON for a featured image."""
    studio = {
        "Hacksaw Gaming": "hacksaw-gaming",
        "Backseat Gaming": "backseat-gaming",
        "Nolimit City": "nolimit-city",
        "Pragmatic Play": "pragmatic-play",
    }.get(provider, "")
    title_slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    candidates = []
    if studio:
        candidates.append(f"{title_slug}-{studio}-slot-review")
        candidates.append(f"{title_slug}-{studio}-slot-review-demo")
    candidates.append(f"{title_slug}-slot-review")
    for slug in candidates:
        try:
            data, _ = http_get(
                f"https://www.bigwinboard.com/wp-json/wp/v2/posts?slug={slug}",
                BWB_UA,
                timeout=25,
            )
            posts = json.loads(data.decode())
            if not posts:
                continue
            fm = posts[0].get("featured_media")
            if not fm:
                continue
            mdata, _ = http_get(
                f"https://www.bigwinboard.com/wp-json/wp/v2/media/{fm}",
                BWB_UA,
                timeout=25,
            )
            media = json.loads(mdata.decode())
            sizes = (media.get("media_details") or {}).get("sizes") or {}
            for key in ("medium", "mh-magazine-medium", "bwb-gu-thumb", "full"):
                if key in sizes and sizes[key].get("source_url"):
                    return sizes[key]["source_url"]
            return media.get("source_url")
        except Exception:
            continue
    # fuzzy search fallback
    try:
        from urllib.parse import quote
        q = quote(f"{title} {provider.split()[0]}")
        data, _ = http_get(
            f"https://www.bigwinboard.com/wp-json/wp/v2/posts?search={q}&per_page=5",
            BWB_UA,
            timeout=25,
        )
        posts = json.loads(data.decode())
        tn = norm(title)
        for p in posts:
            rendered = htmlmod.unescape(p.get("title", {}).get("rendered") or "")
            if tn and tn in norm(rendered):
                fm = p.get("featured_media")
                if not fm:
                    continue
                mdata, _ = http_get(
                    f"https://www.bigwinboard.com/wp-json/wp/v2/media/{fm}",
                    BWB_UA,
                    timeout=25,
                )
                media = json.loads(mdata.decode())
                sizes = (media.get("media_details") or {}).get("sizes") or {}
                for key in ("medium", "mh-magazine-medium", "full"):
                    if key in sizes and sizes[key].get("source_url"):
                        return sizes[key]["source_url"]
                return media.get("source_url")
    except Exception:
        pass
    return None


def main() -> None:
    THUMBS.mkdir(parents=True, exist_ok=True)
    sitemaps = load_sitemaps()
    local_ogs = load_local_ogs()
    print(f"local og keys: {len(local_ogs)}")
    for prov, sm in sitemaps.items():
        print(f"sitemap {prov}: {len(sm)}")

    records = []
    for path in sorted(GAMES_DIR.glob("*.json")):
        records.append(json.loads(path.read_text()))

    # Phase 1: resolve image URL or page URL
    plan = []
    for rec in records:
        img, page, src = resolve_page_or_image(rec, sitemaps, local_ogs)
        plan.append(
            {
                "slug": rec["identity"]["slug"],
                "title": rec["identity"]["title"],
                "provider": rec["identity"]["provider"],
                "image": img,
                "page": page,
                "source": src,
                "rec": rec,
            }
        )

    need_pages = [p for p in plan if not p["image"] and p["page"]]
    print(f"need page fetch: {len(need_pages)}")

    def fetch_page_og(item):
        try:
            data, final = http_get(item["page"], UA, timeout=35)
            og = extract_og(data)
            return item["slug"], og, None
        except Exception as e:
            return item["slug"], None, str(e)

    page_results = {}
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = [ex.submit(fetch_page_og, p) for p in need_pages]
        for i, fut in enumerate(as_completed(futs), 1):
            slug, og, err = fut.result()
            page_results[slug] = (og, err)
            if i % 50 == 0:
                print(f"  pages {i}/{len(need_pages)}")

    for p in plan:
        if p["image"]:
            continue
        if p["slug"] in page_results:
            og, err = page_results[p["slug"]]
            if og:
                p["image"] = og
                p["source"] = p["source"] + "+og"
            else:
                p["page_error"] = err

    # Phase 2: BWB fallback for still-missing (esp Hacksaw/Backseat)
    missing = [p for p in plan if not p["image"]]
    print(f"missing after SC: {len(missing)}; trying BWB…")
    for p in missing:
        url = bwb_lookup(p["title"], p["provider"])
        if url:
            p["image"] = url
            p["source"] = "bigwinboard"
            time.sleep(0.05)

    # Phase 3: download
    to_dl = [p for p in plan if p["image"]]
    print(f"downloading {len(to_dl)} images…")

    def dl_one(item):
        dest = THUMBS / f"{item['slug']}.webp"
        headers = BWB_UA if item["source"] == "bigwinboard" else UA
        data = download_image(item["image"], headers)
        if not data:
            return item["slug"], False, "download_failed"
        try:
            to_webp(data, dest)
            return item["slug"], True, str(dest.relative_to(ROOT))
        except Exception as e:
            return item["slug"], False, str(e)

    results = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = [ex.submit(dl_one, p) for p in to_dl]
        for i, fut in enumerate(as_completed(futs), 1):
            slug, ok, info = fut.result()
            results[slug] = (ok, info)
            if i % 50 == 0:
                print(f"  downloads {i}/{len(to_dl)}")

    # Phase 4: stamp game JSON
    matched = 0
    gaps = []
    source_counter = Counter()
    for p in plan:
        slug = p["slug"]
        rec = p["rec"]
        ok_info = results.get(slug)
        thumb = None
        if ok_info and ok_info[0]:
            thumb = ok_info[1]
            matched += 1
            source_counter[p["source"].split("+")[0]] += 1
        else:
            gaps.append(
                {
                    "slug": slug,
                    "title": p["title"],
                    "provider": p["provider"],
                    "reason": (ok_info[1] if ok_info else p.get("page_error") or p["source"]),
                }
            )
        rec["thumbnail"] = thumb
        # keep attribution note lightly
        if thumb:
            rec.setdefault("thumbnail_attribution", None)
            src = p["source"]
            if src.startswith("slotcatalog") or "slotcatalog" in src:
                rec["thumbnail_attribution"] = "SlotCatalog"
            elif src == "bigwinboard":
                rec["thumbnail_attribution"] = "Big Win Board"
            else:
                rec["thumbnail_attribution"] = src
        else:
            rec["thumbnail_attribution"] = None

        path = GAMES_DIR / f"{slug}.json"
        path.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")

    report = {
        "total": len(plan),
        "matched": matched,
        "gaps": len(gaps),
        "coverage_pct": round(100.0 * matched / len(plan), 1),
        "sources": dict(source_counter),
        "gap_list": gaps,
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("total", "matched", "gaps", "coverage_pct", "sources")}, indent=2))
    print("gaps:")
    for g in gaps[:40]:
        print(" ", g)


if __name__ == "__main__":
    main()
