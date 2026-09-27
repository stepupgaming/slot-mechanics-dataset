# Slot Mechanics Dataset

Public, evidence-backed JSON descriptions of how video slots work, plus a browsable art-first catalog viewer.

Audience: researchers, marketers, and builders who need real mechanics (not marketing tags).

Viewer job: browse like a premium slot database (lobby art tiles), open a dossier with structured mechanics, jump to official rules / raw JSON.

Tone: confident, clean, game-industry literate — closer to a polished review catalog than an admin console.

## Quality bar (rebuildable mechanics)
A record is useful only if someone who never played the game can rebuild the loop from the structured fields:
what pays, tumble/cascade rules, free-spin trigger + awards + retrigger, buys/ante costs & effects, multipliers, and ordered phases.

Prefer fewer high-fidelity official-source records over hundreds of empty shells or SlotCatalog tag dumps.
Null-filled fields with a single prose blob in `effects` is a fail for gold-standard rows.

Schema 1.1 (additive): optional `base_game_loop.phases[]`, richer `bonus_free_spins.modes[].phases[]` / `end_condition`.
