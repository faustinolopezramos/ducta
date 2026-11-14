/**
 * Join CSS class names, dropping falsy entries. The single implementation
 * for the `[...].filter(Boolean).join(" ")` pattern that was previously
 * copy-pasted across every `components/ui` primitive.
 */
export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
