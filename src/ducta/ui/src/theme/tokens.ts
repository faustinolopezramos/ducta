// ─────────────────────────────────────────────
// DESIGN TOKENS — values reference CSS custom
// properties so all inline styles automatically
// switch when [data-theme="dark"] is applied.
// ─────────────────────────────────────────────

export const colors = {
  // ── Base palette ──
  bg:          "var(--bg)",
  surface:     "var(--surface)",
  surfaceElevated: "var(--surface-elevated)",
  border:      "var(--border)",
  borderHover: "var(--border-hover)",
  text:        "var(--text)",
  textMuted:   "var(--text-muted)",
  textDim:     "var(--text-dim)",
  accent:      "var(--primary)",
  accentBg:    "var(--primary-light)",
  primary:     "var(--primary)",

  // ── Semantic colors ──
  success:     "var(--success)",
  warning:     "var(--warning)",
  danger:      "var(--danger)",
  error:       "var(--danger)",
  errorBg:     "color-mix(in srgb, var(--danger) 10%, transparent)",
  errorBorder: "var(--danger)",

  // ── Compatibility map (all values derive from theme tokens so light/dark
  //    never drift; hardcoded legacy hexes were removed) ──
  bgContrast:  "var(--bg)",
  amber:       "var(--warning)",
  green:       "var(--success)",
  blue:        "var(--blue)",
  red:         "var(--danger)",
  purple:      "var(--purple)",
  /** Warning text that clears WCAG AA on light surfaces (--warning-strong). */
  warningStrong: "var(--warning-strong)",

  // ── Compatibility Opacity variants ──
  redA12:      "color-mix(in srgb, var(--danger) 12%, transparent)",
  redA30:      "color-mix(in srgb, var(--danger) 30%, transparent)",
  amberA10:    "color-mix(in srgb, var(--warning) 10%, transparent)",
  amberA12:    "color-mix(in srgb, var(--warning) 12%, transparent)",
  amberA15:    "color-mix(in srgb, var(--warning) 15%, transparent)",
  amberA20:    "color-mix(in srgb, var(--warning) 20%, transparent)",
  amberA30:    "color-mix(in srgb, var(--warning) 30%, transparent)",
  greenA10:    "color-mix(in srgb, var(--success) 10%, transparent)",
  greenA12:    "color-mix(in srgb, var(--success) 12%, transparent)",
  greenA15:    "color-mix(in srgb, var(--success) 15%, transparent)",
  greenA20:    "color-mix(in srgb, var(--success) 20%, transparent)",
  greenA30:    "color-mix(in srgb, var(--success) 30%, transparent)",
  blueA12:     "color-mix(in srgb, var(--blue) 12%, transparent)",
  blueA15:     "color-mix(in srgb, var(--blue) 15%, transparent)",
  blueA30:     "color-mix(in srgb, var(--blue) 30%, transparent)",
  slateA12:    "color-mix(in srgb, var(--text-dim) 12%, transparent)",
  grayA12:     "color-mix(in srgb, var(--text-dim) 12%, transparent)",
  purpleA15:   "color-mix(in srgb, var(--purple) 15%, transparent)",
  orangeA15:   "color-mix(in srgb, var(--warning) 15%, transparent)",
  accentA12:   "color-mix(in srgb, var(--primary) 12%, transparent)",
  // accent alphas derive from --primary so they invert with the theme; they were
  // hardcoded black (rgba(0,0,0)) which was invisible/wrong in dark mode.
  accentA20:   "color-mix(in srgb, var(--primary) 20%, transparent)",
  accentA30:   "color-mix(in srgb, var(--primary) 30%, transparent)",
  accentA40:   "color-mix(in srgb, var(--primary) 40%, transparent)",
  accentDim:   "var(--primary-light)",
  shadow:      "var(--shadow)",
};

export const styles = {
  flexCenter: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },
  flexBetween: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
  },
  transition: "all 0.2s cubic-bezier(0.4, 0, 0.2, 1)",
  fontSans:    { fontFamily: 'var(--font-sans)' },
  fontMono:    { fontFamily: 'var(--font-mono)' },
};
