import { useLayoutEffect, useRef, useState } from "react";

/**
 * The end of a name that tells it apart from its neighbours: from the last "_"
 * or "." when that is short ("_student"), else its last few characters.
 */
export function distinctiveTail(text: string, maxTail = 12): string {
  const cut = Math.max(text.lastIndexOf("_"), text.lastIndexOf("."));
  if (cut > 0 && text.length - cut <= maxTail) return text.slice(cut);
  return text.length > maxTail ? text.slice(-Math.min(8, maxTail)) : "";
}

const ELLIPSIS = "…";

/**
 * The head to show so `head + "…" + tail` fills `width` exactly: the longest
 * prefix that fits, and no shorter than the name's first segment ("silver.")
 * unless even that does not fit.
 * Null when the whole name fits.
 */
export function fitHead(
  text: string,
  tail: string,
  width: number,
  measure: (s: string) => number,
): string | null {
  if (measure(text) <= width + 0.5) return null;
  const head = text.slice(0, text.length - tail.length);
  const dot = head.indexOf(".");
  const fits = (n: number) => measure(head.slice(0, n) + ELLIPSIS + tail) <= width + 0.5;
  // Keep the first segment ("silver.") when there is room for it. In a box too
  // narrow even for that, holding on to it pushed the "…" out of view and the
  // name read as another one ("silv_education").
  const preferred = Math.min(head.length, dot > 0 ? dot + 1 : 1);
  const minKeep = fits(preferred) ? preferred : 1;
  let lo = minKeep;
  let hi = head.length - 1;
  let best = minKeep;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (fits(mid)) {
      best = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return head.slice(0, best) + ELLIPSIS;
}

let canvas: HTMLCanvasElement | null = null;
function measurer(font: string, letterSpacing: number): ((s: string) => number) | null {
  if (typeof document === "undefined") return null;
  canvas ??= document.createElement("canvas");
  let ctx: CanvasRenderingContext2D | null = null;
  try {
    ctx = canvas.getContext("2d");
  } catch {
    return null; // jsdom: no canvas
  }
  if (!ctx) return null;
  ctx.font = font;
  // The names are set with a slight negative tracking, which canvas text does
  // not apply: unaccounted, every name measured a pixel or two wider than its
  // box and names that fit were cut.
  return (s) => ctx!.measureText(s).width + letterSpacing * s.length;
}

/**
 * A name cut in the middle only when it does not fit: the head shrinks with an
 * ellipsis, the distinctive tail always shows. Canvas names share long
 * prefixes ("golden.transformation_…"); an ellipsis at the end made two of
 * them read the same.
 *
 * The cut is measured, not left to `text-overflow`: CSS clipped the head at a
 * glyph boundary and left the rest of its box empty, so a gap opened before
 * the tail ("golden.transfor… _student"). The box takes its width from an
 * invisible copy of the whole name (`::before`), so the measurement never
 * feeds on the cut text. Without layout (tests) the name shows whole.
 */
export function MiddleTruncate({ text, className }: { text: string; className?: string }) {
  const tail = distinctiveTail(text);
  const ref = useRef<HTMLSpanElement>(null);
  /** Not measured yet (CSS cuts), measured and whole, or the head that fits. */
  const [fit, setFit] = useState<{ head: string | null } | null>(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const measureAndFit = (width: number) => {
      if (!width) return;
      const style = getComputedStyle(el);
      const tracking = parseFloat(style.letterSpacing);
      const measure = measurer(
        `${style.fontStyle} ${style.fontWeight} ${style.fontSize} ${style.fontFamily}`,
        Number.isFinite(tracking) ? tracking : 0,
      );
      if (!measure) return;
      setFit({ head: fitHead(text, tail, width, measure) });
    };
    let width = 0;
    const observer = new ResizeObserver(([entry]) => {
      width = entry.contentRect.width;
      measureAndFit(width);
    });
    observer.observe(el);
    // A measurement taken before the web font arrived used the fallback face,
    // and a box already clamped to its room does not resize when the font
    // lands — so nothing re-measured, and the cut was left to CSS.
    const fonts = typeof document !== "undefined" ? document.fonts : undefined;
    const refit = () => measureAndFit(width);
    fonts?.addEventListener?.("loadingdone", refit);
    void fonts?.ready?.then(refit);
    return () => {
      observer.disconnect();
      fonts?.removeEventListener?.("loadingdone", refit);
    };
  }, [text, tail]);

  const classes = `middle-trunc${fit ? " middle-trunc--fitted" : ""}${className ? ` ${className}` : ""}`;
  // Measured and whole: one run of text. Split into head and tail, the parts'
  // rounding could add a fraction of a pixel and set off the head's CSS
  // ellipsis on a name that fits ("golden.u…  ersities").
  if (fit && fit.head === null) {
    return (
      <span ref={ref} className={classes} title={text} data-text={text}>
        <span className="middle-trunc__text">{text}</span>
      </span>
    );
  }
  const head = fit?.head ?? (tail ? text.slice(0, text.length - tail.length) : text);
  // The ellipsis sits in a span of its own: the font draws "…" with room on
  // its right, which read as a space before the tail.
  const cut = head.endsWith(ELLIPSIS);
  return (
    <span ref={ref} className={classes} title={text} data-text={text}>
      <span className="middle-trunc__text">
        <span className="middle-trunc__head">{cut ? head.slice(0, -1) : head}</span>
        {/* Outside the head, which clips: inside it the "…" was the first thing cut. */}
        {cut && <span className="middle-trunc__dots">{ELLIPSIS}</span>}
        {tail && <span className="middle-trunc__tail">{tail}</span>}
      </span>
    </span>
  );
}
