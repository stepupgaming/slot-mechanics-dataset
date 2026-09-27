# Schema 1.1 draft (additive)

Compatible with existing `1.0.0` game JSON. New records that use the loop fields should set `"schema_version": "1.1.0"`.

## Goals
Make mechanics **rebuildable**: ordered phases with concrete triggers, awards, state rules — not marketing tags.

## Additive fields
### `base_game_loop` (optional object)
- `summary` — one-paragraph overview of a paid spin
- `phases[]` — ordered `{ name, what_happens, order?, ends_when?, state_changes? }`
- `win_evaluation` — when wins are scored relative to phases
- `notes`

### `bonus_free_spins.modes[]` enrichments
- `end_condition`
- `phases[]` (same shape as base loop phases)
- `award` (optional alias; prefer `spins_awarded` for spin counts)

### `features[]` enrichments
- `when`, `cost_multiplier`, `cost_text`

### `confidence.base_game_loop`
Optional confidence facet when loop is populated.

## Provider enum
Includes `Elk Studios` and `Slotmill` alongside existing studios.

## Quality bar
Do not mark `overall: high` unless grid, win evaluation, at least one bonus mode (when the game has one), and buy/ante (when present) have concrete, evidence-backed values — not “listed on SlotCatalog”.
