import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import "./Menu.css";

export interface MenuItem {
  key: string;
  label: ReactNode;
  /** Secondary line under the label (a path, a role…). */
  hint?: ReactNode;
  icon?: ReactNode;
  onSelect?: () => void;
  /** Shown checked and not actionable — the current choice. */
  current?: boolean;
  tone?: "danger";
  /** Draw a divider above this item. */
  divideBefore?: boolean;
}

/**
 * A button that opens a list of actions: Escape and a click outside close it,
 * arrow keys move between items, and focus returns to the button on close.
 */
export function Menu({
  trigger,
  triggerLabel,
  triggerTitle,
  triggerClassName,
  header,
  items,
  align = "end",
}: {
  trigger: ReactNode;
  triggerLabel: string;
  triggerTitle?: string;
  triggerClassName?: string;
  /** Non-interactive block at the top (who you are, where you are). */
  header?: ReactNode;
  items: MenuItem[];
  align?: "start" | "end";
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const id = useId();

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    listRef.current?.querySelector<HTMLElement>("[role=menuitem]:not([aria-disabled=true])")?.focus();
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const close = () => {
    setOpen(false);
    buttonRef.current?.focus();
  };

  const onListKey = (e: React.KeyboardEvent) => {
    const all = Array.from(listRef.current?.querySelectorAll<HTMLElement>("[role=menuitem]") ?? []);
    const at = all.indexOf(document.activeElement as HTMLElement);
    if (e.key === "Escape") {
      e.preventDefault();
      close();
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const step = e.key === "ArrowDown" ? 1 : -1;
      all[(at + step + all.length) % all.length]?.focus();
    } else if (e.key === "Home" || e.key === "End") {
      e.preventDefault();
      (e.key === "Home" ? all[0] : all[all.length - 1])?.focus();
    }
  };

  return (
    <div className="ducta-menu" ref={rootRef}>
      <button
        ref={buttonRef}
        type="button"
        className={triggerClassName}
        aria-label={triggerLabel}
        title={triggerTitle ?? triggerLabel}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={() => setOpen((v) => !v)}
      >
        {trigger}
      </button>
      {open && (
        <div
          id={id}
          ref={listRef}
          role="menu"
          tabIndex={-1}
          aria-label={triggerLabel}
          className={`ducta-menu__list ducta-menu__list--${align}`}
          onKeyDown={onListKey}
        >
          {header && <div className="ducta-menu__header">{header}</div>}
          {items.map((item) => (
            <div key={item.key} role="none">
              {item.divideBefore && <div className="ducta-menu__divider" role="separator" />}
              <button
                type="button"
                role="menuitem"
                className="ducta-menu__item"
                data-tone={item.tone}
                aria-current={item.current || undefined}
                onClick={() => {
                  if (item.current) return close();
                  setOpen(false);
                  item.onSelect?.();
                }}
              >
                <span className="ducta-menu__icon" aria-hidden="true">{item.icon}</span>
                <span className="ducta-menu__text">
                  <span className="ducta-menu__label">{item.label}</span>
                  {item.hint && <span className="ducta-menu__hint">{item.hint}</span>}
                </span>
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
