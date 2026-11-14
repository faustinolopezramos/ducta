import { useEffect, useId, useRef, useState } from "react";
import { IconChevronDown } from "@tabler/icons-react";

export interface FilterOption {
  value: string;
  label: string;
}

/**
 * One filter of the Runs bar: a button that says what it filters on, opening a
 * short list. Status takes several values (checkboxes, the list stays open);
 * pipeline, environment, project and date take one (picking closes it).
 *
 * Replaces the status chips and the native <select>s, which drew the same bar
 * in three different ways. The button is petrol while it filters, and its text
 * says on what ("Status · Failed, Cancelled").
 */
export function FilterMenu({
  label,
  allLabel = "all",
  options,
  selected,
  onChange,
  multiple = false,
  buttonText,
  footer,
  filtering,
}: {
  label: string;
  /** What the button says while nothing is picked ("Pipeline: all"). */
  allLabel?: string;
  options: FilterOption[];
  selected: string[];
  onChange: (values: string[]) => void;
  multiple?: boolean;
  /** Overrides the button's text (the date menu reads "Last 7 days"). */
  buttonText?: string;
  /** Extra content under the list (the custom date range). */
  footer?: React.ReactNode;
  /** Filtering even with nothing in the list picked (a custom date range). */
  filtering?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const id = useId();
  const active = selected.length > 0 || Boolean(filtering);
  const names = options.filter((o) => selected.includes(o.value)).map((o) => o.label);
  const text = buttonText ?? (active ? `${label} · ${names.join(", ")}` : `${label}: ${allLabel}`);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    // Escape closes it and gives focus back to its button.
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      buttonRef.current?.focus();
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const close = () => {
    setOpen(false);
    buttonRef.current?.focus();
  };

  const pick = (value: string) => {
    if (multiple) {
      onChange(selected.includes(value) ? selected.filter((v) => v !== value) : [...selected, value]);
    } else {
      onChange(selected.includes(value) ? [] : [value]);
      close();
    }
  };

  return (
    <div className="run-filters__menu" ref={rootRef}>
      <button
        ref={buttonRef}
        type="button"
        className="run-filters__menu-btn"
        data-active={active || undefined}
        aria-haspopup="true"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        aria-label={`${label}: ${buttonText ?? (active ? names.join(", ") : allLabel)}`}
        onClick={() => setOpen((v) => !v)}
      >
        <span>{text}</span>
        <IconChevronDown size={13} aria-hidden="true" />
      </button>
      {open && (
        <div id={id} className="run-filters__popover" role="group" aria-label={label}>
          {options.map((o) =>
            multiple ? (
              <label key={o.value} className="run-filters__option">
                <input type="checkbox" checked={selected.includes(o.value)} onChange={() => pick(o.value)} />
                {o.label}
              </label>
            ) : (
              <button
                key={o.value}
                type="button"
                className="run-filters__option"
                aria-pressed={selected.includes(o.value)}
                onClick={() => pick(o.value)}
              >
                {o.label}
              </button>
            ),
          )}
          {footer}
        </div>
      )}
    </div>
  );
}
