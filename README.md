# Slot Mechanics Dataset

Public, machine-readable descriptions of **how video slots actually work** (grid, win system, tumbles/respins, symbol behaviors, free-spin modes, feature buys, limits) — not shallow marketing tags.

Built for Money / Crypto Marketing workflows under GitHub user [`stepupgaming`](https://github.com/stepupgaming).

## Browse online

Live dataset viewer (GitHub Pages): **https://stepupgaming.github.io/slot-mechanics-dataset/**

Art-first catalog viewer (lobby/cover tiles + sticky filters + dossier with Mechanics/Symbols/Bonus/Sources). Search and filter by studio, confidence, win system, tumble/buy/ante. Raw JSON in `games/` / `dataset.json`. Visual system: `DESIGN.md`.

### Thumbnails
Cover art lives in `thumbs/<slug>.webp` with a `thumbnail` path on each index entry and game record. Sources (see `thumbnail_attribution`): **SlotCatalog** lobby thumbs and **Big Win Board** review featured images (studio promotional art redistributed for catalog browsing). Mechanics data is independent of art provenance.

## Layout

```
schema/slot-mechanics.schema.json   # JSON Schema (draft 2020-12) for one game record
games/<slug>.json                   # one record per game (incl. thumbnail path)
dataset.json                        # index + counts + thumbnail paths
dataset-full.json                   # combined array of all records (large)
thumbs/<slug>.webp                  # local lobby/cover art for the catalog viewer
sources/                            # raw evidence dumps (official HTML/PDF/txt, SlotCatalog HTML)
scripts/                            # parsers + thumbnail fetch / index rebuild
```

## Quick start

```bash
# list high-confidence Pragmatic titles
jq -r '.games[] | select(.provider=="Pragmatic Play" and .confidence_overall=="high") | .title' dataset.json

# list Backseat Gaming titles
jq -r '.games[] | select(.provider=="Backseat Gaming") | .title' dataset.json

# load one game
jq . games/pragmatic-gates-of-olympus.json
jq . games/backseat-lord-venom.json

# validate (requires jsonschema)
python -c "import json,glob; from jsonschema import Draft202012Validator as V; s=json.load(open('schema/slot-mechanics.schema.json')); v=V(s); \
[v.validate(json.load(open(f))) for f in glob.glob('games/*.json')]; print('ok')"
```

Example records:

- `games/hacksaw-chaos-crew.json` — official Hacksaw gameinfo (paylines, Cranky Cat wild multipliers, meter free spins)
- `games/backseat-lord-venom.json` — official OpenRGS/Hacksaw CDN gameinfo (Backseat studio; Jungle Bush / Golden Egg bonus)
- `games/pragmatic-gates-of-olympus.json` — official rules PDF (pay anywhere, tumble, multipliers, ante, buy)
- `games/pragmatic-sugar-rush.json` — official rules PDF (7×7 clusters, multiplier spots, free spins)

## Confidence levels

| Level | Meaning |
| --- | --- |
| **high** | Core mechanics extracted from the game’s own Info / Rules / Paytable (Hacksaw / Backseat `en-us-gameinfo.html`, or Pragmatic official rules PDF). Quotes stored under `evidence` and usually mirrored in `sources/`. |
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

Live counts are always in `dataset.json` → `by_provider` / `by_confidence` / `by_provider_confidence`. Snapshot for this expansion:

| Provider | Records | Notes |
| --- | --- | --- |
| **Pragmatic Play** | **250** (~156 high / ~94 medium) | Expanded from ~42. High = text-extractable official rules PDFs (yesplay.bet CDN + kertn GameRules mirrors). Medium = SlotCatalog when PDF missing or image-only. |
| **Hacksaw Gaming** | ~203 | Official `en-us-gameinfo.html` dumps (mostly high). |
| **Backseat Gaming** | **35** (all high) | Independent studio on Hacksaw OpenRGS. Same `en-us-gameinfo.html` CDN path; `identity.provider` = **Backseat Gaming**, slug prefix `backseat-`. |
| **Nolimit City** | 7 | SlotCatalog seed batch (medium); official sheets to be expanded. |

Priority while collecting: official rules/gameinfo first, SlotCatalog only to fill gaps without inventing mechanics.

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

Provider enum includes `Pragmatic Play`, `Hacksaw Gaming`, `Backseat Gaming`, `Nolimit City`, `Other`.

## Regenerating

```bash
# Hacksaw (requires /workspace/hacksaw-info/pages from prior scrape)
python3 scripts/parse_hacksaw.py

# Backseat Gaming (OpenRGS gameinfo under sources/backseat/pages/)
python3 scripts/parse_backseat.py

# Pragmatic (requires PDFs under sources/pragmatic/pdfs/)
python3 scripts/parse_pragmatic_pdfs.py
```

Then rebuild `dataset.json` / `dataset-full.json` from `games/*.json` (see counts in the index).

## License / use

Mechanics text is transcribed/summarized from publicly available game info and rules materials for interoperability and marketing research. Providers retain rights to their games and artwork. This dataset does **not** include ROM/binary assets or copyrighted art packs.

## Blockers / known gaps

- Hacksaw / Backseat static gameinfo often leaves RTP and feature-buy **prices** as `{placeholders}` → those fields stay `null`.
- Some Pragmatic rules PDFs are image-only (no text layer), e.g. Sweet Bonanza / The Dog House on common CDN mirrors; those titles stay SlotCatalog (medium) until OCR/official HTML is added.
- Yesplay / kertn PDF catalogs are incomplete vs the full Pragmatic library; SlotCatalog fills the rest to the 250 target without inventing mechanics.
- A few very new Backseat titles on BigWinBoard had no Hacksaw launcher/`gameid` yet (or used a non-Hacksaw demo host) → omitted until official `en-us-gameinfo.html` is available.
- Nolimit official in-game help HTML is not yet bulk-mirrored; current Nolimit rows are medium/SlotCatalog.
- Interactive demo Info pages sometimes need a real browser session (age gates / JS shells).
