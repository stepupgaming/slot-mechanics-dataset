#!/usr/bin/env python3
"""Parse Slotmill official game pages into schema 1.1 records + thumbs."""
from __future__ import annotations

import html as HTML
import json
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
GAMES = ROOT / "games"
SOURCES = ROOT / "sources" / "slotmill"
THUMBS = ROOT / "thumbs"
CMS_BASE = "https://cms.slotmill.com"
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*",
}
EXTRACTED_AT = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# Official studio boilerplate (appears on most Slotmill marketing pages)
BURST_EFFECTS = (
    "Burst Mode functions as an enhanced auto-play, completing two game rounds per second."
)
FAST_TRACK_EFFECTS = (
    "Fast Track provides players with the option to access the games' bonus features directly."
)
XTRA_BET_EFFECTS = (
    "Xtra-Bet enables players to augment their bets, thereby increasing their chances "
    "of winning a bonus round."
)


def http_get(url: str, timeout: float = 45) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def plain_from_html(html: str) -> str:
    t = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.S | re.I)
    t = re.sub(r"<style[^>]*>.*?</style>", " ", t, flags=re.S | re.I)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"</(p|div|li|h\d|tr)>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = HTML.unescape(t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    return t.strip()


def extract_specs(html: str) -> dict[str, str]:
    """Pull label/value pairs from specsWrapper blocks."""
    specs: dict[str, str] = {}
    for m in re.finditer(
        r'class="[^"]*specs[^"]*"[^>]*>\s*'
        r"<span[^>]*>(.*?)</span>\s*"
        r"(?:<div[^>]*>)?(.*?)(?:</div>)?\s*</div>",
        html,
        re.S | re.I,
    ):
        label = re.sub(r"<[^>]+>", "", m.group(1))
        label = HTML.unescape(label).strip()
        label = re.sub(r"\s+", " ", label)
        val_html = m.group(2)
        parts = re.findall(r"<span[^>]*>(.*?)</span>", val_html, re.S | re.I)
        if parts:
            val = " | ".join(
                HTML.unescape(re.sub(r"<[^>]+>", "", p)).strip() for p in parts if p.strip()
            )
        else:
            val = HTML.unescape(re.sub(r"<[^>]+>", " ", val_html))
            val = re.sub(r"\s+", " ", val).strip()
        val = val.replace("<!-- -->", "").strip()
        if label and val and label not in specs:
            specs[label] = val
    return specs


def extract_description(html: str) -> str:
    m = re.search(
        r'id="game-description"[^>]*>(.*?)</div>\s*<div class="[^"]*clientArea',
        html,
        re.S | re.I,
    )
    if not m:
        m = re.search(r'id="game-description"[^>]*>(.*?)</div>', html, re.S | re.I)
    if not m:
        return ""
    paras = re.findall(r"<p[^>]*>(.*?)</p>", m.group(1), re.S | re.I)
    texts = []
    for p in paras:
        t = HTML.unescape(re.sub(r"<[^>]+>", " ", p))
        t = re.sub(r"\s+", " ", t).strip()
        if t and "Contact us at" not in t:
            texts.append(t)
    return "\n\n".join(texts)


def extract_og_image(html: str) -> str | None:
    m = re.search(
        r'property=["\']og:image["\']\s+content=["\']([^"\']+)|'
        r'content=["\']([^"\']+)["\']\s+property=["\']og:image["\']',
        html,
        re.I,
    )
    if m:
        return m.group(1) or m.group(2)
    return None


def extract_product_sheet_url(html: str) -> str | None:
    """Find CMS product sheet PDF path in Next.js flight / HTML."""
    # Prefer productSheetPdf nested url
    m = re.search(
        r'productSheetPdf\\?":\s*\\?\{[^}]{0,800}?\\?"url\\?":\\?"(/uploads/[^"\\]+\.pdf)',
        html,
    )
    if m:
        return CMS_BASE + m.group(1).replace("\\/", "/")
    m = re.search(r'(/uploads/product_sheet_[^"\'\\\s]+\.pdf)', html, re.I)
    if m:
        return CMS_BASE + m.group(1).replace("\\/", "/")
    m = re.search(r'(https://cms\.slotmill\.com/uploads/[^"\'\\\s]+\.pdf)', html, re.I)
    if m:
        return m.group(1).replace("\\/", "/")
    return None


def extract_next_game_details(html: str) -> dict | None:
    """Best-effort extract of gameDetails from escaped Next.js flight payload."""
    # Unescape common JS-string escapes inside push payloads for regex search
    # Look for gameDetails block with escaped quotes
    patterns = [
        r'"gameDetails":(\{(?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*\})',
        r'\\"gameDetails\\":(\{(?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*\})',
    ]
    # Simpler: find start after unescaping chunks
    for chunk_m in re.finditer(r'self\.__next_f\.push\(\[1,"((?:\\.|[^"\\])*)"\]\)', html):
        raw = chunk_m.group(1)
        try:
            # Decode the JS string content
            decoded = raw.encode("utf-8").decode("unicode_escape")
        except Exception:
            decoded = (
                raw.replace('\\"', '"')
                .replace("\\/", "/")
                .replace("\\n", "\n")
                .replace("\\\\", "\\")
            )
        if '"gameDetails"' not in decoded and "gameDetails" not in decoded:
            continue
        start = decoded.find('"gameDetails":')
        if start < 0:
            start = decoded.find("gameDetails")
            if start < 0:
                continue
            # find colon brace
            brace = decoded.find("{", start)
        else:
            brace = decoded.find("{", start)
        if brace < 0:
            continue
        depth = 0
        for j, c in enumerate(decoded[brace:], brace):
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(decoded[brace : j + 1])
                    except json.JSONDecodeError:
                        break
    return None


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.replace("\n", " "))
    return [p.strip() for p in parts if p.strip()]


def find_sentence(text: str, *needles: str) -> str | None:
    tl = text.lower()
    for n in needles:
        if n.lower() not in tl:
            continue
        for s in sentences(text):
            if n.lower() in s.lower():
                return s.strip()
    return None


def parse_grid(game_type: str) -> tuple[int | None, int | None, str | None]:
    gt = game_type or ""
    m = re.search(r"(\d+)\s*[xX×]\s*(\d+)", gt)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        # Slotmill writes cols x rows (5x5, 5x3)
        return b, a, f"Game Type: {game_type}"
    # e.g. "5-reel 5-row Video Slot"
    m = re.search(r"(\d+)\s*-\s*reel\s+(\d+)\s*-\s*row", gt, re.I)
    if m:
        cols, rows = int(m.group(1)), int(m.group(2))
        return rows, cols, f"Game Type: {game_type}"
    m = re.search(r"(\d+)\s*reels?\s*[x×,]?\s*(\d+)\s*rows?", gt, re.I)
    if m:
        cols, rows = int(m.group(1)), int(m.group(2))
        return rows, cols, f"Game Type: {game_type}"
    return None, None, game_type or None


def parse_win_system(paylines: str) -> dict:
    p = (paylines or "").lower()
    notes = f"Official Paylines field: {paylines}" if paylines else None
    min_sym = None
    m_min = re.search(r"(\d+)\s*\+\s*cluster", p)
    if m_min:
        min_sym = int(m_min.group(1))
    if "cluster" in p:
        return {
            "type": "clusters",
            "payline_count": None,
            "ways_count": None,
            "min_symbols_for_win": min_sym,
            "direction": None,
            "notes": notes,
        }
    if "matching symbol" in p or "pay anywhere" in p or p.strip() == "matching symbols":
        return {
            "type": "pay_anywhere",
            "payline_count": None,
            "ways_count": None,
            "min_symbols_for_win": None,
            "direction": None,
            "notes": notes,
        }
    if "ways" in p or "megaways" in p or "betway" in p:
        # Prefer the larger/expanded ways count when range like "2000 -> 5488"
        nums = [int(x.replace(",", "")) for x in re.findall(r"([\d,]+)", paylines or "")]
        ways = max(nums) if nums else None
        wm = re.search(r"([\d,]+)\s*ways", p)
        if wm:
            ways = int(wm.group(1).replace(",", ""))
        return {
            "type": "ways",
            "payline_count": None,
            "ways_count": ways,
            "min_symbols_for_win": None,
            "direction": None,
            "notes": notes,
        }
    m = re.search(r"(\d+)\s*(?:-|–)?\s*(?:fixed|bet\s*lines?)?", paylines or "", re.I)
    if m and "cluster" not in p:
        return {
            "type": "paylines",
            "payline_count": int(m.group(1)),
            "ways_count": None,
            "min_symbols_for_win": None,
            "direction": "left_to_right" if ("left" in p or "fixed" in p or m) else None,
            "notes": notes,
        }
    return {
        "type": "unknown",
        "payline_count": None,
        "ways_count": None,
        "min_symbols_for_win": None,
        "direction": None,
        "notes": notes,
    }


def parse_rtp(rtp_text: str) -> tuple[float | None, str | None]:
    if not rtp_text:
        return None, None
    nums = [
        float(x)
        for x in re.findall(r"(\d{2,3}(?:[.,]\d+)?)\s*%?", rtp_text.replace(",", "."))
    ]
    nums = [n for n in nums if 80 <= n <= 100]
    if not nums:
        nums = [float(x) for x in re.findall(r"(\d{2}\.\d+)", rtp_text.replace(",", "."))]
        nums = [n for n in nums if 80 <= n <= 100]
    return (nums[0] if nums else None), rtp_text


def parse_max_win(text: str) -> float | None:
    if not text:
        return None
    t = text.replace("\u00a0", " ").replace(",", " ")
    m = re.search(r"([\d\s]+(?:[.,]\d+)?)\s*x", t, re.I)
    if m:
        raw = m.group(1).replace(" ", "").replace(",", ".")
        try:
            return float(raw)
        except ValueError:
            return None
    m = re.search(r"([\d\s]+)\s*/\s*([\d\s]+)", t)
    if m:
        try:
            return float(m.group(1).replace(" ", ""))
        except ValueError:
            return None
    return None


def parse_release_year(specs: dict) -> int | None:
    for k, v in specs.items():
        if "Release" in k or "Game Name" in k:
            m = re.search(r"(20\d{2})", v)
            if m:
                return int(m.group(1))
    return None


def clean_demo_url(raw: str | None) -> str | None:
    if not raw:
        return None
    u = raw.strip().strip('"').strip("'").replace(" ", "")
    if not u.startswith("http"):
        return None
    return u


def to_webp(data: bytes, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    im = Image.open(BytesIO(data)).convert("RGB")
    im.thumbnail((640, 640), Image.Resampling.LANCZOS)
    im.save(dest, "WEBP", quality=82, method=4)


def pdf_to_text(pdf_path: Path) -> str:
    """Light text extract via pdftotext if available, else empty."""
    import subprocess

    try:
        out = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if out.returncode == 0:
            return out.stdout
    except Exception:
        pass
    return ""


def build_base_game_loop(
    desc: str,
    win: dict,
    tumble: bool | None,
    tumble_how: str | None,
    has_prog_mult: bool,
    prog_mult_how: str | None,
) -> dict | None:
    dl = desc.lower()
    phases = []
    order = 1
    phases.append(
        {
            "name": "spin",
            "what_happens": "Player places a bet and spins; symbols land on the grid.",
            "order": order,
            "ends_when": "Reels/grid settle",
            "state_changes": None,
        }
    )
    order += 1
    if win["type"] == "clusters":
        min_s = win.get("min_symbols_for_win")
        eval_txt = (
            f"Winning clusters of {min_s}+ matching adjacent symbols are evaluated."
            if min_s
            else "Winning clusters of matching adjacent symbols are evaluated."
        )
        phases.append(
            {
                "name": "win_evaluation",
                "what_happens": eval_txt,
                "order": order,
                "ends_when": "All current winning clusters identified",
                "state_changes": None,
            }
        )
    elif win["type"] == "paylines":
        pc = win.get("payline_count")
        phases.append(
            {
                "name": "win_evaluation",
                "what_happens": (
                    f"Wins evaluated along {pc} paylines (left-to-right) per official Paylines field."
                    if pc
                    else "Wins evaluated along paylines per official Paylines field."
                ),
                "order": order,
                "ends_when": "All paying lines scored",
                "state_changes": None,
            }
        )
    elif win["type"] == "ways":
        phases.append(
            {
                "name": "win_evaluation",
                "what_happens": "Wins evaluated as ways-to-win per official Betways/Paylines field.",
                "order": order,
                "ends_when": "All ways scored",
                "state_changes": None,
            }
        )
    else:
        phases.append(
            {
                "name": "win_evaluation",
                "what_happens": "Winning combinations evaluated per game win system.",
                "order": order,
                "ends_when": None,
                "state_changes": None,
            }
        )
    order += 1

    if tumble:
        how = tumble_how or (
            "Winning clusters/symbols are removed; remaining symbols fall and new symbols "
            "fill empty positions (avalanche/cascade)."
        )
        # Prefer official avalanche wording if present
        aval = find_sentence(desc, "avalanche", "winning clusters explode", "tumble")
        if aval:
            how = aval
        phases.append(
            {
                "name": "avalanche_cascade",
                "what_happens": how,
                "order": order,
                "ends_when": "No further winning clusters/combinations after a cascade",
                "state_changes": "Winning symbols removed; grid refilled from above",
            }
        )
        order += 1

    if has_prog_mult:
        how = prog_mult_how or "Progressive win multiplier increases with consecutive wins."
        phases.append(
            {
                "name": "progressive_multiplier",
                "what_happens": how,
                "order": order,
                "ends_when": None,
                "state_changes": "Win multiplier grows across consecutive wins in the cascade chain",
            }
        )
        order += 1

    summary_bits = []
    if win["type"] == "clusters":
        summary_bits.append("cluster-pays")
    elif win["type"] == "paylines":
        summary_bits.append("payline")
    if tumble:
        summary_bits.append("avalanche/cascade")
    if has_prog_mult:
        summary_bits.append("progressive win multiplier")
    summary = (
        "Paid spin on Slotmill "
        + (" / ".join(summary_bits) if summary_bits else "video slot")
        + ": spin → evaluate wins"
        + (" → avalanche while wins continue" if tumble else "")
        + (" → multiplier grows with wins" if has_prog_mult else "")
        + "."
    )
    # Only emit if we have meaningful cascade or clear win system from specs
    if win["type"] == "unknown" and not tumble and not has_prog_mult:
        return None
    return {
        "summary": summary,
        "phases": phases,
        "win_evaluation": phases[1]["what_happens"] if len(phases) > 1 else None,
        "notes": "Phases inferred from official Slotmill game-page specs + marketing description; spin counts/costs not invented.",
    }


def enrich_from_pdf_text(pdf_text: str) -> dict:
    """Pull free-spin trigger hints from product sheet when clearly stated."""
    out: dict = {}
    if not pdf_text:
        return out
    # Look for free spins award patterns — only capture explicit statements
    m = re.search(
        r"(.{0,80}(?:free spins?|bonus)[^.!?\n]{0,120}(?:award|trigger|land|scatter|bonus)[^.!?\n]{0,120}[.!?])",
        pdf_text,
        re.I,
    )
    if m:
        out["fs_sentence"] = re.sub(r"\s+", " ", m.group(1)).strip()
    m2 = re.search(
        r"(\d+)\s+free spins",
        pdf_text,
        re.I,
    )
    if m2:
        out["spins_awarded"] = int(m2.group(1))
    m3 = re.search(
        r"(?:land|collect|hit)\s+(\d+)\s+(?:or more\s+)?(?:scatter|bonus)",
        pdf_text,
        re.I,
    )
    if m3:
        out["trigger_count"] = int(m3.group(1))
    return out


def build_record(
    page_slug: str,
    html: str,
    url: str,
    pdf_text: str | None = None,
    pdf_local: str | None = None,
) -> dict:
    specs = extract_specs(html)
    # Prefer Next.js gameDetails when HTML specs miss fields
    gd = extract_next_game_details(html)
    if gd:
        mapping = {
            "Game Name / Release Date": None,
            "Game ID": "gameID",
            "Game URL": "gameURL",
            "Game Type": "gameType",
            "Paylines": "paylines",
            "Betways": "betways",
            "RTP (%)": None,
            "Volatility (variance)": "volatility",
            "Max win; x Bet": "maxWin",
            "Bonus Features": "bonusFeatures",
            "Special Symbols": "specialSymbols",
        }
        if gd.get("gameName") and gd.get("releaseDate"):
            specs.setdefault(
                "Game Name / Release Date",
                f"{gd['gameName']} / {gd['releaseDate']}",
            )
        for label, key in mapping.items():
            if key and gd.get(key) and not specs.get(label):
                specs[label] = str(gd[key])
        if not specs.get("RTP (%)") and gd.get("rtp"):
            # rtp may be richtext list
            rtp = gd["rtp"]
            if isinstance(rtp, list):
                bits = []
                for block in rtp:
                    for ch in block.get("children") or []:
                        if ch.get("text"):
                            bits.append(ch["text"])
                if bits:
                    specs["RTP (%)"] = " | ".join(bits)
            elif isinstance(rtp, str):
                specs["RTP (%)"] = rtp

    desc = extract_description(html)
    title = specs.get("Game Name / Release Date", "").split(" / ")[0].strip()
    if not title:
        m = re.search(r"<h1[^>]*>([^<]+)</h1>", html)
        title = HTML.unescape(m.group(1)).strip() if m else page_slug.replace("-", " ").title()
    game_id = specs.get("Game ID") or page_slug
    game_type = specs.get("Game Type", "")
    paylines = specs.get("Paylines") or specs.get("Betways") or ""
    rtp_raw = specs.get("RTP (%)", "")
    max_win_raw = specs.get("Max win; x Bet", "")
    bonus_feats = specs.get("Bonus Features", "")
    specials = specs.get("Special Symbols", "")
    volatility = specs.get("Volatility (variance)", "")
    demo_url = clean_demo_url(specs.get("Game URL"))

    rows, cols, layout_notes = parse_grid(game_type)
    win = parse_win_system(paylines)
    rtp, rtp_notes = parse_rtp(rtp_raw)
    max_win = parse_max_win(max_win_raw)

    dl = desc.lower()
    pdf_info = enrich_from_pdf_text(pdf_text or "")

    # Cascades
    tumble = None
    tumble_how = None
    aval_sent = find_sentence(
        desc, "winning clusters explode", "Trigger avalanches", "avalanche", "tumble", "cascade"
    )
    # Prefer the concrete cascade sentence over marketing intro that merely says "Avalanche Cluster Pays"
    if aval_sent and "winning clusters explode" not in aval_sent.lower() and "trigger avalanche" not in aval_sent.lower():
        better = find_sentence(desc, "winning clusters explode", "Trigger avalanches")
        if better:
            aval_sent = better
    if aval_sent or any(
        k in dl for k in ("avalanche", "cluster pays", "winning clusters explode", "tumble")
    ):
        tumble = True
        tumble_how = aval_sent or (
            "Described as avalanche/cluster cascade in official game page copy."
        )
    elif "cluster" in (paylines or "").lower():
        tumble = True
        tumble_how = (
            "Cluster pays game type; winning clusters remove and refill "
            "(exact cascade wording not always stated on marketing page)."
        )

    # Progressive multiplier
    has_prog_mult = False
    prog_how = None
    if any(
        k in dl
        for k in (
            "progressive win multiplier",
            "progressive multiplier",
            "doubles with each win",
            "multiplier doubles",
        )
    ) or "progressive multiplier" in (bonus_feats or "").lower():
        has_prog_mult = True
        prog_how = find_sentence(
            desc,
            "Progressive Win Multiplier",
            "progressive multiplier",
            "DOUBLES",
            "doubles with each",
        ) or "Progressive Win Multiplier referenced on official page."

    ante = None
    ante_notes = None
    if "xtra-bet" in dl or "xtra bet" in dl:
        ante = True
        ante_notes = XTRA_BET_EFFECTS

    buy = None
    buy_notes = None
    if "fast track" in dl:
        buy = True
        buy_notes = FAST_TRACK_EFFECTS

    features: list[dict] = []
    seen_feat: set[str] = set()

    def add_feature(name: str, trigger, effects: str, **extra):
        key = name.lower()
        if key in seen_feat:
            return
        seen_feat.add(key)
        feat = {
            "name": name,
            "trigger": trigger,
            "effects": effects,
            "params": {},
        }
        feat.update(extra)
        features.append(feat)

    # Named bonus features from specs — enrich from description sentences
    if bonus_feats:
        for part in re.split(r",\s*", bonus_feats):
            part = part.strip()
            if not part:
                continue
            pl = part.lower()
            sent = find_sentence(desc, part)
            # Special enrichments
            if "giant" in pl:
                sent = sent or find_sentence(desc, "Giant Symbols", "giant symbol")
                add_feature(
                    part,
                    None,
                    sent
                    or "Giant Symbols listed under Bonus Features on official Slotmill game page.",
                )
            elif "progressive" in pl and "multiplier" in pl:
                add_feature(part, None, prog_how or sent or "Progressive multiplier feature.")
            elif "free spin" in pl:
                # handled primarily in bonus_free_spins; still list as feature
                fs_sent = find_sentence(desc, "Free Spins", "free spin")
                add_feature(
                    part,
                    pdf_info.get("fs_sentence"),
                    fs_sent
                    or sent
                    or "Free Spins Bonus listed on official Slotmill game page; exact trigger counts often not on marketing page.",
                )
            else:
                add_feature(
                    part,
                    None,
                    sent or f"{part} listed under Bonus Features on official Slotmill game page.",
                )

    # Description-only features (avalanche, progressive) if not already listed
    if tumble and not any("avalanche" in f["name"].lower() or "cluster" in f["name"].lower() for f in features):
        if "avalanche" in dl or "cluster" in (paylines or "").lower():
            add_feature(
                "Avalanche / Cluster Cascade",
                "Winning cluster lands",
                tumble_how or "Winning clusters explode and new symbols cascade in.",
            )
    if has_prog_mult and not any("multiplier" in f["name"].lower() for f in features):
        add_feature("Progressive Win Multiplier", "Each consecutive win in cascade", prog_how)

    # Studio-wide modes with official definitions
    if "burst mode" in dl:
        sent = find_sentence(desc, "Burst Mode") or BURST_EFFECTS
        add_feature("Burst Mode", "Player enables Burst Mode", sent, when="any time / auto-play")
    if "fast track" in dl:
        sent = find_sentence(desc, "Fast Track") or FAST_TRACK_EFFECTS
        add_feature(
            "Fast Track",
            "Player selects Fast Track",
            sent,
            when="before spin / bonus access",
        )
    if "xtra-bet" in dl or "xtra bet" in dl:
        sent = find_sentence(desc, "Xtra-Bet", "Xtra Bet") or XTRA_BET_EFFECTS
        add_feature(
            "Xtra-Bet",
            "Player opts into raised bet",
            sent,
            when="base game bet selection",
        )

    wilds = []
    scatters = []
    specials_list = []
    if specials:
        for part in re.split(r",\s*", specials):
            part = part.strip()
            if not part:
                continue
            pl = part.lower()
            if "wild" in pl:
                behavior = find_sentence(desc, "Wild") or (
                    "Listed under Special Symbols on official page."
                )
                wilds.append({"name": part, "behavior": behavior, "params": {}})
            elif "bonus" in pl or "scatter" in pl:
                behavior = (
                    pdf_info.get("fs_sentence")
                    or find_sentence(desc, "Free Spins", "Bonus")
                    or "Listed under Special Symbols on official page."
                )
                scatters.append({"name": part, "behavior": behavior, "params": {}})
            else:
                specials_list.append(
                    {
                        "name": part,
                        "behavior": "Listed under Special Symbols on official page.",
                        "params": {},
                    }
                )

    multipliers = []
    if has_prog_mult:
        multipliers.append(
            {
                "name": "Progressive Win Multiplier",
                "behavior": prog_how
                or "Progressive win multiplier grows with consecutive wins.",
                "params": {},
            }
        )

    # Bonus free spins modes
    bonus_modes = []
    has_fs = (
        any("free spin" in f["name"].lower() for f in features)
        or "free spin" in dl
        or "free spins" in (bonus_feats or "").lower()
    )
    if has_fs:
        fs_effects_parts = []
        fs_sent = find_sentence(desc, "Free Spins", "free spin")
        if fs_sent:
            fs_effects_parts.append(fs_sent)
        if pdf_info.get("fs_sentence"):
            fs_effects_parts.append(pdf_info["fs_sentence"])
        if has_prog_mult and (
            "multiplier remains" in dl
            or "remains active" in dl
            or "multiplier" in (fs_sent or "").lower()
        ):
            persist = find_sentence(desc, "multiplier remains", "remains active throughout")
            if persist:
                fs_effects_parts.append(persist)

        trigger = None
        if pdf_info.get("trigger_count"):
            trigger = (
                f"Product sheet implies trigger involving "
                f"{pdf_info['trigger_count']}+ scatter/bonus symbols "
                "(verify in sheet; marketing page may omit exact count)."
            )
        elif "bonus" in (specials or "").lower():
            trigger = (
                "Triggered via Bonus symbol(s) (listed under Special Symbols); "
                "exact scatter count not stated on marketing page."
            )

        sticky = None
        progressive = None
        if has_prog_mult and (
            "remains active" in dl or "multiplier remains" in dl or "throughout" in dl
        ):
            sticky = (
                "Progressive win multiplier remains active throughout Free Spins "
                "(per official description)."
            )
            progressive = sticky

        phases = [
            {
                "name": "trigger",
                "what_happens": trigger
                or "Free Spins Bonus triggered (exact symbol count often not on marketing page).",
                "order": 1,
                "ends_when": None,
                "state_changes": None,
            },
            {
                "name": "free_spins_play",
                "what_happens": (
                    "Free spins play with base cascade/multiplier rules"
                    + (" and persistent progressive multiplier" if sticky else "")
                    + "."
                ),
                "order": 2,
                "ends_when": "Awarded free spins are exhausted (retrigger rules not always stated)",
                "state_changes": sticky,
            },
        ]

        spins_awarded = pdf_info.get("spins_awarded")  # only if PDF stated a number
        bonus_modes.append(
            {
                "name": "Free Spins",
                "trigger": trigger,
                "spins_awarded": spins_awarded,
                "retrigger": None,
                "sticky_or_persistent_state": sticky,
                "progressive_state": progressive,
                "effects": " ".join(fs_effects_parts)
                or "Free Spins referenced on official page; exact trigger counts not always stated on marketing page.",
                "end_condition": "Free spins counter reaches zero (retrigger not evidenced on marketing page).",
                "phases": phases,
            }
        )

    base_loop = build_base_game_loop(
        desc, win, tumble, tumble_how, has_prog_mult, prog_how
    )

    unknowns = []
    if rows is None:
        unknowns.append("grid rows/cols not parsed from Game Type")
    if win["type"] == "unknown":
        unknowns.append("win_system exact type from Paylines field ambiguous")
    unknowns.append("full paytable / symbol pays not on marketing page")
    if has_fs and not pdf_info.get("spins_awarded"):
        unknowns.append(
            "exact free-spins award count / scatter trigger count not stated on marketing page"
        )
    if ante:
        unknowns.append(
            "Xtra-Bet cost multiplier not stated on marketing page (not invented)"
        )
    if buy:
        unknowns.append(
            "Fast Track buy cost not stated on marketing page (not invented)"
        )
    if volatility:
        unknowns.append(f"volatility from official specs: {volatility}")

    excerpt_bits = []
    for k in (
        "Game Type",
        "Paylines",
        "Betways",
        "RTP (%)",
        "Max win; x Bet",
        "Bonus Features",
        "Special Symbols",
        "Volatility (variance)",
        "Game URL",
    ):
        if specs.get(k):
            excerpt_bits.append(f"{k}: {specs[k]}")
    if desc:
        excerpt_bits.append(desc[:700])

    evidence = [
        {
            "source_type": "provider_marketing",
            "url": url,
            "local_path": f"sources/slotmill/{page_slug}.html",
            "extracted_at": EXTRACTED_AT,
            "quote_or_excerpt": "\n".join(excerpt_bits)[:1500],
        }
    ]
    if pdf_local and pdf_text:
        evidence.append(
            {
                "source_type": "provider_product_sheet",
                "url": None,
                "local_path": pdf_local,
                "extracted_at": EXTRACTED_AT,
                "quote_or_excerpt": (pdf_text[:800] if pdf_text else None),
            }
        )

    conf_grid = "high" if rows and cols else "low"
    conf_win = "high" if win["type"] != "unknown" else "medium"
    conf_num = "high" if (rtp is not None or max_win is not None) else "medium"
    conf_feat = "high" if features and desc else "medium"
    conf_reel = "high" if tumble and tumble_how else ("medium" if tumble else "low")
    conf_bonus = "medium" if bonus_modes else "low"
    if bonus_modes and (
        bonus_modes[0].get("sticky_or_persistent_state") or pdf_info.get("spins_awarded")
    ):
        conf_bonus = "high"
    conf_loop = "high" if base_loop and conf_grid == "high" and conf_win == "high" else (
        "medium" if base_loop else "low"
    )
    # overall high only when grid + win + (bonus when present) evidence-backed
    overall = "medium"
    if conf_grid == "high" and conf_win == "high" and conf_num == "high":
        if has_fs:
            if conf_bonus in ("high", "medium") and conf_feat == "high":
                overall = "high"
        else:
            overall = "high"

    record = {
        "schema_version": "1.1.0",
        "updated_at": EXTRACTED_AT,
        "identity": {
            "provider": "Slotmill",
            "title": title,
            "slug": f"slotmill-{page_slug}",
            "provider_game_id": game_id,
            "release_year": parse_release_year(specs),
            "demo_url": demo_url,
            "slotcatalog_url": None,
            "official_info_url": url,
        },
        "grid": {
            "rows": rows,
            "cols": cols,
            "rows_min": None,
            "rows_max": None,
            "layout_notes": layout_notes,
        },
        "win_system": win,
        "reel_behavior": {
            "cascades_or_tumbles": {"present": tumble, "how_it_works": tumble_how},
            "respins": {"present": None, "how_it_works": None},
            "expanding_reels": {"present": None, "how_it_works": None},
            "other": [],
        },
        "base_game_loop": base_loop,
        "symbols": {
            "wilds": wilds,
            "scatters": scatters,
            "multipliers": multipliers,
            "collectors": [],
            "specials": specials_list,
        },
        "bonus_free_spins": {
            "modes": bonus_modes,
            "notes": (
                f"Volatility (official): {volatility}" if volatility else None
            ),
        },
        "features": features,
        "feature_buy": {
            "available": buy,
            "options": [],
            "notes": buy_notes,
        },
        "ante_bet": {
            "available": ante,
            "cost_multiplier": None,
            "effects": ante_notes,
            "notes": ante_notes,
        },
        "numeric_limits": {
            "max_win_multiplier": max_win,
            "max_win_notes": f"Official Max win; x Bet: {max_win_raw}" if max_win_raw else None,
            "rtp_percent": rtp,
            "rtp_notes": rtp_notes,
            "hit_frequency_notes": None,
        },
        "confidence": {
            "overall": overall,
            "grid": conf_grid,
            "win_system": conf_win,
            "reel_behavior": conf_reel,
            "base_game_loop": conf_loop,
            "symbols": "medium" if (wilds or scatters or multipliers) else "low",
            "bonus_free_spins": conf_bonus,
            "features": conf_feat,
            "feature_buy": "medium" if buy else "low",
            "numeric_limits": conf_num,
        },
        "evidence": evidence,
        "unknowns": unknowns,
        "thumbnail": None,
        "thumbnail_attribution": None,
    }
    return record


def load_urls() -> list[tuple[str, str]]:
    path = SOURCES / "game_urls.txt"
    urls = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or "/games/" not in line:
            continue
        slug = line.rstrip("/").split("/")[-1]
        if slug in ("games",):
            continue
        urls.append((slug, line))
    return urls


def try_download_product_sheet(slug: str, html: str) -> tuple[str | None, str | None]:
    """Download product sheet PDF if URL found. Returns (local_rel_path, text)."""
    pdf_url = extract_product_sheet_url(html)
    if not pdf_url:
        return None, None
    dest = SOURCES / f"product_sheet_{slug}.pdf"
    try:
        data = http_get(pdf_url)
        if len(data) < 500 or not data.startswith(b"%PDF"):
            return None, None
        dest.write_bytes(data)
        text = pdf_to_text(dest)
        txt_path = SOURCES / f"product_sheet_{slug}.txt"
        if text:
            txt_path.write_text(text, encoding="utf-8")
        return f"sources/slotmill/product_sheet_{slug}.pdf", text
    except Exception:
        return None, None


def process_one(slug: str, url: str) -> tuple[str, str]:
    try:
        data = http_get(url)
        html = data.decode("utf-8", errors="ignore")
        SOURCES.mkdir(parents=True, exist_ok=True)
        (SOURCES / f"{slug}.html").write_text(html, encoding="utf-8")
        pdf_local, pdf_text = try_download_product_sheet(slug, html)
        rec = build_record(slug, html, url, pdf_text=pdf_text, pdf_local=pdf_local)
        og = extract_og_image(html)
        if og:
            try:
                img = http_get(og)
                dest = THUMBS / f"{rec['identity']['slug']}.webp"
                to_webp(img, dest)
                rec["thumbnail"] = f"thumbs/{rec['identity']['slug']}.webp"
                rec["thumbnail_attribution"] = "Slotmill"
            except Exception as e:
                rec.setdefault("unknowns", []).append(f"thumbnail fetch failed: {e}")
        out = GAMES / f"{rec['identity']['slug']}.json"
        out.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")
        return slug, "ok"
    except Exception as e:
        return slug, f"ERR {e}"


def main() -> None:
    SOURCES.mkdir(parents=True, exist_ok=True)
    THUMBS.mkdir(parents=True, exist_ok=True)
    items = load_urls()
    print(f"Slotmill games to parse: {len(items)}")
    ok = err = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(process_one, s, u) for s, u in items]
        for i, fut in enumerate(as_completed(futs), 1):
            slug, status = fut.result()
            if status == "ok":
                ok += 1
            else:
                err += 1
                print(" ", slug, status)
            if i % 10 == 0 or i == len(items):
                print(f"  {i}/{len(items)} done (ok={ok} err={err})")
            time.sleep(0.03)
    print(json.dumps({"ok": ok, "err": err, "total": len(items)}))


if __name__ == "__main__":
    main()
