# Foresprint 1.0 design system

Draft for review. Tokens are proposals; mocks in `docs/redesign/mocks/` are the test bed.
Product context: [PRODUCT.md](PRODUCT.md).

## Principles

1. Data first. Chrome stays quiet so tables, boards and forecasts carry the page.
2. One accent. Indigo marks the primary action and the current location, nothing else.
3. Mint is the forecast. Dashed or mint always means "predicted", solid means "happened".
4. Dense, not cramped. Rows 32 px, 4 px grid, no decorative shadows.
5. Every state is designed: empty, loading, error, offline, stale (Jira not synced).

## Color tokens

| Token | Light | Dark | Use |
| --- | --- | --- | --- |
| `--bg` | `#f7f7fb` | `#101118` | App background |
| `--surface` | `#ffffff` | `#181a24` | Cards, tables, panels |
| `--surface-2` | `#eef0f7` | `#212433` | Hover, selected row, inputs |
| `--border` | `#dcdfeb` | `#2d3144` | Dividers |
| `--text` | `#1b1d2a` | `#e8eaf4` | Body |
| `--text-muted` | `#5d6280` | `#9aa0bf` | Secondary text (4.5:1 on surface) |
| `--primary` | `#5b5bf0` | `#8585ff` | Primary action, current page |
| `--secondary` | `#a24df0` | `#bb7bff` | Charts, product accent |
| `--forecast` | `#17c3a0` | `#2ad9b5` | Forecast, predicted values |
| `--highlight` | `#ffc233` | `#ffc233` | Focus ring accent, marker |
| `--ok` / `--warn` / `--bad` | `#1a9a5a` / `#c47f00` / `#d33a4a` | `#3dc07c` / `#f0a81c` / `#ff6b7a` | Traffic light; never color alone, always with icon or text |

Dark theme is a first-class token set, switched by `prefers-color-scheme` and an explicit setting.
Contrast target: WCAG AA for text, 3:1 for UI borders and icons.

## Typography

| Role | Font | Size / line |
| --- | --- | --- |
| UI text | Proposal: Inter (OFL), system UI fallback. Alternative: Iosevka Aile. Decision open, see PRODUCT.md | 14 / 20 |
| Numbers, IDs, tickets | Iosevka (OFL), tabular figures | 13 / 20 |
| Page title | UI font semibold | 22 / 28 |
| Section title | UI font semibold | 16 / 24 |
| Caption | UI font | 12 / 16 |

Fonts ship inside the executable; no web requests.

## Spacing, shape, motion

- 4 px grid: 4, 8, 12, 16, 24, 32, 48.
- Radius 6 px (controls), 10 px (cards). Borders instead of shadows; one shadow for drag ghost and menus.
- Row height 32 px (dense), 40 px (comfortable, setting).
- Motion 120 to 180 ms ease-out, only for state change and drag feedback. Respect `prefers-reduced-motion`.

## Icons

Material Symbols, outlined, weight 400, flat, 20 px. No emojis anywhere in the UI. Icon-only buttons need a tooltip and an `aria-label`.

## Layout

- Left rail (240 px, collapsible to 56 px) with the task steps and areas; top bar with team, sprint, sync state, search (Ctrl+K).
- Content max width for forms 720 px; tables and boards use the full width.
- Minimum window 1100 x 700; below 900 px the rail collapses.

## Components

| Component | Notes |
| --- | --- |
| Button | primary (filled indigo), secondary (outline), ghost, danger; 32 px high; loading state |
| Input, select, chips | 32 px; filter chips with count; visible label above |
| Table | sticky header, sortable, column chooser, row selection, inline edit |
| Backlog row | drag handle, key, title, estimate, product and project chips, status; keyboard move (Alt+Up/Down) |
| Sprint lane | capacity bar (committed vs forecast), drop zone with insert line |
| Capacity bar | solid = committed, dashed mint = forecast range |
| Traffic light | icon + word + color |
| Toast, banner | sync errors, offline, unsaved changes |
| Dialog, drawer | ticket detail as right drawer, not a page |
| Command palette | Ctrl+K: go to page, find ticket, run action |

## Interaction rules

- Drag and drop always has a keyboard and a menu alternative.
- Destructive actions are undoable (toast with Undo) instead of confirm dialogs where possible.
- Every number with a derivation opens its calculation as a table (carries over the 0.8 "Rechenweg").
- Sync is automatic and visible: last sync time, changed-ticket count, one click to retry.

## Accessibility

Full keyboard use, visible focus ring (2 px indigo plus 2 px offset), landmarks and labels, color never the only signal, 200 percent zoom without loss, reduced motion honored.

## Checks

`npx impeccable detect` runs on the HTML mocks in CI once added. Skill-based critique needs access to impeccable.style from the host or a local install.
