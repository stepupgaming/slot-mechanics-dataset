# Slot Mechanics Dataset

Public, machine-readable descriptions of **how video slots actually work** (grid, win system, tumbles/respins, symbol behaviors, free-spin modes, feature buys, limits) — not shallow marketing tags.

Built for Money / Crypto Marketing workflows under GitHub user [`stepupgaming`](https://github.com/stepupgaming).

## Layout

```
schema/slot-mechanics.schema.json   # JSON Schema (draft 2020-12) for one game record
games/<slug>.json                   # one record per game
dataset.json                        # index + counts (points at games/)
dataset-full.json                   # combined array of all records (large)
sources/                            # raw evidence dumps (official HTML/PDF/txt, SlotCatalog HTML)
scripts/                            # parsers used to build records
```

## Quick start

```bash
# list high-confidence Pragmatic titles
jq -r '.games[] | select(.provider=="Pragmatic Play" and .confidence_overall=="high") | .title' dataset.json

# load one game
jq . games/pragmatic-gates-of-olympus.json

# validate (requires jsonschema)
python -c "import json,glob; from jsonschema import Draft202012Validator as V; s=json.load(open('schema/slot-mechanics.schema.json')); v=V(s); \
[v.validate(json.load(open(f))) for f in glob.glob('games/*.json')]; print('ok')"
```

Example records:

- `games/hacksaw-chaos-crew.json` — official Hacksaw gameinfo (paylines, Cranky Cat wild multipliers, meter free spins)
- `games/pragmatic-gates-of-olympus.json` — official rules PDF (pay anywhere, tumble, multipliers, ante, buy)
- `games/pragmatic-sugar-rush.json` — official rules PDF (7×7 clusters, multiplier spots, free spins)

## Confidence levels

| Level | Meaning |
| --- | --- |
| **high** | Core mechanics extracted from the game’s own Info / Rules / Paytable (Hacksaw `en-us-gameinfo.html`, or Pragmatic official rules PDF). Quotes stored under `evidence` and usually mirrored in `sources/`. |
| **medium** | Secondary sources with concrete mechanic text or structured tags (e.g. SlotCatalog layout/betways/feature lists). Useful for discovery; verify before relying on buy costs / exact triggers. |
| **low** | Partial parse, missing grid/win system, or tags without rule text. See `unknowns`. |

Confidence is also set **per major section** (`confidence.grid`, `confidence.feature_buy`, etc.).

## Provenance rules (do not invent)

1. Prefer **official** demo Info / Rules / Paytable / provider rules PDF.
2. SlotCatalog (and similar) = discovery + cross-check only.
3. Never invent payline counts, buy costs, ante multipliers, max wins, or RTP.
4. If a value is only a runtime template in HTML (e.g. Hacksaw `{rtp}%`, `{featureBuyRtp}%`), store `null` and list the field in `unknowns`.
5. RTP / max win are recorded **only** when a concrete number appears in official rules text (or clearly tagged secondary source for medium records, with notes).
6. Every record has `evidence[]` with `source_type`, URL/path, timestamp, and a short excerpt.

## Providers in this release

Priority order used while collecting:

1. **Pragmatic Play** — official rules PDFs where text-extractable; SlotCatalog for a few titles whose PDFs were image-only.
2. **Hacksaw Gaming** — full set of local official `en-us-gameinfo.html` dumps (high confidence for most titles).
3. **Nolimit City** — smaller SlotCatalog seed batch (medium); official sheets to be expanded.

See `dataset.json` → `by_provider` / `by_confidence` / `by_provider_confidence` for live counts.

## Schema highlights

Each `games/*.json` includes:

- `identity` — provider, title, slug, demo/info URLs
- `grid` — rows/cols + layout notes
- `win_system` — `paylines` | `ways` | `pay_anywhere` | `clusters` | `other` | `unknown` (+ counts)
- `reel_behavior` — cascades/tumbles, respins, expanding reels
- `symbols` — wilds / scatters / multipliers / collectors / specials with behavior text
- `bonus_free_spins` — trigger, retrigger, sticky/persistent/progressive state
- `features` — named features with trigger/effects
- `feature_buy` / `ante_bet` — availability + cost multipliers **only if stated**
- `numeric_limits` — max win / RTP notes
- `confidence`, `evidence`, `unknowns`

## Regenerating

```bash
# Hacksaw (requires /workspace/hacksaw-info/pages from prior scrape)
python3 scripts/parse_hacksaw.py

# Pragmatic (requires PDFs under sources/pragmatic/pdfs/)
python3 scripts/parse_pragmatic_pdfs.py
```

Then rebuild the index by re-running the validation/index script used in this repo’s build process (or regenerate `dataset.json` from `games/*.json`).

## License / use

Mechanics text is transcribed/summarized from publicly available game info and rules materials for interoperability and marketing research. Providers retain rights to their games and artwork. This dataset does **not** include ROM/binary assets or copyrighted art packs.

## Blockers / known gaps

- Hacksaw static gameinfo often leaves RTP and feature-buy **prices** as `{placeholders}` → those fields stay `null`.
- Some Pragmatic rules PDFs are image-only (no text layer); those titles fall back to SlotCatalog (medium) until OCR/official HTML is added.
- Nolimit official in-game help HTML is not yet bulk-mirrored; current Nolimit rows are medium/SlotCatalog.
- Interactive demo Info pages sometimes need a real browser session (age gates / JS shells).

