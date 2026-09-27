#!/usr/bin/env python3
"""Parse Backseat Gaming official en-us-gameinfo.html (Hacksaw OpenRGS) into schema records.

Provider is labeled Backseat Gaming; gameinfo is served from the Hacksaw CDN.
"""
from __future__ import annotations

import json
import re
import html as HTML
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/workspace/slot-mechanics-dataset")
HS_PAGES = Path("/workspace/slot-mechanics-dataset/sources/backseat/pages")
HS_LIST = Path("/workspace/slot-mechanics-dataset/sources/backseat/LIST.json")
EXTRACTED_AT = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def strip_tags(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</p>", "\n", s, flags=re.I)
    s = re.sub(r"</h[1-6]>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = HTML.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n\n", s)
    return s.strip()


def section_html(text: str, key: str) -> str:
    # match section by data-gameinfo-section (case-insensitive, flexible spacing)
    pat = rf'<section[^>]*data-gameinfo-section=["\']({re.escape(key)})["\'][^>]*>(.*?)(?=<section\s[^>]*data-gameinfo-section=|$)'
    m = re.search(pat, text, re.S | re.I)
    if m:
        return m.group(2)
    # try without escaping for keys with spaces / variants
    for m in re.finditer(
        r'<section[^>]*data-gameinfo-section=["\']([^"\']+)["\'][^>]*>(.*?)(?=<section\s[^>]*data-gameinfo-section=|$)',
        text,
        re.S | re.I,
    ):
        if m.group(1).lower().replace(" ", "") == key.lower().replace(" ", ""):
            return m.group(2)
    return ""


def h2_blocks(section: str) -> list[tuple[str, str]]:
    """Split a section into (h2_title, body_html) pairs; leading content before first h2 is ('__intro__', ...)."""
    parts = re.split(r"<h2[^>]*>", section, flags=re.I)
    out = []
    if not parts:
        return out
    intro = parts[0]
    # drop leading h1
    intro = re.sub(r"<h1[^>]*>.*?</h1>", "", intro, flags=re.S | re.I)
    if strip_tags(intro):
        out.append(("__intro__", intro))
    for part in parts[1:]:
        m = re.match(r"(.*?)</h2>(.*)", part, re.S | re.I)
        if not m:
            continue
        title = strip_tags(m.group(1))
        body = m.group(2)
        out.append((title, body))
    return out


def parse_grid_and_win(about_plain: str, winways_plain: str, winways_html: str):
    rows = cols = None
    layout_notes = None
    m = re.search(r"(\d+)\s*[xX×]\s*(\d+)\s*grid", about_plain)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        # Hacksaw usually writes cols x rows (5x5, 6x5, 5x3)
        cols, rows = a, b
        layout_notes = f"Described as {a}x{b} grid in official About text"
    else:
        m = re.search(r"(\d+)\s*[xX×]\s*(\d+)", about_plain)
        if m:
            cols, rows = int(m.group(1)), int(m.group(2))
            layout_notes = f"Parsed grid {cols}x{rows} from About text"

    # winlines attributes
    wm = re.search(
        r'data-winline-width=["\'](\d+)["\'][^>]*data-winline-height=["\'](\d+)["\']',
        winways_html,
        re.I,
    )
    if not wm:
        wm = re.search(
            r'data-winline-height=["\'](\d+)["\'][^>]*data-winline-width=["\'](\d+)["\']',
            winways_html,
            re.I,
        )
        if wm:
            rows, cols = int(wm.group(1)), int(wm.group(2))
    elif rows is None:
        cols, rows = int(wm.group(1)), int(wm.group(2))

    win_type = "unknown"
    payline_count = ways_count = min_sym = None
    direction = None
    notes = None
    combined = about_plain + "\n" + winways_plain

    if re.search(r"pay\s*anywhere|scatter\s*pays|symbols?\s+anywhere", combined, re.I):
        win_type = "pay_anywhere"
        direction = "anywhere"
        m = re.search(r"(?:at least|minimum of|need)\s+(\d+)\s+(?:matching\s+)?symbols?", combined, re.I)
        if m:
            min_sym = int(m.group(1))
    elif re.search(r"cluster", combined, re.I):
        win_type = "clusters"
    elif re.search(r"\bways?\s+to\s+win\b|\b\d[\d,]*\s+ways\b|adjacent reels from left to right", combined, re.I) and not re.search(
        r"predefined lines|number of possible lines", combined, re.I
    ):
        win_type = "ways"
        direction = "left_to_right"
        m = re.search(r"(\d[\d,]*)\s+ways", combined, re.I)
        if m:
            ways_count = int(m.group(1).replace(",", ""))
    elif re.search(r"paylines?|predefined lines|number of possible lines", combined, re.I):
        win_type = "paylines"
        direction = "left_to_right"
        m = re.search(r"number of possible lines[^0-9]{0,40}(\d+)", combined, re.I)
        if m:
            payline_count = int(m.group(1))
        else:
            m = re.search(r"(\d+)\s+paylines?", combined, re.I)
            if m:
                payline_count = int(m.group(1))

    # count winlines in HTML if present
    if win_type == "paylines" and payline_count is None:
        n = len(re.findall(r'class="Winline\b', winways_html))
        if n:
            payline_count = n

    if "left to right" in combined.lower():
        direction = direction or "left_to_right"

    notes = winways_plain[:500] if winways_plain else None
    return (
        {"rows": rows, "cols": cols, "rows_min": None, "rows_max": None, "layout_notes": layout_notes},
        {
            "type": win_type,
            "payline_count": payline_count,
            "ways_count": ways_count,
            "min_symbols_for_win": min_sym,
            "direction": direction,
            "notes": notes,
        },
    )


def classify_symbol(title: str, body_plain: str):
    t = (title + " " + body_plain).lower()
    name = title.strip() or "Unnamed"
    entry = {"name": name, "behavior": body_plain.strip()[:2000], "params": {}}

    # multiplier values
    mults = re.findall(r"x\s?(\d+(?:\.\d+)?)", body_plain, re.I)
    if mults:
        vals = sorted({float(x) if "." in x else int(x) for x in mults})
        entry["params"]["multiplier_values_mentioned"] = vals[:40]

    if re.search(r"\bwild\b", t) and not re.search(r"non[- ]wild", t):
        return "wilds", entry
    if re.search(r"\bscatter\b|free\s*spin\s*symbol|bonus\s*symbol", t):
        return "scatters", entry
    if re.search(r"\bmultiplier\b|\bx\d+\b", t) and re.search(r"multipl", t):
        return "multipliers", entry
    if re.search(r"\bcollect", t):
        return "collectors", entry
    return "specials", entry


def parse_features_and_fs(blocks: list[tuple[str, str]]):
    symbols = {"wilds": [], "scatters": [], "multipliers": [], "collectors": [], "specials": []}
    features = []
    fs_modes = []
    reel_other = []
    cascades = {"present": None, "how_it_works": None}
    respins = {"present": None, "how_it_works": None}
    expanding = {"present": None, "how_it_works": None}

    for title, body_html in blocks:
        if title == "__intro__":
            continue
        body = strip_tags(body_html)
        if not body and not title:
            continue
        low = (title + " " + body).lower()

        # free spins / bonus modes
        if re.search(r"free\s*spins?|bonus\s*game|bonus\s*feature|hold\s*and\s*win|respin", title, re.I) or (
            re.search(r"trigger(?:s|ed)?\s+(?:the\s+)?(?:free|bonus)", body, re.I)
            and re.search(r"free\s*spin|bonus", low)
        ):
            mode = {
                "name": title,
                "trigger": None,
                "spins_awarded": None,
                "retrigger": None,
                "sticky_or_persistent_state": None,
                "progressive_state": None,
                "effects": body[:2500],
            }
            tm = re.search(
                r"(land(?:ing)?\s+(?:\d+|three|four|five|six)[^.]*?(?:scatter|symbol)[^.]*?\.)",
                body,
                re.I,
            )
            if tm:
                mode["trigger"] = tm.group(1).strip()
            else:
                tm = re.search(r"([^.]{0,120}trigger[^.]{0,160}\.)", body, re.I)
                if tm:
                    mode["trigger"] = tm.group(1).strip()
            sm = re.search(
                r"((?:starts? with|awards?|granted?|receive|get)\s+\d+\s+(?:free\s*)?spins?[^.]*)",
                body,
                re.I,
            )
            if sm:
                mode["spins_awarded"] = sm.group(1).strip()
            if re.search(r"re-?trigger|additional\s+free\s*spins?|\+\s*\d+\s*(?:free\s*)?spins?", body, re.I):
                rm = re.search(r"([^.]{0,40}(?:re-?trigger|\+\s*\d+\s*(?:free\s*)?spins?)[^.]{0,120}\.)", body, re.I)
                mode["retrigger"] = rm.group(1).strip() if rm else "Retrigger mentioned (see effects)"
            if re.search(r"sticky|remain(?:s|ing)?\s+on\s+the\s+(?:reels|grid)|persistent", body, re.I):
                mode["sticky_or_persistent_state"] = "Sticky/persistent state described in effects"
            if re.search(r"accumulat|increas(?:e|ing)|progress|meter|collect(?:ed|ion)?", body, re.I):
                mode["progressive_state"] = "Progressive/accumulating state described in effects"
            fs_modes.append(mode)
            features.append({"name": title, "trigger": mode["trigger"], "effects": body[:2000], "params": {}})
        else:
            # reel behaviors
            if re.search(r"cascade|tumble|avalanche|super\s*cascade", low):
                cascades = {"present": True, "how_it_works": body[:1500]}
            if re.search(r"\brespin", low):
                respins = {"present": True, "how_it_works": body[:1500]}
            if re.search(r"expand(?:ing|s|ed)?\s+reel|reel\s+height|extra\s+row", low):
                expanding = {"present": True, "how_it_works": body[:1500]}

            cat, entry = classify_symbol(title, body)
            # avoid dumping pure UI junk
            if len(body) > 40:
                symbols[cat].append(entry)
                features.append(
                    {
                        "name": title,
                        "trigger": None,
                        "effects": body[:2000],
                        "params": entry.get("params") or {},
                    }
                )

    return symbols, features, fs_modes, cascades, respins, expanding


def parse_max_win(text_plain: str, features_plain: str):
    max_win = None
    notes = None
    for src in (features_plain, text_plain):
        m = re.search(
            r"maximum\s+(?:feature\s+)?win[^0-9]{0,40}(\d[\d\s,]*)\s*(?:times|x)\s*(?:your\s*)?bet",
            src,
            re.I,
        )
        if not m:
            m = re.search(
                r"maximum\s+achievable\s+win[^0-9]{0,40}(\d[\d\s,]*)\s*times",
                src,
                re.I,
            )
        if not m:
            m = re.search(r"max(?:imum)?\s*win\s+of\s+up\s+to\s*\{?maximumWinMultiplier\}?x", src, re.I)
            # placeholder — skip
            if m:
                continue
        if m:
            raw = re.sub(r"[\s,]", "", m.group(1))
            try:
                max_win = int(raw)
                notes = m.group(0).strip()[:300]
                break
            except ValueError:
                pass
    # also {maximumWinMultiplier} in about — leave null
    return max_win, notes


def parse_feature_buy(section_html_raw: str):
    plain = strip_tags(section_html_raw)
    available = None
    options = []
    notes = None
    if not plain:
        return {"available": None, "options": [], "notes": "No featureBuy section found"}, ["feature_buy.cost_multiplier"]

    if re.search(r"offers the possibility to purchase|BUY BONUS|bonus buy", plain, re.I):
        available = True
    elif re.search(r"does not offer|not available|no bonus buy", plain, re.I):
        available = False

    # Named options with possible costs — only capture numeric costs if explicit (not placeholders)
    for m in re.finditer(
        r"(?:buy|purchase|cost(?:s)?)\s+([^.]{0,80}?)(?:for\s+)?(\d+(?:\.\d+)?)\s*x\s*(?:the\s*)?(?:total\s*)?bet",
        plain,
        re.I,
    ):
        options.append(
            {
                "name": m.group(1).strip(" :,-")[:80] or None,
                "cost_multiplier": float(m.group(2)),
                "cost_text": m.group(0).strip()[:200],
                "effects": None,
                "rtp_when_bought_note": None,
            }
        )

    # data-bonus-game attributes
    for m in re.finditer(
        r'data-bonus-game-name=["\']([^"\']+)["\']',
        section_html_raw,
        re.I,
    ):
        name = m.group(1)
        if not any(o.get("name") == name for o in options):
            options.append(
                {
                    "name": name,
                    "cost_multiplier": None,
                    "cost_text": None,
                    "effects": None,
                    "rtp_when_bought_note": "RTP when buying is template-injected ({featureBuyRtp}) in gameinfo HTML",
                }
            )

    unknowns = []
    if available and not any(o.get("cost_multiplier") is not None for o in options):
        unknowns.append("feature_buy.cost_multiplier")
        notes = (
            (notes or "")
            + " Bonus buy available per official rules, but cost multipliers are not stated as concrete numbers in the static gameinfo HTML (often runtime-injected)."
        ).strip()

    if "{featureBuyRtp}" in section_html_raw or "{featureBuyName}" in section_html_raw:
        unknowns.append("feature_buy.rtp_when_bought")

    return {"available": available, "options": options, "notes": notes}, unknowns


def title_from_about(about_plain: str, slug: str) -> str:
    # Prefer explicit game name patterns
    m = re.search(
        r"([A-Z][^!]{2,60}?)\s+is\s+a\s+(?:high|medium|low|volatile|action|grid|5x|6x|cluster|ways|paylines)",
        about_plain,
    )
    if m:
        return m.group(1).strip()
    m = re.search(r"Welcome to[^!]*?!\s*([^.]+?)\s+is\s+a\s+", about_plain)
    if m:
        return m.group(1).strip()
    # fallback: title-case slug
    return slug.replace("-", " ").title()


def build_record(meta: dict, html: str) -> dict:
    slug = meta["slug"]
    features_html = (
        section_html(html, "features")
        or section_html(html, "features_section")
        or section_html(html, "Features")
        or ""
    )
    # some games split about + features; Backseat/OpenRGS often uses about_the_game
    about_html = (
        section_html(html, "about")
        or section_html(html, "about_the_game")
        or section_html(html, "About")
        or ""
    )
    if about_html and features_html:
        combined_feat_html = about_html + features_html
    elif about_html:
        combined_feat_html = about_html
    else:
        combined_feat_html = features_html

    special_html = (
        section_html(html, "special_symbols")
        or section_html(html, "specialsymbols")
        or section_html(html, "special symbols")
        or ""
    )
    if special_html:
        combined_feat_html += special_html

    winways_html = section_html(html, "winways")
    paytable_html = section_html(html, "paytable")
    buy_html = section_html(html, "featureBuy")
    maxwin_html = section_html(html, "generalSection-maxwin")

    about_plain = strip_tags(combined_feat_html)
    winways_plain = strip_tags(winways_html)
    paytable_plain = strip_tags(paytable_html)
    full_plain = strip_tags(html)

    grid, win_system = parse_grid_and_win(about_plain, winways_plain, winways_html)
    blocks = h2_blocks(combined_feat_html)
    symbols, features, fs_modes, cascades, respins, expanding = parse_features_and_fs(blocks)

    # If about mentions cascades globally
    if cascades["present"] is None and re.search(r"cascade|tumble", about_plain, re.I):
        cascades = {
            "present": True,
            "how_it_works": "Cascades/tumbles mentioned in About/Features; see feature texts for details.",
        }
    if respins["present"] is None and re.search(r"\brespin", about_plain, re.I):
        respins = {
            "present": True,
            "how_it_works": "Respins mentioned in About/Features; see feature texts for details.",
        }

    max_win, max_win_notes = parse_max_win(full_plain + "\n" + strip_tags(maxwin_html), about_plain)
    feature_buy, buy_unknowns = parse_feature_buy(buy_html)

    # ante / featurespins
    ante = {"available": None, "cost_multiplier": None, "effects": None, "notes": None}
    ante_unknowns = []
    if re.search(r"feature\s*spins|ante\s*bet|featurespins", full_plain, re.I):
        ante["available"] = True
        ante["notes"] = "FeatureSpins/ante-style options referenced in gameinfo; concrete cost multipliers often runtime-injected."
        ante_unknowns.append("ante_bet.cost_multiplier")

    # RTP — only if concrete number (not {rtp})
    rtp = None
    rtp_notes = None
    m = re.search(r"theoretical payout \(RTP\) for this game is \{rtp\}%", paytable_plain, re.I)
    if m:
        rtp_notes = "Official gameinfo uses template placeholder {rtp}%; concrete RTP not present in static HTML."
    else:
        m = re.search(r"RTP[^0-9%]{0,40}(\d{2}(?:\.\d+)?)\s*%", paytable_plain, re.I)
        if m:
            rtp = float(m.group(1))
            rtp_notes = "RTP stated in official gameinfo paytable section."

    title = meta.get("clean_title") or title_from_about(about_plain, slug)

    unknowns = []
    if grid["rows"] is None or grid["cols"] is None:
        unknowns.append("grid.rows/cols")
    if win_system["type"] == "unknown":
        unknowns.append("win_system.type")
    if max_win is None:
        unknowns.append("numeric_limits.max_win_multiplier")
    if rtp is None:
        unknowns.append("numeric_limits.rtp_percent")
    unknowns.extend(buy_unknowns)
    unknowns.extend(ante_unknowns)
    if not fs_modes:
        unknowns.append("bonus_free_spins.modes (none clearly extracted)")

    # confidence
    conf = {
        "overall": "high",
        "grid": "high" if grid["rows"] else "low",
        "win_system": "high" if win_system["type"] != "unknown" else "low",
        "reel_behavior": "medium",
        "symbols": "high" if any(symbols.values()) else "low",
        "bonus_free_spins": "high" if fs_modes else "low",
        "features": "high" if features else "medium",
        "feature_buy": "medium" if feature_buy["available"] else "low",
        "numeric_limits": "high" if max_win is not None else "low",
    }
    # overall: high if core mechanics from official rules
    if conf["win_system"] == "high" and conf["features"] == "high":
        conf["overall"] = "high"
    elif conf["win_system"] == "high" and conf["grid"] == "high":
        # Official gameinfo with clear grid/win system even if feature h2 blocks sparse
        conf["overall"] = "high" if (features or fs_modes or about_plain) else "medium"
        if conf["features"] == "medium" and about_plain:
            conf["features"] = "high"
    elif conf["features"] == "high":
        conf["overall"] = "medium"
    else:
        conf["overall"] = "low"

    excerpt = about_plain[:600]

    record = {
        "schema_version": "1.0.0",
        "updated_at": EXTRACTED_AT,
        "identity": {
            "provider": "Backseat Gaming",
            "title": title,
            "slug": f"backseat-{slug}",
            "provider_game_id": str(meta.get("gameid")) if meta.get("gameid") else None,
            "release_year": None,
            "demo_url": meta.get("launcher"),
            "slotcatalog_url": None,
            "official_info_url": meta.get("info_url"),
        },
        "grid": grid,
        "win_system": win_system,
        "reel_behavior": {
            "cascades_or_tumbles": cascades,
            "respins": respins,
            "expanding_reels": expanding,
            "other": [],
        },
        "symbols": symbols,
        "bonus_free_spins": {"modes": fs_modes, "notes": None},
        "features": features,
        "feature_buy": feature_buy,
        "ante_bet": ante,
        "numeric_limits": {
            "max_win_multiplier": max_win,
            "max_win_notes": max_win_notes,
            "rtp_percent": rtp,
            "rtp_notes": rtp_notes,
            "hit_frequency_notes": (
                "Hit frequency uses template {hitfreq}% in static gameinfo"
                if "{hitfreq}" in html
                else None
            ),
        },
        "confidence": conf,
        "evidence": [
            {
                "source_type": "official_gameinfo",
                "url": meta.get("info_url"),
                "local_path": f"sources/backseat/pages/{slug}/en-us-gameinfo.html",
                "extracted_at": EXTRACTED_AT,
                "quote_or_excerpt": excerpt,
            }
        ],
        "unknowns": sorted(set(unknowns)),
    }
    return record


def clean_list_title(t: str) -> str:
    t = HTML.unescape(t or "")
    t = re.sub(r"\s*\(Backseat Gaming\)\s*Slot Review.*$", "", t, flags=re.I)
    t = re.sub(r"\s*Slot Review.*$", "", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    return t.strip()


def main():
    metas = json.loads(HS_LIST.read_text())
    by_slug = {m["slug"]: m for m in metas if m.get("slug")}
    games_dir = ROOT / "games"
    src_dir = ROOT / "sources" / "backseat" / "pages"
    games_dir.mkdir(parents=True, exist_ok=True)
    src_dir.mkdir(parents=True, exist_ok=True)

    written = []
    errors = []
    for slug_dir in sorted(HS_PAGES.iterdir()):
        if not slug_dir.is_dir():
            continue
        slug = slug_dir.name
        info = slug_dir / "en-us-gameinfo.html"
        if not info.exists():
            info = slug_dir / "info.html"
        if not info.exists():
            errors.append((slug, "missing en-us-gameinfo.html"))
            continue
        html = info.read_text(errors="replace")
        meta = by_slug.get(slug, {"slug": slug})
        meta = dict(meta)
        if meta.get("status") and meta.get("status") != "ok":
            continue
        meta["clean_title"] = clean_list_title(meta.get("title", "")) or meta.get("title") or slug.replace("-", " ").title()
        # demo launcher from gameid
        if meta.get("gameid") and not meta.get("launcher"):
            meta["launcher"] = (
                f"https://static-live.hacksawgaming.com/launcher/static-launcher.html"
                f"?gameid={meta['gameid']}&channel=desktop&language=en&partner=demo&mode=demo&token=123"
            )
        try:
            rec = build_record(meta, html)
        except Exception as e:
            errors.append((slug, str(e)))
            continue
        # copy source
        out_src = src_dir / slug
        out_src.mkdir(parents=True, exist_ok=True)
        (out_src / "en-us-gameinfo.html").write_text(html)
        # write game json
        out_name = rec["identity"]["slug"] + ".json"
        (games_dir / out_name).write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")
        written.append(rec["identity"]["slug"])

    summary = {
        "written": len(written),
        "errors": errors[:20],
        "error_count": len(errors),
        "sample": written[:5],
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
