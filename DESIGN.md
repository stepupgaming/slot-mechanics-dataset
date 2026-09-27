# DESIGN — Slot Mechanics viewer

## Mode
Operate. The tool disappears into the lookup task.

## Scene
Desk work, long sessions, reading dense rules text. Cool neutral surfaces; dark charcoal content area optional but no neon glow.

## Color (Restrained)
- Canvas: `#f4f5f7`
- Panel / list: `#ffffff`
- Detail well: `#0f1115` (ink) for long reading contrast, OR stay light — pick one system: **light canvas, white panels, ink text**
- Text: `#111318` / secondary `#5c6370`
- Line: `#e4e6eb`
- Accent (selection + primary links only): `#2563eb`
- Success/high: `#0f7b4c` · Medium: `#9a6700` · Low: `#b42318`

## Type
One family: system UI stack (`ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`).
Scale: 12 / 13 / 14 / 16 / 20 / 28. Weights 400 / 500 / 600. Mono only for slugs and JSON paths: `ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`.

## Layout
Full-bleed app shell. Thin top toolbar (title + search + filters). Split: dense list | detail. No hero, no metric scoreboard, no provider pill row as decoration, no nested cards, no glass, no gradient text, no kickers.

## Components
Text inputs and selects share one height (36px). List rows are flat, 1px dividers. Selected row: light blue wash + accent text, not thick left border. Detail uses definition grids and section headings with space, not card stacks. Evidence in monospace blocks with muted chrome.

## Motion
150–200ms ease on selection background only. No page-load choreography.
