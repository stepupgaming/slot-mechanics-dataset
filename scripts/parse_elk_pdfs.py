#!/usr/bin/env python3
"""Parse Elk Studios official Game Description PDFs into schema 1.1.0 records.

Modeled on games/elk-ryze.json gold shape + scripts/parse_pragmatic_pdfs.py.
Only writes high-confidence records when PDF text is rebuildable (skip thin/image).
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
PDF_DIR = ROOT / "sources" / "elk" / "pdfs"
TXT_DIR = ROOT / "sources" / "elk" / "txt"
GAMES = ROOT / "games"
SLUG_MAP = json.loads((ROOT / "sources" / "elk" / "slug_to_id.json").read_text())
EXTRACTED_AT = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
CDN = "https://cnsicdn.kubdev.com/common-content/help/CNSI/game-documents/"
GAMERULES_DIR = ROOT / "sources" / "elk" / "gamerules"
THUMBS = ROOT / "thumbs"

# pdf stem / id -> slug (prefer primary slug when skins share id)
ID_TO_SLUG = {}
for slug, meta in SLUG_MAP.items():
    ID_TO_SLUG.setdefault(meta["id"], slug)
# Prefer canonical skins
ID_TO_SLUG["10234"] = "pirots-4"

SKIP_SLUGS = {"ryze"}  # already gold on main


def clean_ws(s: str) -> str:
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def flatten(s: str) -> str:
    return clean_ws(s.replace("\x0c", "\n"))


def money_num(s: str) -> float | None:
    m = re.search(r"([\d][\d\s,]*(?:\.\d+)?)", s)
    if not m:
        return None
    return float(m.group(1).replace(" ", "").replace(",", ""))


def parse_key_features(text: str) -> dict:
    """Pull Key features table fields (layout varies)."""
    out = {
        "name": None,
        "id": None,
        "rtp": None,
        "lines": None,
        "reels": None,
        "rows": None,
        "hit_frequency": None,
        "min_bet": None,
        "max_bet": None,
        "max_exposure": None,
        "max_win_spin": None,
        "maximum_win_eur": None,
    }
    # Name
    m = re.search(r"Name in\s+English\s+(.+?)(?:\nELK|\nProduct)", text, re.S | re.I)
    if not m:
        m = re.search(r"Name in English\s+(.+)", text)
    if m:
        out["name"] = clean_ws(m.group(1).split("\n")[0])
    m = re.search(r"ELK Game id\s+(\d+)", text, re.I)
    if not m:
        m = re.search(r"ELK Game\s+id\s+(\d+)", text, re.I)
    if m:
        out["id"] = m.group(1)
    m = re.search(r"Theoretical\s+RTP\s+([\d.]+)\s*%", text, re.I)
    if not m:
        m = re.search(r"Theoretical\s+([\d.]+)\s*%\s*RTP", text, re.I)
    if not m:
        m = re.search(r"theoretical payout \(RTP\).*?([\d.]+)\s*%", text, re.I)
    if m:
        out["rtp"] = float(m.group(1))
    m = re.search(r"Hit frequency\s+([\d.]+)\s*%", text, re.I)
    if m:
        out["hit_frequency"] = float(m.group(1))
    m = re.search(r"Min bet\s+€\s*([\d.]+)", text, re.I)
    if m:
        out["min_bet"] = float(m.group(1))
    m = re.search(r"Max bet\s+€\s*([\d.]+)", text, re.I)
    if m:
        out["max_bet"] = float(m.group(1))
    m = re.search(r"Max exposure\s+([\d\s]+)\s*x", text, re.I)
    if m:
        out["max_exposure"] = float(m.group(1).replace(" ", ""))
    m = re.search(r"Max win single\s*(?:spin)?\s*([\d\s]+)\s*x", text, re.I | re.S)
    if m:
        out["max_win_spin"] = float(re.sub(r"\s+", "", m.group(1)))
    m = re.search(r"Maximum win\s+€\s*([\d,\.]+)", text, re.I)
    if m:
        out["maximum_win_eur"] = float(m.group(1).replace(",", ""))

    # Lines / win system blurb (may wrap)
    m = re.search(r"Lines\s+(.+?)(?:\nJackpot|\nReels)", text, re.S | re.I)
    if m:
        out["lines"] = clean_ws(m.group(1))

    m = re.search(r"Reels\s+(.+)", text)
    if m:
        out["reels"] = clean_ws(m.group(1).split("\n")[0])
    m = re.search(r"Rows\s+(.+)", text)
    if m:
        out["rows"] = clean_ws(m.group(1).split("\n")[0])
        # sometimes rows wraps: "4 rows expanding up to 8"
        if "expand" not in out["rows"].lower():
            # peek next line
            m2 = re.search(r"Rows\s+.+\n\s*(.+)", text)
            if m2 and re.search(r"expand|row", m2.group(1), re.I):
                out["rows"] = clean_ws(out["rows"] + " " + m2.group(1))
    return out


def parse_grid(text: str, kf: dict) -> dict:
    rows = cols = rows_min = rows_max = None
    layout_notes_parts = []

    # Prefer descriptive sentence: "N row by M column" / "N columns by M rows"
    patterns = [
        r"(\d+)\s*rows?\s+by\s+(\d+)\s*columns?",
        r"(\d+)\s*columns?\s+by\s+(\d+)\s*rows?",
        r"(\d+)\s*row\s+by\s+(\d+)\s*column",
        r"(\d+)\s*column[s,]?\s+(\d+)\s*row",
        r"(\d+)\s*reels?\s+and\s+(\d+)\s*rows?",
    ]
    # Determine orientation from pattern
    m = re.search(
        r"(?:is a |starts with a )?(\d+)\s*(?:row|rows)\s+by\s+(\d+)\s*(?:column|columns)",
        text,
        re.I,
    )
    if m:
        rows, cols = int(m.group(1)), int(m.group(2))
        layout_notes_parts.append(f"Official Game Description: {rows} rows by {cols} columns")
    elif re.search(r"(\d+)\s*rows?\s+and\s+(\d+)(?:-(\d+))?\s*columns?", text, re.I):
        m = re.search(r"(\d+)\s*rows?\s+and\s+(\d+)(?:-(\d+))?\s*columns?", text, re.I)
        rows = int(m.group(1))
        cols = int(m.group(3) or m.group(2))
        layout_notes_parts.append(f"Official Game Description: {m.group(0)}")
    else:
        m = re.search(
            r"(\d+)\s*(?:column|columns|reels?)\s*(?:by|,|and)\s*(\d+)\s*(?:row|rows)",
            text,
            re.I,
        )
        if m:
            cols, rows = int(m.group(1)), int(m.group(2))
            layout_notes_parts.append(f"Official Game Description: {cols} columns by {rows} rows")

    # Expand ranges
    m = re.search(
        r"expand(?:s|ing|ed)?\s+up\s+to\s+(?:the\s+maximum\s+)?(\d+)\s*rows?\s+by\s+(\d+)\s*columns?",
        text,
        re.I,
    )
    if m:
        rows_max = int(m.group(1))
        cols_max = int(m.group(2))
        layout_notes_parts.append(f"expands up to {rows_max} rows by {cols_max} columns")
        if rows is not None:
            rows_min = rows
            rows = rows_max  # store upper for primary? Gold ryze stores upper for cols. For rows use max + min
            # Convention: rows = base or max? ryze uses fixed 6. For expandable: rows=base, rows_min/max set
            # Task: "Expandable grids: layout_notes + rows_min/rows_max when present"
            rows = rows_min  # keep base as rows
        layout_notes_parts.append(
            f"schema has rows_min/rows_max; cols variable upper={cols_max} noted in layout_notes (no cols_min/cols_max)"
        )
    else:
        m = re.search(r"expand(?:s|ing|ed)?\s+up\s+to\s+(?:the\s+maximum\s+)?(\d+)\s*rows?", text, re.I)
        if m:
            rows_max = int(m.group(1))
            if rows is not None:
                rows_min = rows
            layout_notes_parts.append(f"rows expand up to {rows_max}")
        m = re.search(
            r"(\d+)\s*columns?\s+expanding\s+up\s+to\s+(\d+)",
            text,
            re.I,
        )
        if m:
            cols = int(m.group(1))
            layout_notes_parts.append(f"columns expand up to {m.group(2)}")

    # Fallback to key features
    if rows is None and kf.get("rows"):
        m = re.search(r"(\d+)\s*rows?", kf["rows"], re.I)
        if m:
            rows = int(m.group(1))
            layout_notes_parts.append(f"Key features Rows: {kf['rows']}")
        m = re.search(r"expanding up to (\d+)", kf["rows"], re.I)
        if m:
            rows_max = int(m.group(1))
            rows_min = rows
    if cols is None and kf.get("reels"):
        m = re.search(r"(\d+)\s*(?:columns?|reels?)", kf["reels"], re.I)
        if m:
            cols = int(m.group(1))
            layout_notes_parts.append(f"Key features Reels: {kf['reels']}")
        # "5 to 6 columns"
        m = re.search(r"(\d+)\s*to\s*(\d+)\s*columns?", kf["reels"], re.I)
        if m:
            cols = int(m.group(2))
            layout_notes_parts.append(
                f"Columns vary {m.group(1)}-{m.group(2)}; cols={cols} (upper) because schema has no cols_min/cols_max"
            )

    # Slurpy-style "5 columns expanding up to 7" / rows line
    if cols is None:
        m = re.search(r"Reels\s+(\d+)\s*columns?\s+expanding\s+up\s+to\s+(\d+)", text, re.I)
        if m:
            cols = int(m.group(1))
            layout_notes_parts.append(f"columns {m.group(1)} expanding up to {m.group(2)}")

    # "slot with 5 columns, 7 rows" / "5 columns, 6 rows"
    if cols is None or rows is None:
        m = re.search(r"(\d+)\s*columns?,\s*(\d+)\s*rows?", text, re.I)
        if m:
            if cols is None:
                cols = int(m.group(1))
            if rows is None:
                rows = int(m.group(2))
            layout_notes_parts.append(f"Official help: {m.group(1)} columns, {m.group(2)} rows")
    if cols is None or rows is None:
        m = re.search(r"(\d+)\s*reels?\s+(\d+)\s*rows?", text, re.I)
        if m:
            if cols is None:
                cols = int(m.group(1))
            if rows is None:
                rows = int(m.group(2))
            layout_notes_parts.append(f"Official help: {m.group(1)} reels, {m.group(2)} rows")

    return {
        "rows": rows,
        "cols": cols,
        "rows_min": rows_min,
        "rows_max": rows_max,
        "layout_notes": "; ".join(layout_notes_parts) if layout_notes_parts else None,
    }


def parse_win_system(text: str, kf: dict) -> dict:
    lines = kf.get("lines") or ""
    blob = lines + "\n" + text[:3000]
    win_type = "unknown"
    payline_count = None
    ways_count = None
    min_symbols = None
    direction = None
    notes = lines or None

    if re.search(r"cluster", blob, re.I):
        win_type = "clusters"
        direction = "horizontal_or_vertical"
        m = re.search(r"(?:at least |minimum of |clusters? of )?(\d+)\s+or more", blob, re.I)
        if not m:
            m = re.search(r"(\d+)\s+or more (?:identical |connecting )?symbols", text, re.I)
        if m:
            min_symbols = int(m.group(1))
        notes = clean_ws(
            re.search(
                r"A winning cluster consists of[^.]+\.",
                text,
                re.I,
            ).group(0)
            if re.search(r"A winning cluster consists of[^.]+\.", text, re.I)
            else (lines or "Cluster wins")
        )
    elif re.search(r"scatter(?:ed)?\s*(?:win|pay|pays|symbols)|scatter pay", blob, re.I):
        win_type = "other"
        direction = None
        m = re.search(r"(\d+)\s+or more identical symbols", blob, re.I)
        if not m:
            m = re.search(r"(?:group|symbols) of (\d+)\s+or more", blob, re.I)
        if not m:
            m = re.search(r"Scattered symbols of (\d+)\s+or more", blob, re.I)
        if m:
            min_symbols = int(m.group(1))
        notes = clean_ws(lines or "Scatter pays (identical symbols anywhere on the grid)")
    elif re.search(r"Collector Wins|collector", lines, re.I) and re.search(
        r"collector", text[:2000], re.I
    ):
        win_type = "other"
        direction = None
        notes = lines or "Collector wins (path-to-collector)"
    elif re.search(r"poker hand|poker style", blob, re.I):
        win_type = "other"
        direction = None
        notes = lines or "Poker-hand evaluation"
    elif re.search(r"ways to win|all-?ways|all win ways|connecting win ways", blob, re.I):
        win_type = "ways"
        direction = "left_to_right"
        m = re.search(r"([\d,]+)\s*(?:ways to win|connecting win ways)", blob, re.I)
        if m:
            ways_count = int(m.group(1).replace(",", ""))
        m = re.search(r"Up to\s+([\d,]+)\s*ways", blob, re.I)
        if m:
            ways_count = int(m.group(1).replace(",", ""))
        notes = lines or "Ways to win"
    elif re.search(r"paylines?", blob, re.I):
        win_type = "paylines"
        direction = "left_to_right"
        m = re.search(r"(\d+)\s*paylines?", blob, re.I)
        if m:
            payline_count = int(m.group(1))

    return {
        "type": win_type,
        "payline_count": payline_count,
        "ways_count": ways_count,
        "min_symbols_for_win": min_symbols,
        "direction": direction,
        "notes": notes,
    }


def excerpt_around(text: str, pattern: str, radius: int = 350) -> str | None:
    m = re.search(pattern, text, re.I | re.S)
    if not m:
        return None
    start = max(0, m.start() - 80)
    end = min(len(text), m.end() + radius)
    return clean_ws(text[start:end])[:1200]


def parse_avalanche(text: str) -> dict:
    present = bool(
        re.search(r"Avalanche|explode|remaining symbols fall|new symbols drop", text, re.I)
    )
    how = None
    m = re.search(
        r"((?:All cluster wins|All wins|Symbol wins)[^.]*\.(?:[^.]*explode[^.]*\.)?(?:[^.]*(?:fall|Avalanche|drop in)[^.]+\.){1,4})",
        text,
        re.I | re.S,
    )
    if m:
        how = clean_ws(m.group(1))[:1500]
    else:
        how = excerpt_around(
            text,
            r"remaining symbols fall|Avalanche feature continues|new symbols drop in",
            400,
        )
    return {"present": present, "how_it_works": how}


def parse_xiter(text: str) -> tuple[dict, list[dict]]:
    """Return feature_buy dict and feature list entries for X-iter."""
    buy = {"available": False, "options": [], "notes": None}
    features = []
    if not re.search(r"X-iter", text, re.I):
        return buy, features

    buy["available"] = True
    # Split X-iter rules section
    m = re.search(r"X-iter rules(.+?)(?:Contact info:|\Z)", text, re.S | re.I)
    sec = m.group(1) if m else text
    # Modes: NAME: ... cost of Nx / Cost is Nx
    # Handle ALL CAPS headings
    mode_pat = re.compile(
        r"(?m)^(?:\s*)([A-Z][A-Z0-9][A-Z0-9 !']*(?:\s+[A-Z0-9 !']+)*)\s*:\s*(.+?)(?=(?:^[A-Z][A-Z0-9][A-Z0-9 !']*(?:\s+[A-Z0-9 !']+)*\s*:)|\Z)",
        re.S,
    )
    found = list(mode_pat.finditer(sec))
    if not found:
        # fallback: inline "Name: ... at the cost of Nx"
        for m in re.finditer(
            r"([A-Z][A-Za-z0-9][A-Za-z0-9 !']{1,40}):\s*(.+?(?:cost of|Cost is)\s*(?:[\d.]+|__X\d+_MULTIPLIER__)\s*(?:x|the selected bet)[^.]*\.)",
            sec,
            re.S,
        ):
            name = clean_ws(m.group(1)).title().replace("Bonus Hunt!", "Bonus Hunt")
            body = clean_ws(m.group(2))
            cm = re.search(r"(?:cost of|Cost is)\s*([\d.]+)\s*x", body, re.I)
            ph = re.search(r"(?:cost of|Cost is)\s*(__X\d+_MULTIPLIER__)", body, re.I)
            cost = float(cm.group(1)) if cm else None
            cost_text = (
                f"{cost:g}x the selected bet"
                if cost is not None
                else f"{ph.group(1)} the selected bet (runtime; not numeric in help XML)"
            )
            buy["options"].append(
                {
                    "name": name.rstrip("!"),
                    "cost_multiplier": cost,
                    "cost_text": cost_text,
                    "effects": body[:800],
                    "rtp_when_bought_note": None,
                }
            )
    else:
        for m in found:
            name = clean_ws(m.group(1))
            if name.lower() in {"the x-iter feature offers several different game modes"}:
                continue
            if len(name) > 40:
                continue
            body = clean_ws(m.group(2))
            cm = re.search(r"(?:cost of|Cost is)\s*([\d.]+)\s*x", body, re.I)
            ph = re.search(r"(?:cost of|Cost is)\s*(__X\d+_MULTIPLIER__)\s*(?:the selected bet)?", body, re.I)
            if cm:
                cost = float(cm.group(1))
                cost_text = f"{cost:g}x the selected bet"
            elif ph:
                cost = None
                cost_text = f"{ph.group(1)} the selected bet (runtime; not numeric in help XML)"
            else:
                continue
            nice = name.title().replace("Bonus Hunt!", "Bonus Hunt")
            buy["options"].append(
                {
                    "name": nice.rstrip("!"),
                    "cost_multiplier": cost,
                    "cost_text": cost_text,
                    "effects": body[:900],
                    "rtp_when_bought_note": None,
                }
            )

    # Also catch "Buy a game round ... Cost is Nx" patterns if options empty/thin
    if len(buy["options"]) < 2:
        for m in re.finditer(
            r"([A-Z][A-Za-z0-9 ']{2,30}):\s*(Buy a game round.+?Cost is\s*([\d.]+)\s*x[^.]*\.)",
            sec,
            re.S,
        ):
            name = clean_ws(m.group(1)).title()
            if any(o["name"].lower() == name.lower() for o in buy["options"]):
                continue
            buy["options"].append(
                {
                    "name": name.rstrip("!"),
                    "cost_multiplier": float(m.group(3)),
                    "cost_text": f"{float(m.group(3)):g}x the selected bet",
                    "effects": clean_ws(m.group(2))[:900],
                    "rtp_when_bought_note": None,
                }
            )

    # RTP note for X-iter
    m = re.search(
        r"theoretical payout \(RTP\) for all X-iter[^.]*([\d.]+)\s*%",
        text,
        re.I,
    )
    rtp_note = None
    if m:
        rtp_note = f"Theoretical RTP for all X-iter game modes is {m.group(1)}%"
        for o in buy["options"]:
            o["rtp_when_bought_note"] = rtp_note

    m = re.search(
        r"minimum X-iter cost is €\s*([\d.]+).*maximum (?:X-iter )?cost is €\s*([\d,.]+)",
        text,
        re.I | re.S,
    )
    notes = ["X-iter features can only be activated in the base game."]
    if m:
        notes.append(f"Min X-iter cost €{m.group(1)}, max €{m.group(2)}.")
    if rtp_note:
        notes.append(rtp_note)
    buy["notes"] = " ".join(notes)

    if buy["options"]:
        features.append(
            {
                "name": "X-iter",
                "trigger": "Player selects an X-iter mode in base game only",
                "when": "Base game only",
                "cost_text": buy["notes"],
                "effects": "; ".join(
                    (
                        f"{o['name']} ({o['cost_multiplier']:g}x): {o['effects'][:160]}"
                        if o.get("cost_multiplier") is not None
                        else f"{o['name']} ({o.get('cost_text') or 'cost n/a'}): {o['effects'][:160]}"
                    )
                    for o in buy["options"]
                )[:2000],
                "params": {"base_game_only": True, "mode_count": len(buy["options"])},
            }
        )
    return buy, features


def parse_bonus_modes(text: str, title: str) -> dict:
    modes = []
    # Common Elk pattern: N bonus symbols -> free drops/spins
    # Bonus
    trigger_bonus = None
    spins = None
    retrigger = None
    sticky = None

    if re.search(r"3 (?:or more )?bonus symbols", text, re.I):
        m = re.search(
            r"((?:3(?:\s+or more)?\s+bonus symbols)[^.]*trigger[^.]*\.)",
            text,
            re.I,
        )
        trigger_bonus = clean_ws(m.group(1)) if m else "3 or more bonus symbols trigger the bonus game"
    if re.search(r"bonus symbols? (?:that )?reaches?", text, re.I):
        m = re.search(r"(A bonus symbol that reaches[^.]*\.)", text, re.I)
        if m:
            trigger_bonus = clean_ws(m.group(1))

    m = re.search(
        r"(?:with|gets?|awards?|award)\s+(\d+)\s+(?:or more\s+)?free (?:drops|spins)",
        text,
        re.I,
    )
    if m:
        unit = "free drops" if re.search(r"free drops", text, re.I) else "free spins"
        spins = f"{m.group(1)} {unit}"
        if re.search(r"or more free", text, re.I):
            spins = f"{m.group(1)} or more {unit}"

    # more specific: "trigger the bonus mode with 5 free drops"
    m = re.search(
        r"trigger(?:s|ed)? the (?:bonus|free spins?)[^.]{0,40}?with\s+(\d+)\s+free (drops|spins)",
        text,
        re.I,
    )
    if m:
        spins = f"{m.group(1)} free {m.group(2)}"

    m = re.search(
        r"((?:Landing |additional )?free (?:drop|spin) symbols? award[^.]+\.|Free (?:drops|spins) can be retriggered[^.]*\.)",
        text,
        re.I,
    )
    if m:
        retrigger = clean_ws(m.group(1))

    sticky_bits = []
    for pat, lab in [
        (r"global multiplier is persistent between free drops", "Global multiplier persistent between free drops"),
        (r"Multiplier Wilds are sticky", "Multiplier Wilds sticky between free drops"),
        (r"Locked Wild[^.]*persistent", "Locked Wilds persistent over free drops"),
        (r"Win Multipliers? are persistent", "Win multipliers persistent over free drops"),
        (r"Nitro Reels are (?:sticky|persistent)", "Nitro Reels sticky/persistent during free spins"),
        (r"Numbers of collectors and the global multiplier are persistent", "Collectors count and global multiplier persistent"),
        (r"coins and Multiplier Wilds are sticky", "Coins and Multiplier Wilds sticky"),
    ]:
        if re.search(pat, text, re.I):
            sticky_bits.append(lab)
    sticky = "; ".join(sticky_bits) if sticky_bits else None

    end_cond = None
    m = re.search(
        r"((?:The )?(?:free drops?|bonus)[^.]{0,40}end(?:s| when)[^.]*\.)",
        text,
        re.I,
    )
    if m:
        end_cond = clean_ws(m.group(1))
    else:
        end_cond = "Ends when no free drops/spins remain or when the win cap has been reached."

    if trigger_bonus or spins:
        unit = "free drops" if "drop" in (spins or "free drops") else "free spins"
        modes.append(
            {
                "name": "Bonus",
                "trigger": trigger_bonus or "Bonus symbols trigger the bonus game (see PDF)",
                "spins_awarded": spins,
                "retrigger": retrigger,
                "sticky_or_persistent_state": sticky,
                "progressive_state": None,
                "effects": clean_ws(
                    (excerpt_around(text, r"bonus (?:game|mode) with free", 500) or "")[:1200]
                ),
                "end_condition": end_cond,
                "phases": [
                    {
                        "name": f"Start Bonus",
                        "order": 1,
                        "what_happens": f"Enter bonus; award {spins or unit}. "
                        + (f"Persistent state: {sticky}." if sticky else ""),
                        "ends_when": "First free drop/spin begins",
                        "state_changes": f"free_count set; sticky/persistent flags enabled",
                    },
                    {
                        "name": "Free drop/spin loop",
                        "order": 2,
                        "what_happens": "Play free drops/spins with base mechanics plus bonus-mode persistence/retriggers as described in Game rules.",
                        "ends_when": "No free drops/spins remain or win cap reached",
                        "state_changes": "free_count decremented; possible retriggers",
                    },
                    {
                        "name": "Settle",
                        "order": 3,
                        "what_happens": "Pay bonus-mode winnings at end of bonus (or immediately on win cap).",
                        "ends_when": "Payout complete",
                        "state_changes": "Return to base game",
                    },
                ],
                "award": spins,
            }
        )

    # Super bonus
    if re.search(r"super bonus", text, re.I):
        m = re.search(
            r"((?:1 Super bonus|super bonus symbol)[^.]{0,120}trigger[^.]{0,200}\.)",
            text,
            re.I,
        )
        trig = clean_ws(m.group(1)) if m else "Super bonus symbol combination triggers the super bonus game"
        effects = excerpt_around(text, r"super bonus game", 450) or trig
        modes.append(
            {
                "name": "Super Bonus",
                "trigger": trig,
                "spins_awarded": spins,
                "retrigger": retrigger,
                "sticky_or_persistent_state": sticky,
                "progressive_state": None,
                "effects": clean_ws(effects)[:1200],
                "end_condition": end_cond,
                "phases": [
                    {
                        "name": "Start Super Bonus",
                        "order": 1,
                        "what_happens": clean_ws(effects)[:400],
                        "ends_when": "Free drop/spin loop begins",
                        "state_changes": "Super bonus flags; often max grid / guaranteed features",
                    },
                    {
                        "name": "Free drop/spin loop",
                        "order": 2,
                        "what_happens": "Play free drops/spins under super-bonus rules.",
                        "ends_when": "No free drops/spins remain or win cap reached",
                        "state_changes": "State persists across free drops/spins",
                    },
                    {
                        "name": "Settle",
                        "order": 3,
                        "what_happens": "Pay winnings at end of bonus mode (or on win cap).",
                        "ends_when": "Payout complete",
                        "state_changes": "Return to base game",
                    },
                ],
                "award": spins,
            }
        )

    # Assassin spins etc. as extra mode
    if re.search(r"Assassin Spins", text, re.I):
        m = re.search(r"(Assassin Spins[^.]*\.(?:[^.]*\.){0,3})", text, re.I)
        modes.append(
            {
                "name": "Assassin Spins",
                "trigger": clean_ws(m.group(1))[:400] if m else "Assassin symbol covering Feature Reel",
                "spins_awarded": None,
                "retrigger": None,
                "sticky_or_persistent_state": None,
                "progressive_state": None,
                "effects": (excerpt_around(text, r"Assassin Spins", 500) or "")[:1200],
                "end_condition": None,
                "phases": [],
                "award": None,
            }
        )

    notes = None
    if modes:
        notes = f"{len(modes)} bonus mode(s) extracted from official Game Description for {title}."
    return {"modes": modes, "notes": notes}


def parse_symbols(text: str) -> dict:
    symbols = {"wilds": [], "scatters": [], "multipliers": [], "collectors": [], "specials": []}

    def add(bucket, name, behavior, params=None):
        if not behavior:
            return
        symbols[bucket].append({"name": name, "behavior": clean_ws(behavior)[:1200], "params": params or {}})

    # Wild
    m = re.search(
        r"(The wild symbols? substitutes? for any (?:paying )?symbol(?! except)[^.]*\.)",
        text,
        re.I,
    )
    if not m:
        m = re.search(
            r"(The wild symbol substitutes for any symbol except[^.]*\.)",
            text,
            re.I,
        )
    if m:
        add("wilds", "Wild", m.group(1))
    m = re.search(
        r"(The charged Wild symbol[^.]*\.(?:[^.]*\.){0,1})",
        text,
        re.I,
    )
    if m:
        add("wilds", "Charged Wild", m.group(1), {"charges": 3})
    m = re.search(
        r"(The multiplier wild symbol substitutes[^.]*\.(?:[^.]*multiplier[^.]*\.)?)",
        text,
        re.I,
    )
    if m:
        add("wilds", "Multiplier Wild", m.group(1))
        add("multipliers", "Multiplier Wild", m.group(1), {"role": "symbol_multiplier"})

    m = re.search(r"(The Locked Wild feature symbol[^.]*\.(?:[^.]*\.){0,2})", text, re.I)
    if m:
        add("wilds", "Locked Wild", m.group(1), {"charges": 3})

    # Bonus / scatter-like
    m = re.search(
        r"((?:Three or more|3 or more) bonus symbols trigger[^.]*\.)",
        text,
        re.I,
    )
    if m:
        add("scatters", "Bonus", m.group(1), {"trigger_threshold": 3})
    m = re.search(r"(The super bonus symbol[^.]*\.)", text, re.I)
    if m:
        add("scatters", "Super Bonus", m.group(1))

    # Collectors / birds / nitro etc as specials
    for name, pat in [
        ("Bomb", r"(The bomb symbol[^.]*\.(?:[^.]*\.){0,2})"),
        ("Nest", r"(The nest (?:symbol |allows)[^.]*\.(?:[^.]*\.){0,2})"),
        ("Feature Chest", r"(The feature chest[^.]*\.)"),
        ("Coin", r"(The Coin symbol[^.]*\.)"),
        ("Burst", r"(The burst symbol[^.]*\.(?:[^.]*\.){0,2})"),
        ("Nitro Reel", r"(A Nitro Reel[^.]*\.(?:[^.]*\.){0,2})"),
        ("Nitro Multiplier", r"(The Nitro Multiplier[^.]*\.)"),
        ("Nitro Booster", r"(The Nitro Booster[^.]*\.(?:[^.]*\.){0,2})"),
        ("Elmo", r"(The Elmo[^.]*\.(?:[^.]*\.){0,2})"),
        ("Mystery", r"(The Mystery symbols?[^.]*\.(?:[^.]*\.){0,1})"),
        ("Row Swap", r"(The Row Swap feature[^.]*\.(?:[^.]*\.){0,1})"),
        ("Loki", r"(A Loki symbol[^.]*\.(?:[^.]*\.){0,2})"),
        ("Odin's Ravens", r"(Odin.?s Ravens[^.]*\.(?:[^.]*\.){0,1})"),
        ("Thor Wild", r"(The Thor wild[^.]*\.)"),
        ("Spike", r"(Spike symbols[^.]*\.(?:[^.]*\.){0,1})"),
        ("Global Multiplier", r"(The global multiplier[^.]*\.(?:[^.]*\.){0,2})"),
    ]:
        m = re.search(pat, text, re.I)
        if m:
            bucket = "multipliers" if "Multiplier" in name or name == "Global Multiplier" else "specials"
            if name in {"Nitro Multiplier", "Global Multiplier"}:
                bucket = "multipliers"
            add(bucket, name, m.group(1))

    # Collectors (Slurpy / bird collection)
    if re.search(r"collector", text, re.I):
        m = re.search(r"((?:The game consists of|starts with one) collector[^.]*\.(?:[^.]*\.){0,3})", text, re.I)
        if m:
            add("collectors", "Collector", m.group(1))
    if re.search(r"birds can collect", text, re.I):
        m = re.search(r"(From the (?:game )?grid, the birds can collect[^.]*\.(?:[^.]*\.){0,2})", text, re.I)
        if m:
            add("collectors", "Pirot bird collection", m.group(1))

    return symbols


def build_features(text: str, avalanche: dict, xiter_feats: list) -> list:
    feats = []
    if avalanche["present"]:
        feats.append(
            {
                "name": "Avalanche",
                "trigger": "After wins in a drop",
                "when": "Throughout base and bonus",
                "effects": avalanche["how_it_works"] or "Winning symbols removed; remaining fall; new symbols drop in.",
                "params": {"provider_name": "Avalanche"},
            }
        )
    # Expanding grid
    if re.search(r"expand", text, re.I):
        ex = excerpt_around(text, r"expand(?:s|ing|ed)? up to", 200)
        if ex:
            feats.append(
                {
                    "name": "Expanding grid",
                    "trigger": "Feature/bomb/clear-board events as described",
                    "when": "Base and bonus",
                    "effects": ex,
                    "params": {},
                }
            )
    # Named features
    for name, pat in [
        ("Feature Release", r"feature release"),
        ("Big Drop", r"big drop is triggered"),
        ("Bomb", r"bomb feature releases"),
        ("Nitro Booster", r"Nitro Booster"),
        ("NPD Holding Cell", r"NPD Holding Cell"),
        ("Elmo's Revenge", r"Elmo.?s Revenge"),
        ("Second chance", r"second chance feature"),
        ("Spike replication", r"Spike symbols replicate"),
        ("Loki's inventory", r"Loki.?s inventory"),
    ]:
        if re.search(pat, text, re.I):
            feats.append(
                {
                    "name": name,
                    "trigger": None,
                    "when": None,
                    "effects": excerpt_around(text, pat, 350) or name,
                    "params": {},
                }
            )
    feats.extend(xiter_feats)
    return feats


def build_base_loop(title: str, text: str, grid: dict, win: dict, avalanche: dict, bonus: dict) -> dict:
    rows = grid.get("rows")
    cols = grid.get("cols")
    grid_desc = f"{rows}x{cols}" if rows and cols else "the grid"
    if grid.get("rows_max"):
        grid_desc += f" (expands to {grid['rows_max']} rows)"

    win_desc = win.get("notes") or win.get("type")
    phases = [
        {
            "name": "Place bet and spin",
            "order": 1,
            "what_happens": "Player selects bet and hits Spin (or Auto Spin). Optional: activate an X-iter mode from base game only before the drop/spin.",
            "ends_when": "Spin committed",
            "state_changes": "Bet locked; optional X-iter mode selected",
        },
        {
            "name": "Initial symbol drop/spin",
            "order": 2,
            "what_happens": f"Symbols land on {grid_desc}. Game-specific setup features may fire (birds, Nitro/COOL reels, collectors, etc.).",
            "ends_when": "All symbols at resting positions / reels stopped",
            "state_changes": "Grid filled",
        },
        {
            "name": "Evaluate wins",
            "order": 3,
            "what_happens": f"Evaluate wins: {win_desc}",
            "ends_when": "Current-drop wins collected (or none)",
            "state_changes": "Win amounts staged",
        },
    ]
    if avalanche["present"]:
        phases.append(
            {
                "name": "Remove winners and Avalanche",
                "order": 4,
                "what_happens": avalanche["how_it_works"]
                or "Winning symbols explode/are removed; remaining symbols fall; new symbols drop in. Continues while new wins appear.",
                "ends_when": "No new winning combinations after a fill",
                "state_changes": "Grid updated; avalanche chain may continue",
            }
        )
    phases.append(
        {
            "name": "End-of-drop features",
            "order": len(phases) + 1,
            "what_happens": "Resolve end-of-round features (bombs, mystery reveals, row swaps, boosters, etc.) if nothing else can happen; may resume avalanches.",
            "ends_when": "No further features/wins",
            "state_changes": "Possible new symbols / expansions",
        }
    )
    phases.append(
        {
            "name": "Bonus trigger check",
            "order": len(phases) + 1,
            "what_happens": (
                "If bonus/super-bonus trigger conditions met, enter bonus mode after resolving same-drop features. "
                "Otherwise settle base-game wins subject to win cap."
            ),
            "ends_when": "Bonus entered or round complete",
            "state_changes": "Enter bonus mode or settle base round",
        }
    )

    summary = (
        f"{title}: paid spin on {grid_desc}. {win_desc}. "
        + ("Avalanche/tumble after wins. " if avalanche["present"] else "")
        + (f"Bonus modes: {', '.join(m['name'] for m in bonus.get('modes', []))}. " if bonus.get("modes") else "")
        + "Round ends on win cap if reached."
    )
    return {
        "summary": clean_ws(summary)[:1500],
        "phases": phases,
        "win_evaluation": win_desc,
        "notes": excerpt_around(text, r"played in two modes|is played in", 200),
    }


def confidence_block(grid, win, bonus, buy, symbols) -> dict:
    def h(ok):
        return "high" if ok else "medium"

    return {
        "overall": "high",
        "grid": h(grid.get("rows") and grid.get("cols")),
        "win_system": h(win.get("type") not in (None, "unknown")),
        "reel_behavior": "high",
        "symbols": h(any(symbols.values())),
        "bonus_free_spins": h(bool(bonus.get("modes"))),
        "features": "high",
        "feature_buy": h(buy.get("available") and buy.get("options")),
        "numeric_limits": "high",
        "base_game_loop": "high",
    }



def gamerules_xml_to_text(xml_path: Path, title: str) -> tuple[str, dict]:
    """Convert official client gamerules XML into PDF-like Game Description text."""
    root = ET.parse(xml_path).getroot()
    by: dict[str, list[str]] = {}
    gfx: dict[str, str] = {}
    for e in root.iter():
        if e.tag == "entry":
            k = e.get("key") or ""
            v = (e.text or "").strip()
            if v:
                by.setdefault(k, []).append(v)
        elif e.tag == "gfx":
            k = e.get("key") or ""
            v = (e.text or "").strip()
            if k and v:
                gfx[k] = v

    lines: list[str] = []
    lines.append("Key features")
    lines.append(f"Name in English {title}")
    lines.append("Product category Casino")
    lines.append("Game type Slot")
    lines.append("Client HTML5")
    if by.get("gdd-kf-lines"):
        lines.append(f"Lines {by['gdd-kf-lines'][0]}")
    if by.get("gdd-kf-jackpot"):
        lines.append(f"Jackpot {by['gdd-kf-jackpot'][0]}")
    if by.get("gdd-kf-reels"):
        lines.append(f"Reels {by['gdd-kf-reels'][0]}")
    if by.get("gdd-kf-rows"):
        lines.append(f"Rows {by['gdd-kf-rows'][0]}")

    maxwin = None
    for v in list(gfx.values()) + [x for vs in by.values() for x in vs]:
        m = re.search(r"WIN UP TO\s+([\d,\.]+)\s*x", v, re.I)
        if m:
            maxwin = float(m.group(1).replace(",", ""))
            break
    if maxwin:
        lines.append(f"Max exposure {int(maxwin) if maxwin == int(maxwin) else maxwin} x")
        lines.append(f"Max win single spin {int(maxwin) if maxwin == int(maxwin) else maxwin} x")

    lines.append("")
    lines.append("Game description")
    for key in ("gdd-description", "gdd-payline", "gdd-bonusgame", "gdd-gameview"):
        for v in by.get(key, []):
            lines.append(v)
    for i in range(1, 30):
        for v in by.get(f"gdd-sfs-{i}", []):
            lines.append(v)

    lines.append("")
    lines.append("Game rules")
    for v in by.get("gamerule", []):
        # Drop pure placeholder RTP lines noise? keep — parsers may use structure
        lines.append(v)

    lines.append("")
    lines.append("X-iter rules")
    for v in by.get("xiter-rule", []):
        lines.append(v)

    # Paytable / Txt feature blurbs
    for k, vals in by.items():
        if k.startswith("paytable") or k.startswith("Txt"):
            for v in vals:
                if len(v) > 40:
                    lines.append(v)

    meta = {"maxwin": maxwin, "gfx": gfx, "entry_keys": sorted(by.keys())}
    return "\n".join(lines), meta


def build_record_from_text(
    slug: str,
    meta: dict,
    text: str,
    *,
    source_url: str,
    local_path: str,
    source_type: str = "official_demo_rules",
) -> dict | None:
    text = flatten(text)
    if sum(c.isalpha() for c in text) < 800:
        return None

    kf = parse_key_features(text)
    gid = meta["id"]
    title = meta["title"]
    if kf.get("name") and len(kf["name"]) < 80 and not kf["name"].lower().startswith("reels"):
        title = kf["name"]

    grid = parse_grid(text, kf)
    win = parse_win_system(text, kf)
    avalanche = parse_avalanche(text)
    expanding_present = bool(re.search(r"expand", text, re.I))
    symbols = parse_symbols(text)
    bonus = parse_bonus_modes(text, title)
    buy, xiter_feats = parse_xiter(text)
    features = build_features(text, avalanche, xiter_feats)
    base_loop = build_base_loop(title, text, grid, win, avalanche, bonus)

    max_win = kf.get("max_win_spin") or kf.get("max_exposure")
    rtp = kf.get("rtp")
    if rtp is None:
        m = re.search(r"theoretical payout \(RTP\).*?([\d.]+)\s*%", text, re.I)
        if m:
            rtp = float(m.group(1))

    evidence = []
    for pat in [
        r"Key features[\s\S]{0,600}",
        r"(?:is a \d+[^.]*\.(?:[^.]*\.){0,2})",
        r"X-iter rules[\s\S]{0,700}",
        r"Game description[\s\S]{0,800}",
    ]:
        m = re.search(pat, text, re.I)
        if m:
            evidence.append(
                {
                    "source_type": source_type,
                    "url": source_url,
                    "local_path": local_path,
                    "extracted_at": EXTRACTED_AT,
                    "quote_or_excerpt": clean_ws(m.group(0))[:1200],
                }
            )
    evidence.append(
        {
            "source_type": source_type,
            "url": source_url,
            "local_path": local_path,
            "extracted_at": EXTRACTED_AT,
            "quote_or_excerpt": clean_ws(text[:900]),
        }
    )
    evidence.append(
        {
            "source_type": "provider_marketing",
            "url": meta.get("page_url"),
            "local_path": None,
            "extracted_at": EXTRACTED_AT,
            "quote_or_excerpt": f"Demo launcher gameid={gid}; mechanics taken from official client gamerules XML / Game Description, not marketing copy.",
        }
    )

    unknowns = []
    if not grid.get("rows") or not grid.get("cols"):
        unknowns.append("grid.rows/cols incomplete")
    if win.get("type") == "unknown":
        unknowns.append("win_system.type")
    if not bonus.get("modes"):
        unknowns.append("bonus_free_spins.modes")
    if buy.get("available") and not buy.get("options"):
        unknowns.append("feature_buy.options incomplete")
    if buy.get("available") and buy.get("options") and any(o.get("cost_multiplier") is None for o in buy["options"]):
        unknowns.append("feature_buy option cost multipliers are runtime placeholders in help XML")
    if rtp is None:
        unknowns.append("rtp_percent not numeric in help XML (placeholder __RTP__)")
    if max_win is None:
        unknowns.append("max_win_multiplier not numeric in help XML (placeholder __TBB__ or image asset)")
    unknowns.append("Exact paytable symbol values not in help text extract")
    unknowns.append("release_year not stated in official help text")

    conf = confidence_block(grid, win, bonus, buy, symbols)
    if rtp is None or max_win is None:
        conf["numeric_limits"] = "medium"
    if buy.get("available") and (
        not buy.get("options") or any(o.get("cost_multiplier") is None for o in buy["options"])
    ):
        conf["feature_buy"] = "medium"

    thumb = f"thumbs/elk-{slug}.webp"
    rec = {
        "schema_version": "1.1.0",
        "updated_at": EXTRACTED_AT,
        "identity": {
            "provider": "Elk Studios",
            "title": title,
            "slug": f"elk-{slug}",
            "provider_game_id": gid,
            "release_year": None,
            "demo_url": meta.get("demo_url"),
            "slotcatalog_url": None,
            "official_info_url": source_url,
        },
        "grid": grid,
        "win_system": win,
        "reel_behavior": {
            "cascades_or_tumbles": avalanche,
            "respins": {
                "present": bool(re.search(r"\brespin", text, re.I)),
                "how_it_works": excerpt_around(text, r"\brespin", 250),
            },
            "expanding_reels": {
                "present": expanding_present,
                "how_it_works": excerpt_around(text, r"expand(?:s|ing|ed)? up to", 250),
            },
            "other": [],
        },
        "symbols": symbols,
        "base_game_loop": base_loop,
        "bonus_free_spins": bonus,
        "features": features,
        "feature_buy": buy,
        "ante_bet": {
            "available": False,
            "cost_multiplier": None,
            "effects": None,
            "notes": "No ante bet stated in official help; X-iter covers paid feature entry when present.",
        },
        "numeric_limits": {
            "max_win_multiplier": max_win,
            "max_win_notes": clean_ws(
                f"Max exposure {kf.get('max_exposure')}x; max win single spin {kf.get('max_win_spin')}x; "
                f"Maximum win €{kf.get('maximum_win_eur')}"
            )
            if max_win
            else "Max win uses runtime placeholder (__TBB__) in help XML; numeric value not extracted.",
            "rtp_percent": rtp,
            "rtp_notes": f"Theoretical RTP {rtp}% (base and X-iter when stated). Min bet €{kf.get('min_bet')}, max bet €{kf.get('max_bet')}."
            if rtp
            else "RTP is a runtime placeholder (__RTP__) in help XML; not stored as a numeric value.",
            "hit_frequency_notes": f"Hit frequency {kf['hit_frequency']}% (official key features table)"
            if kf.get("hit_frequency")
            else None,
        },
        "confidence": conf,
        "evidence": evidence,
        "unknowns": unknowns,
        "thumbnail": thumb,
        "thumbnail_attribution": "ELK Studios",
    }
    return rec


def fetch_thumb(slug: str, meta: dict) -> bool:
    """Download provider logo/thumb into thumbs/elk-{slug}.webp."""
    THUMBS.mkdir(parents=True, exist_ok=True)
    dest = THUMBS / f"elk-{slug}.webp"
    if dest.exists() and dest.stat().st_size > 1000:
        return True
    url = meta.get("thumb_url")
    if not url:
        return False
    try:
        from io import BytesIO
        from PIL import Image

        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=30).read()
        im = Image.open(BytesIO(data)).convert("RGBA")
        w, h = im.size
        if w > 640:
            im = im.resize((640, int(h * 640 / w)), Image.Resampling.LANCZOS)
        im.save(dest, "WEBP", quality=85)
        return dest.exists()
    except Exception as e:
        print(f"thumb fail {slug}: {e}")
        return False


def quality_ok(rec: dict) -> tuple[bool, str]:
    if not rec["grid"].get("rows") or not rec["grid"].get("cols"):
        return False, "incomplete grid"
    if rec["win_system"]["type"] == "unknown":
        return False, "unknown win system"
    if len(rec["base_game_loop"]["phases"]) < 3:
        return False, "thin base loop"
    # Prefer rebuildable bonus when help mentions free drops/spins
    return True, "ok"


def build_record(slug: str, meta: dict, pdf_path: Path, txt_path: Path) -> dict | None:
    text = flatten(txt_path.read_text(errors="replace"))
    if sum(c.isalpha() for c in text) < 800:
        return None

    kf = parse_key_features(text)
    gid = meta["id"]
    title = meta["title"]
    # Prefer official name from PDF if present
    if kf.get("name"):
        title = kf["name"]

    pdf_url = CDN + urllib.parse.quote(pdf_path.name, safe="-_.")
    grid = parse_grid(text, kf)
    win = parse_win_system(text, kf)
    avalanche = parse_avalanche(text)
    expanding_present = bool(re.search(r"expand", text, re.I))
    symbols = parse_symbols(text)
    bonus = parse_bonus_modes(text, title)
    buy, xiter_feats = parse_xiter(text)
    features = build_features(text, avalanche, xiter_feats)
    base_loop = build_base_loop(title, text, grid, win, avalanche, bonus)

    max_win = kf.get("max_win_spin") or kf.get("max_exposure")
    rtp = kf.get("rtp")
    if rtp is None:
        m = re.search(r"theoretical payout \(RTP\).*?([\d.]+)\s*%", text, re.I)
        if m:
            rtp = float(m.group(1))

    # Evidence excerpts
    evidence = []
    for pat in [
        r"Key features[\s\S]{0,600}",
        r"(?:is a \d+[^.]*\.(?:[^.]*\.){0,2})",
        r"X-iter rules[\s\S]{0,700}",
    ]:
        m = re.search(pat, text, re.I)
        if m:
            evidence.append(
                {
                    "source_type": "official_pdf",
                    "url": pdf_url,
                    "local_path": str(txt_path.relative_to(ROOT)),
                    "extracted_at": EXTRACTED_AT,
                    "quote_or_excerpt": clean_ws(m.group(0))[:1200],
                }
            )
    evidence.append(
        {
            "source_type": "official_pdf",
            "url": pdf_url,
            "local_path": str(pdf_path.relative_to(ROOT)),
            "extracted_at": EXTRACTED_AT,
            "quote_or_excerpt": clean_ws(text[text.find("Game rules") : text.find("Game rules") + 900])
            if "Game rules" in text
            else clean_ws(text[:900]),
        }
    )
    evidence.append(
        {
            "source_type": "provider_marketing",
            "url": meta.get("page_url"),
            "local_path": None,
            "extracted_at": EXTRACTED_AT,
            "quote_or_excerpt": f"Demo launcher gameid={gid}; mechanics taken from Game Description PDF, not marketing copy.",
        }
    )

    unknowns = []
    if not grid.get("rows") or not grid.get("cols"):
        unknowns.append("grid.rows/cols incomplete")
    if win.get("type") == "unknown":
        unknowns.append("win_system.type")
    if not bonus.get("modes"):
        unknowns.append("bonus_free_spins.modes")
    if buy.get("available") and not buy.get("options"):
        unknowns.append("feature_buy.options incomplete")
    unknowns.append("Exact paytable symbol values (PDF references paytable; numeric paytable not in text extract)")
    unknowns.append("release_year not stated in Game Description PDF")

    thumb = f"thumbs/elk-{slug}.webp"
    rec = {
        "schema_version": "1.1.0",
        "updated_at": EXTRACTED_AT,
        "identity": {
            "provider": "Elk Studios",
            "title": title,
            "slug": f"elk-{slug}",
            "provider_game_id": gid,
            "release_year": None,
            "demo_url": meta.get("demo_url"),
            "slotcatalog_url": None,
            "official_info_url": pdf_url,
        },
        "grid": grid,
        "win_system": win,
        "reel_behavior": {
            "cascades_or_tumbles": avalanche,
            "respins": {
                "present": bool(re.search(r"\brespin", text, re.I)),
                "how_it_works": excerpt_around(text, r"\brespin", 250),
            },
            "expanding_reels": {
                "present": expanding_present,
                "how_it_works": excerpt_around(text, r"expand(?:s|ing|ed)? up to", 250),
            },
            "other": [],
        },
        "symbols": symbols,
        "base_game_loop": base_loop,
        "bonus_free_spins": bonus,
        "features": features,
        "feature_buy": buy,
        "ante_bet": {
            "available": False,
            "cost_multiplier": None,
            "effects": None,
            "notes": "No ante bet stated in the official Game Description; X-iter covers paid feature entry.",
        },
        "numeric_limits": {
            "max_win_multiplier": max_win,
            "max_win_notes": clean_ws(
                f"Max exposure {kf.get('max_exposure')}x; max win single spin {kf.get('max_win_spin')}x; "
                f"Maximum win €{kf.get('maximum_win_eur')}"
            )
            if max_win
            else None,
            "rtp_percent": rtp,
            "rtp_notes": f"Theoretical RTP {rtp}% (base and X-iter when stated). Min bet €{kf.get('min_bet')}, max bet €{kf.get('max_bet')}."
            if rtp
            else None,
            "hit_frequency_notes": f"Hit frequency {kf['hit_frequency']}% (official key features table)"
            if kf.get("hit_frequency")
            else None,
        },
        "confidence": confidence_block(grid, win, bonus, buy, symbols),
        "evidence": evidence,
        "unknowns": unknowns,
        "thumbnail": thumb,
        "thumbnail_attribution": "ELK Studios",
    }
    return rec


def main():
    TXT_DIR.mkdir(parents=True, exist_ok=True)
    GAMERULES_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    skipped = []
    thumbs_ok = 0

    existing = {p.name for p in GAMES.glob("elk-*.json")}

    # --- PDF path (existing) ---
    for pdf in sorted(PDF_DIR.glob("*.pdf")):
        m = re.match(r"(\d+)-", pdf.name)
        if not m:
            skipped.append({"pdf": pdf.name, "reason": "no id prefix"})
            continue
        gid = m.group(1)
        slug = ID_TO_SLUG.get(gid)
        if not slug:
            skipped.append({"pdf": pdf.name, "reason": f"no slug for id {gid}"})
            continue
        out_name = f"elk-{slug}.json"
        if out_name in existing or slug in SKIP_SLUGS:
            skipped.append({"pdf": pdf.name, "reason": "skip existing", "slug": slug})
            continue
        txt = TXT_DIR / (pdf.stem + ".txt")
        if not txt.exists():
            skipped.append({"pdf": pdf.name, "reason": "missing txt"})
            continue
        meta = SLUG_MAP[slug]
        rec = build_record(slug, meta, pdf, txt)
        if not rec:
            skipped.append({"pdf": pdf.name, "reason": "thin text"})
            continue
        ok, reason = quality_ok(rec)
        if not ok:
            skipped.append({"pdf": pdf.name, "reason": reason, "slug": slug})
            continue
        out = GAMES / out_name
        out.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")
        written.append(slug)
        existing.add(out_name)
        if fetch_thumb(slug, meta):
            thumbs_ok += 1
        print(f"wrote elk-{slug}.json (pdf)")

    # --- Official client gamerules XML path ---
    fetch_log_path = ROOT / "sources" / "elk" / "gamerules_fetch_log.json"
    gr_items = []
    if fetch_log_path.exists():
        gr_items = json.loads(fetch_log_path.read_text()).get("ok", [])

    for item in gr_items:
        if not item.get("ok"):
            continue
        # Prefer primary slug (first)
        slug = item["slugs"][0]
        # Prefer canonical when multiple
        for cand in item["slugs"]:
            if cand in SLUG_MAP and not cand.endswith("-mobile") and "html5" not in cand:
                slug = cand
                break
        out_name = f"elk-{slug}.json"
        if out_name in existing or slug in SKIP_SLUGS:
            skipped.append({"gamerules": item.get("path"), "reason": "skip existing", "slug": slug})
            continue
        # Quality prefilter: need substantial rules text
        if item.get("alpha", 0) < 800 or item.get("gamerule_count", 0) < 5:
            skipped.append({"gamerules": item.get("path"), "reason": "thin gamerules", "slug": slug,
                            "alpha": item.get("alpha"), "gamerule_count": item.get("gamerule_count")})
            continue
        xml_path = ROOT / item["path"]
        if not xml_path.exists():
            skipped.append({"gamerules": item.get("path"), "reason": "missing xml", "slug": slug})
            continue
        meta = SLUG_MAP[slug]
        title = meta["title"]
        text_body, gr_meta = gamerules_xml_to_text(xml_path, title)
        # Persist derived text for evidence/debug
        txt_path = TXT_DIR / f"{item['id']}-{item['gamename']}-gamerules-en_gb.txt"
        txt_path.write_text(text_body)
        rec = build_record_from_text(
            slug,
            meta,
            text_body,
            source_url=item["url"],
            local_path=str(xml_path.relative_to(ROOT)),
            source_type="official_demo_rules",
        )
        if not rec:
            skipped.append({"gamerules": item.get("path"), "reason": "thin text after convert", "slug": slug})
            continue
        # Inject maxwin from gfx meta if key features missed it
        if rec["numeric_limits"]["max_win_multiplier"] is None and gr_meta.get("maxwin"):
            rec["numeric_limits"]["max_win_multiplier"] = gr_meta["maxwin"]
            rec["numeric_limits"]["max_win_notes"] = f"From official help gfx WIN UP TO {gr_meta['maxwin']:g}x YOUR BET"
            if rec["confidence"]["numeric_limits"] == "medium" and rec["numeric_limits"].get("rtp_percent"):
                rec["confidence"]["numeric_limits"] = "high"
            elif rec["numeric_limits"]["max_win_multiplier"] and not rec["numeric_limits"].get("rtp_percent"):
                rec["confidence"]["numeric_limits"] = "medium"
        ok, reason = quality_ok(rec)
        if not ok:
            skipped.append({"gamerules": item.get("path"), "reason": reason, "slug": slug})
            continue
        out = GAMES / out_name
        out.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")
        written.append(slug)
        existing.add(out_name)
        if fetch_thumb(slug, meta):
            thumbs_ok += 1
        print(f"wrote elk-{slug}.json (gamerules)")

    report = {
        "written": sorted(written),
        "skipped_sample": skipped[:40],
        "skipped_count": len(skipped),
        "count": len(written),
        "thumbs": thumbs_ok,
        "source": "pdf+gamerules_xml",
    }
    (ROOT / "sources" / "elk" / "parse_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("count", "thumbs", "written", "skipped_count")}, indent=2))


if __name__ == "__main__":
    main()
