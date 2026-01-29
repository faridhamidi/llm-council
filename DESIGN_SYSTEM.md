# LLM Council Design System

A lightweight design system derived from the current UI aesthetics: dark, high‑contrast surfaces, soft green accents, subtle grid + glow, and geometric sans typography.

## Visual Principles

- **Quiet confidence**: low‑contrast surfaces with precise highlights.
- **Data‑centric**: typography and spacing favor dense, readable content.
- **Soft neon**: green accent used sparingly as an emphasis, not a flood.
- **Structured depth**: layered surfaces with gentle glow and subtle borders.

## Color System

### Foundation

- `--bg-primary`: #0b0d0f
- `--bg-secondary`: #121417
- `--bg-tertiary`: #171a1f
- `--bg-elevated`: #1e2229
- `--bg-hover`: #20252d
- `--border-primary`: #262b33
- `--border-secondary`: #1f232b
- `--text-primary`: #f3f4f6
- `--text-secondary`: #a1a1aa
- `--text-tertiary`: #6b7280

### Accent

- `--accent-green`: #3ecf8e (primary)
- `--accent-green-dark`: #2da873
- `--accent-green-light`: #4fffb0
- `--accent-emerald`: #10b981
- `--accent-teal`: #14b8a6
- `--accent-yellow`: #f59e0b (warning)
- `--accent-red`: #ef4444 (danger)
- `--accent-blue`: #3b82f6 (info)
- `--glow`: rgba(62, 207, 142, 0.18)
- `--glow-strong`: rgba(62, 207, 142, 0.35)

### Semantic Tokens

- Surfaces: `--surface-0/1/2/3` map to bg tokens
- Text: `--text-1/2/3` map to text tokens
- Borders: `--border-1/2` map to border tokens
- Accent: `--accent-1`, `--accent-1-strong`, `--accent-1-soft`
- States: `--accent-warning`, `--accent-danger`, `--accent-info`
- Focus: `--focus-ring`

## Typography

- **Sans**: Space Grotesk (400/500/600/700)
- **Mono**: IBM Plex Mono (400/500/600)

Type scale (recommended):
- Display: 32/40
- H1: 24/32
- H2: 20/28
- H3: 18/26
- Body: 15/24
- Small: 13/20
- Mono: 13/20

## Spacing & Layout

Spacing scale:
- `--space-1` 4px
- `--space-2` 8px
- `--space-3` 12px
- `--space-4` 16px
- `--space-5` 20px
- `--space-6` 24px
- `--space-7` 32px
- `--space-8` 40px
- `--space-9` 48px
- `--space-10` 64px

Layout guidance:
- Use a 12‑column grid for dashboards and panels.
- Prefer 8px increments for padding and gap.

## Radii & Elevation

- Radii: `--radius-1` 6px, `--radius-2` 10px, `--radius-3` 14px, `--radius-4` 18px, `--radius-5` 24px
- Shadows: `--shadow-1`, `--shadow-2` for elevated layers

## Motion

- Easing: `--ease-standard`, `--ease-emphasized`
- Durations: `--duration-fast` 140ms, `--duration-base` 220ms, `--duration-slow` 360ms
- Use subtle opacity + translate (2‑6px) on entry.

## Components (Guidelines)

### Buttons

- **Primary**: `accent-1` background, bold text, hover to `accent-1-strong`.
- **Secondary**: `surface-2` background, `border-1` border.
- **Ghost**: transparent background, text‑only with hover surface.
- **Danger**: `accent-danger` background, use sparingly.

### Inputs

- Background: `surface-1`
- Border: `border-1`, focus ring `focus-ring`
- Placeholder text: `text-3`

### Cards / Panels

- Background: `surface-2` or `surface-3`
- Border: `border-1`
- Slight shadow on hover to signal interactivity.

### Tabs

- Inactive: text `text-2`, subtle border
- Active: `accent-1` underline + brighter text

### Pills / Badges

- Use `accent-1-soft` for neutral, `accent-warning` or `accent-danger` for state.

### Toasts

- Background: `surface-3`
- Border: `border-1`
- Icon color aligned with state.

## Patterns

- **Data density**: Use compact spacing with readable line‑height.
- **Transparency**: Show raw outputs and structured summaries side‑by‑side.
- **Layering**: Use background grid + glow sparingly to avoid distraction.

## Do/Don’t

- Do keep contrast high for readability.
- Do use green accent only for key actions or status.
- Don’t introduce multiple competing accent colors.
- Don’t use large gradients in content areas; keep them in the backdrop.
