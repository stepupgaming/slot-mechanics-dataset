#!/usr/bin/env python3
"""Rebuild dataset.json and dataset-full.json from games/*.json."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GAMES = ROOT / "games"


def grid_label(grid: dict) -> str | None:
    if not grid:
        return None
    rows, cols = grid.get("rows"), grid.get("cols")
    if rows and cols:
        return f"{rows}×{cols}"
    return None


def main() -> None:
    records = []
    for path in sorted(GAMES.glob("*.json")):
        records.append(json.loads(path.read_text()))

    by_provider: Counter[str] = Counter()
    by_conf: Counter[str] = Counter()
    by_pc: dict[str, Counter[str]] = defaultdict(Counter)
    index_games = []
    thumb_count = 0
    for r in records:
        provider = r["identity"]["provider"]
        conf = r["confidence"]["overall"]
        by_provider[provider] += 1
        by_conf[conf] += 1
        by_pc[provider][conf] += 1
        thumb = r.get("thumbnail")
        if thumb:
            thumb_count += 1
        win = r.get("win_system") or {}
        reel = r.get("reel_behavior") or {}
        tumble = (reel.get("cascades_or_tumbles") or {}).get("present")
        buy = (r.get("feature_buy") or {}).get("available")
        ante = (r.get("ante_bet") or {}).get("available")
        index_games.append(
            {
                "slug": r["identity"]["slug"],
                "title": r["identity"]["title"],
                "provider": provider,
                "confidence_overall": conf,
                "path": f"games/{r['identity']['slug']}.json",
                "win_system_type": win.get("type") or "unknown",
                "grid": grid_label(r.get("grid") or {}),
                "has_tumble": tumble if isinstance(tumble, bool) else None,
                "has_buy": buy if isinstance(buy, bool) else None,
                "has_ante": ante if isinstance(ante, bool) else None,
                "thumbnail": thumb,
            }
        )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    dataset = {
        "schema_version": "1.0.0",
        "description": "Index of slot mechanics records. Full records live in games/<slug>.json",
        "updated_at": now,
        "game_count": len(records),
        "thumbnail_count": thumb_count,
        "by_provider": dict(sorted(by_provider.items(), key=lambda x: -x[1])),
        "by_confidence": dict(by_conf),
        "by_provider_confidence": {p: dict(cc) for p, cc in sorted(by_pc.items())},
        "games": index_games,
    }
    (ROOT / "dataset.json").write_text(json.dumps(dataset, indent=2, ensure_ascii=False) + "\n")
    (ROOT / "dataset-full.json").write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n")
    print(
        json.dumps(
            {
                k: dataset[k]
                for k in (
                    "game_count",
                    "thumbnail_count",
                    "by_provider",
                    "by_confidence",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
