# DESIGN — Slot Mechanics viewer

## Mode
Catalog / Read. Browse and understand games. Presentation quality matters; the data must still be scannable.

## Brief (user)
Polished public interface for the mechanics dataset. Reference energy of Big Win Board / Casino Guru catalogs — **art-first game tiles**, cleaner and more structured. Not a raw admin table. Not purple-glass SaaS.

## Scene
Evening desk, researching slots. Deep charcoal canvas, soft elevated panels, warm accent (not neon). Lobby art leads every tile.

## Color
- Canvas: `#090a0d`
- Raised: `#12141b`
- Raised-2: `#181b24`
- Line: `rgba(255,255,255,0.08)`
- Text: `#f3f4f6` / muted `#9aa3b5`
- Accent: `#d4a24c` (warm metal) — selection, primary actions
- High: `#3ecf8e` · Medium: `#e0b44c` · Low: `#f07178`

## Type
- Display / titles: **Fraunces**
- UI / body: **Figtree**
- Mono (slugs, JSON): system mono stack

Scale: 12 / 13 / 14 / 16 / 18 / 24 / 40. Weights 400–700. Tracking on large titles −0.03em.

## Layout
1. Top brand bar + search
2. Filter chips (providers) + selects
3. Responsive **art-first tile grid** (cover / lobby still → title / provider / chips)
4. Selecting a game opens a **dossier** (right drawer on desktop, full sheet on mobile): hero art, title block, at-a-glance strip, then Mechanics · Symbols · Bonus · Sources

## Thumbnails
Local files under `thumbs/<slug>.webp` (relative paths in `dataset.json` / per-game JSON). Sourced from SlotCatalog lobby thumbs and Big Win Board review featured images. Attribution on each record (`thumbnail_attribution`). Tasteful initials placeholder only if a path is missing.

## Anti-references
Previous dark purple glass dashboard; previous light admin toolbar shell; text-only tiles without art.
