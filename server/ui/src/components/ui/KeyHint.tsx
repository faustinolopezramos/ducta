const isMac = typeof navigator !== "undefined" && /mac/i.test(navigator.userAgent);

const GLYPH: Record<string, string> = isMac
  ? { mod: "⌘", shift: "⇧", alt: "⌥", enter: "⏎", esc: "esc" }
  : { mod: "Ctrl", shift: "Shift", alt: "Alt", enter: "Enter", esc: "Esc" };

/**
 * A keyboard shortcut as the platform writes it: `mod+k` is ⌘K on a Mac and
 * Ctrl K elsewhere. Read by screen readers as the words, not the glyphs.
 */
export function KeyHint({ keys, className }: { keys: string; className?: string }) {
  const parts = keys.split("+").map((k) => GLYPH[k.toLowerCase()] ?? (k.length === 1 ? k.toUpperCase() : k));
  return (
    <kbd className={`key-hint${className ? ` ${className}` : ""}`} aria-label={keys.replace(/\+/g, " ").replace("mod", isMac ? "command" : "control")}>
      {parts.map((p, i) => (
        <span key={i}>{p}</span>
      ))}
    </kbd>
  );
}
