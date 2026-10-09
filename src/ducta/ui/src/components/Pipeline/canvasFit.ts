/**
 * Room around the graph when framing it, in screen pixels: the floating
 * toolbars sit over the top corners and the filter bar and zoom controls over
 * the bottom, so a fraction of the graph's size left the first and last cards
 * under them.
 */
export const FIT_PADDING = { top: "72px", right: "40px", bottom: "112px", left: "40px" } as const;
/** Where the top of a graph too tall to frame starts, below the toolbars. */
export const FIT_TOP_PX = 72;
/** Never zoom past 1:1 when framing — the cards are designed at a size. */
export const FIT_MAX_ZOOM = 1;
