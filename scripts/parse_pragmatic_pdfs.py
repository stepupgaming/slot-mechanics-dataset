#!/usr/bin/env python3
"""Parse Pragmatic Play official rules PDFs (text-extractable) into schema records."""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/workspace/slot-mechanics-dataset")
PDF_DIR = ROOT / "sources" / "pragmatic" / "pdfs"
TXT_DIR = ROOT / "sources" / "pragmatic" / "txt"
GAMES = ROOT / "games"
EXTRACTED_AT = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
INDEX = json.loads((ROOT / "sources" / "pragmatic" / "pdf_index.json").read_text())

# map pdf stem -> display title from download index
STEM_TO_TITLE = {}
STEM_TO_URL = {}
for title, path, url in INDEX["ok"]:
    stem = Path(path).stem
    STEM_TO_TITLE[stem] = title
    STEM_TO_URL[stem] = url


def slugify(title: str) -> str:
    s = title.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return "pragmatic-" + s


def extract_text(pdf: Path) -> str:
    r = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True)
    return r.stdout.decode("utf-8", "replace")


def clean_ws(s: str) -> str:
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def section_after(text: str, heading: str, stop_headings: list[str]) -> str:
    m = re.search(rf"(?im)^\s*{re.escape(heading)}\s*$", text)
    if not m:
        # also allow inline heading
        m = re.search(rf"(?i)\b{re.escape(heading)}\b", text)
        if not m:
            return ""
    start = m.end()
    end = len(text)
    for h in stop_headings:
        m2 = re.search(rf"(?im)^\s*{re.escape(h)}\s*$", text[start:])
        if m2:
            end = min(end, start + m2.start())
    return clean_ws(text[start:end])


STOP = [
    "GAME RULES",
    "TUMBLE FEATURE",
    "FREE SPINS",
    "FREE SPINS RULES",
    "BUY FREE SPINS",
    "ANTE BET",
    "MAX WIN",
    "VOLATILITY",
    "HOW TO PLAY",
    "MAIN GAME INTERFACE",
    "SETTINGS MENU",
    "BET MENU",
    "AUTOPLAY",
    "INFORMATION SCREEN",
    "ADDITIONAL INFORMATION",
    "MULTIPLIER SPOTS FEATURE",
    "MONEY SYMBOL",
    "GOLDEN REELS JACKPOT",
    "BONUS GAME",
    "FEATURE RULES",
]


def parse_grid_win(text: str):
    rows = cols = None
    layout_notes = None
    m = re.search(r"played on a\s+(\d+)\s*[xX×]\s*(\d+)\s*grid", text, re.I)
    if m:
        cols, rows = int(m.group(1)), int(m.group(2))
        layout_notes = f"Official rules: played on a {cols}x{rows} grid"
    else:
        m = re.search(r"(\d+)\s*[xX×]\s*(\d+)\s*grid", text, re.I)
        if m:
            cols, rows = int(m.group(1)), int(m.group(2))
            layout_notes = f"Grid {cols}x{rows} mentioned in rules"

    # megaways reel heights
    m = re.search(r"maximum number of possible ways to win is\s*(\d[\d,]*)", text, re.I)
    ways = int(m.group(1).replace(",", "")) if m else None
    m = re.search(r"(\d[\d,]*)\s+ways to win", text, re.I)
    if m and ways is None:
        ways = int(m.group(1).replace(",", ""))

    win_type = "unknown"
    payline_count = None
    min_sym = None
    direction = None
    notes = None

    if re.search(r"symbols? pay anywhere|pay anywhere on the screen", text, re.I):
        win_type = "pay_anywhere"
        direction = "anywhere"
        m = re.search(r"(?:blocks? of )?minimum\s+(\d+)\s+symbols?", text, re.I)
        if m:
            min_sym = int(m.group(1))
        elif re.search(r"8\s*[-–]\s*9|8 of the same|at least 8", text, re.I):
            min_sym = 8
        notes = "Symbols pay anywhere per official GAME RULES"
    elif re.search(r"blocks of minimum\s+\d+\s+symbols connected horizontally or vertically|cluster", text, re.I):
        win_type = "clusters"
        m = re.search(r"minimum\s+(\d+)\s+symbols", text, re.I)
        if m:
            min_sym = int(m.group(1))
        notes = "Connected blocks / cluster pays per official rules"
    elif ways or re.search(r"ways to win|Megaways", text, re.I):
        win_type = "ways"
        direction = "left_to_right"
        notes = "Ways / Megaways adjacent left-to-right"
    elif re.search(r"selected paylines|paylines?|left to right on adjacent reels", text, re.I):
        win_type = "paylines"
        direction = "left_to_right"
        m = re.search(r"(\d+)\s+paylines?", text, re.I)
        if m:
            payline_count = int(m.group(1))
        notes = "Left-to-right adjacent / paylines per official rules"

    # reel height hints for megaways
    if re.search(r"can have (?:from\s+\d+\s+to\s+)?up to\s+\d+\s+symbols", text, re.I):
        layout_notes = (layout_notes or "") + "; variable reel heights described in rules"
        layout_notes = layout_notes.strip("; ")

    return (
        {"rows": rows, "cols": cols, "rows_min": None, "rows_max": None, "layout_notes": layout_notes},
        {
            "type": win_type,
            "payline_count": payline_count,
            "ways_count": ways,
            "min_symbols_for_win": min_sym,
            "direction": direction,
            "notes": notes,
        },
    )


def grab_paragraphs_containing(text: str, pattern: str, limit=3) -> list[str]:
    paras = re.split(r"\n\s*\n", text)
    out = []
    for p in paras:
        if re.search(pattern, p, re.I):
            out.append(clean_ws(p)[:1500])
            if len(out) >= limit:
                break
    if not out:
        # line windows
        for m in re.finditer(pattern, text, re.I):
            start = max(0, m.start() - 200)
            end = min(len(text), m.end() + 400)
            out.append(clean_ws(text[start:end])[:1500])
            if len(out) >= limit:
                break
    return out


def parse_record(stem: str, text: str, pdf_url: str) -> dict:
    title = STEM_TO_TITLE.get(stem, stem.replace("-", " "))
    grid, win_system = parse_grid_win(text)

    tumble = grab_paragraphs_containing(text, r"TUMBLE FEATURE|tumbling will continue")
    cascades = {
        "present": bool(tumble) or bool(re.search(r"TUMBLE FEATURE", text, re.I)),
        "how_it_works": tumble[0] if tumble else None,
    }
    if cascades["present"] is False:
        cascades["present"] = False

    respins_p = grab_paragraphs_containing(text, r"\brespin")
    respins = {
        "present": bool(respins_p) or bool(re.search(r"\brespin", text, re.I)),
        "how_it_works": respins_p[0] if respins_p else None,
    }

    expanding_p = grab_paragraphs_containing(text, r"expand(?:ing|s|ed)?\s+reel|extra rows?")
    expanding = {
        "present": bool(expanding_p),
        "how_it_works": expanding_p[0] if expanding_p else None,
    }

    symbols = {"wilds": [], "scatters": [], "multipliers": [], "collectors": [], "specials": []}
    for lab, key, pat in [
        ("WILD", "wilds", r"This (?:is the |symbol is )?WILD|WILD symbol"),
        ("SCATTER", "scatters", r"This is the SCATTER|SCATTER symbol"),
        ("MULTIPLIER", "multipliers", r"multiplier symbols?|MULTIPLIER symbol"),
        ("MONEY", "collectors", r"MONEY symbol|collect(?:s|ed|ion)"),
    ]:
        paras = grab_paragraphs_containing(text, pat, limit=2)
        for p in paras:
            name = lab
            params = {}
            mults = re.findall(r"(\d+(?:\.\d+)?)\s*x", p, re.I)
            if mults:
                params["multiplier_values_mentioned"] = sorted({float(x) if "." in x else int(x) for x in mults})[:40]
            symbols[key].append({"name": name, "behavior": p, "params": params})

    # free spins
    fs_text = section_after(text, "FREE SPINS RULES", STOP) or section_after(text, "FREE SPINS", STOP)
    fs_modes = []
    if fs_text or re.search(r"FREE SPINS", text, re.I):
        body = fs_text or "\n".join(grab_paragraphs_containing(text, r"FREE SPINS", limit=5))
        mode = {
            "name": "Free Spins",
            "trigger": None,
            "spins_awarded": None,
            "retrigger": None,
            "sticky_or_persistent_state": None,
            "progressive_state": None,
            "effects": body[:3000],
        }
        tm = re.search(r"([^.]{0,40}(?:Hit|Land|Awarded when)\s+\d[^.]*SCATTER[^.]*\.)", body, re.I)
        if tm:
            mode["trigger"] = tm.group(1).strip()
        sm = re.search(
            r"((?:starts? with|awards?|win)\s+\d+\s+free spins[^.]*\.|[\d,x\s]+SCATTER awards?\s+\d+\s+free spins)",
            body,
            re.I,
        )
        if sm:
            mode["spins_awarded"] = sm.group(1).strip()
        if re.search(r"additional free spins|re-?trigger", body, re.I):
            rm = re.search(r"([^.]{0,30}(?:additional free spins|re-?trigger)[^.]{0,160}\.)", body, re.I)
            mode["retrigger"] = rm.group(1).strip() if rm else "Retrigger described in effects"
        if re.search(r"remain in place|sticky|persistent|until the end of the round", body, re.I):
            mode["sticky_or_persistent_state"] = "Persistent/sticky state described in effects"
        if re.search(r"total multiplier|added to the total|increases?", body, re.I):
            mode["progressive_state"] = "Progressive multiplier/collection described in effects"
        fs_modes.append(mode)

    features = []
    for heading in [
        "TUMBLE FEATURE",
        "MULTIPLIER SPOTS FEATURE",
        "ANTE BET",
        "BUY FREE SPINS",
        "MONEY SYMBOL",
        "GOLDEN REELS JACKPOT",
    ]:
        body = section_after(text, heading, STOP)
        if body:
            features.append({"name": heading.title(), "trigger": None, "effects": body[:2500], "params": {}})

    # also add free spins as feature
    if fs_modes:
        features.insert(
            0,
            {
                "name": "Free Spins",
                "trigger": fs_modes[0]["trigger"],
                "effects": fs_modes[0]["effects"][:2000],
                "params": {},
            },
        )

    # feature buy
    buy = {"available": None, "options": [], "notes": None}
    buy_u = []
    buy_sec = section_after(text, "BUY FREE SPINS", STOP) or "\n".join(
        grab_paragraphs_containing(text, r"buying it for|BUY FREE SPINS|purchase.*FREE SPINS")
    )
    if buy_sec:
        buy["available"] = True
        m = re.search(r"(?:buying it for|paying a value equal to|costs?)\s*(\d+(?:\.\d+)?)\s*x", buy_sec, re.I)
        cost = float(m.group(1)) if m else None
        buy["options"].append(
            {
                "name": "Buy Free Spins",
                "cost_multiplier": cost,
                "cost_text": m.group(0) if m else None,
                "effects": buy_sec[:1500],
                "rtp_when_bought_note": None,
            }
        )
        if cost is None:
            buy_u.append("feature_buy.cost_multiplier")
    elif re.search(r"BUY FREE SPINS|FEATURE BUY|Buy Feature", text, re.I):
        buy["available"] = True
        buy_u.append("feature_buy.cost_multiplier")
        buy["notes"] = "Buy feature referenced but cost not clearly extracted"
    else:
        buy["available"] = False

    # ante
    ante = {"available": None, "cost_multiplier": None, "effects": None, "notes": None}
    ante_u = []
    ante_sec = section_after(text, "ANTE BET", STOP)
    if ante_sec or re.search(r"ANTE BET|bet multiplier 25x", text, re.I):
        ante["available"] = True
        ante["effects"] = (ante_sec or "\n".join(grab_paragraphs_containing(text, r"ANTE BET|bet multiplier")))[:2000]
        # Pragmatic ante often expressed as bet multiplier 25x vs 20x, i.e. 1.25x cost
        if re.search(r"Bet multiplier 25x", ante["effects"] or "", re.I) and re.search(
            r"Bet multiplier 20x", ante["effects"] or "", re.I
        ):
            ante["cost_multiplier"] = 1.25
            ante["notes"] = "Inferred from official ante: 25x bet multiplier vs 20x normal (=1.25x total bet cost)"
        else:
            ante_u.append("ante_bet.cost_multiplier")
    else:
        ante["available"] = False

    # max win + RTP
    max_win = None
    max_notes = None
    m = re.search(
        r"maximum win amount is limited to\s*([\d,\.]+)\s*x\s*bet",
        text,
        re.I,
    )
    if m:
        max_win = float(m.group(1).replace(",", ""))
        max_notes = m.group(0).strip()[:300]
    rtp = None
    rtp_notes = None
    # Prefer lines that look like the main RTP statement; skip jurisdiction fragments if multiple
    rtps = re.findall(r"theoretical RTP of this game is\s*(\d{2}(?:\.\d+)?)\s*%", text, re.I)
    if rtps:
        # take first; note ranges if multiple
        rtp = float(rtps[0])
        rtp_notes = f"From official rules PDF: theoretical RTP {rtp}%"
        if len(set(rtps)) > 1:
            rtp_notes += f"; multiple RTP figures appear in PDF: {sorted(set(map(float, rtps)))}"

    unknowns = []
    if grid["rows"] is None:
        unknowns.append("grid.rows/cols")
    if win_system["type"] == "unknown":
        unknowns.append("win_system.type")
    if max_win is None:
        unknowns.append("numeric_limits.max_win_multiplier")
    if rtp is None:
        unknowns.append("numeric_limits.rtp_percent")
    unknowns.extend(buy_u)
    unknowns.extend(ante_u)

    conf = {
        "overall": "high",
        "grid": "high" if grid["rows"] else "medium",
        "win_system": "high" if win_system["type"] != "unknown" else "low",
        "reel_behavior": "high" if cascades["present"] or respins["present"] else "medium",
        "symbols": "high" if any(symbols.values()) else "medium",
        "bonus_free_spins": "high" if fs_modes else "low",
        "features": "high" if features else "medium",
        "feature_buy": "high" if buy.get("options") and buy["options"][0].get("cost_multiplier") else (
            "medium" if buy.get("available") else "low"
        ),
        "numeric_limits": "high" if max_win is not None or rtp is not None else "low",
    }

    excerpt = clean_ws(text)[:700]
    return {
        "schema_version": "1.0.0",
        "updated_at": EXTRACTED_AT,
        "identity": {
            "provider": "Pragmatic Play",
            "title": title,
            "slug": slugify(title),
            "provider_game_id": None,
            "release_year": None,
            "demo_url": None,
            "slotcatalog_url": None,
            "official_info_url": pdf_url,
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
        "feature_buy": buy,
        "ante_bet": ante,
        "numeric_limits": {
            "max_win_multiplier": max_win,
            "max_win_notes": max_notes,
            "rtp_percent": rtp,
            "rtp_notes": rtp_notes,
            "hit_frequency_notes": None,
        },
        "confidence": conf,
        "evidence": [
            {
                "source_type": "official_pdf",
                "url": pdf_url,
                "local_path": f"sources/pragmatic/pdfs/{stem}.pdf",
                "extracted_at": EXTRACTED_AT,
                "quote_or_excerpt": excerpt,
            }
        ],
        "unknowns": sorted(set(unknowns)),
    }


def main():
    TXT_DIR.mkdir(parents=True, exist_ok=True)
    GAMES.mkdir(parents=True, exist_ok=True)
    written = []
    skipped = []
    for pdf in sorted(PDF_DIR.glob("*.pdf")):
        text = extract_text(pdf)
        if sum(c.isalpha() for c in text) < 500:
            skipped.append(pdf.name)
            continue
        (TXT_DIR / (pdf.stem + ".txt")).write_text(text)
        url = STEM_TO_URL.get(pdf.stem, None)
        rec = parse_record(pdf.stem, text, url)
        out = GAMES / (rec["identity"]["slug"] + ".json")
        out.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")
        written.append(rec["identity"]["slug"])
    print(json.dumps({"written": len(written), "skipped_image_pdfs": skipped, "sample": written[:8]}, indent=2))


if __name__ == "__main__":
    main()
