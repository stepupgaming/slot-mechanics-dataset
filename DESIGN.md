# DESIGN — Slot Mechanics viewer

## Mode
Catalog / Read. Browse and understand games. Presentation quality matters; the data must still be scannable.

## Brief (user)
Polished public interface for the mechanics dataset. Reference energy of Big Win Board / Casino Guru catalogs, but cleaner, more structured, and better looking. Not a raw admin table. Not purple-glass SaaS.

## Scene
Evening desk, researching slots. Deep charcoal canvas, soft elevated panels, warm accent (not neon).

## Color
- Canvas: `#090a0d`
- Raised: `#12141b`
- Raised-2: `#181b24`
- Line: `rgba(255,255,255,0.08)`
- Text: `#f3f4f6` / muted `#9aa3b5`
- Accent: `#d4a24c` (warm metal) — selection, primary actions
- High: `#3ecf8e` · Medium: `#e0b44c` · Low: `#f07178`

## Type
- Display / titles: **Bricolage Grotesque**
- UI / body: **Source Sans 3**
- Mono (slugs, JSON): **IBM Plex Mono** only for code paths — wait, IBM Plex is on anti-default list as family; use system mono stack instead for data.

Scale: 12 / 13 / 14 / 16 / 18 / 24 / 40. Weights 400–700. Tracking on large titles −0.03em.

## Layout
1. Top brand bar + search
2. Filter chips (providers) + selects
3. Responsive game **tile grid** (the catalog)
4. Selecting a game opens a **dossier** (right drawer on desktop, full sheet on mobile): title block, at-a-glance strip, then structured sections (Mechanics · Symbols · Bonus · Sources)

## Anti-references
Previous dark purple glass dashboard; previous light admin toolbar shell.
