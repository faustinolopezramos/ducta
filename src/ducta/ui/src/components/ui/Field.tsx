import { cloneElement, isValidElement, useId, type ReactElement, type ReactNode } from "react";
import "./Field.css";

export interface FieldProps {
  /** Visible label text. */
  label: ReactNode;
  /** The single form control (input, select, textarea, custom). */
  children: ReactElement<any>;
  /** Helper text shown below the control. Hidden when an error is present. */
  help?: ReactNode;
  /** Error message; sets aria-invalid + describes the control. */
  error?: ReactNode;
  required?: boolean;
  /** Lay the label beside the control instead of above it. */
  inline?: boolean;
  className?: string;
  id?: string;
}

/**
 * Accessible field wrapper. Owns the label↔control association and wires
 * `aria-describedby` / `aria-invalid` / `aria-required` onto its child, so every
 * form control in the app gets consistent, correct semantics for free. Renders
 * exactly one labelled control; pass the control as the single child.
 */
export function Field({
  label,
  children,
  help,
  error,
  required = false,
  inline = false,
  className,
  id,
}: FieldProps) {
  const auto = useId();
  const childProps: Record<string, unknown> = children.props ?? {};
  const controlId = id ?? (childProps.id as string | undefined) ?? `field-${auto}`;
  const helpId = `${controlId}-help`;
  const errorId = `${controlId}-error`;

  const describedBy =
    [error ? errorId : null, help ? helpId : null, childProps["aria-describedby"]]
      .filter(Boolean)
      .join(" ") || undefined;

  const control = isValidElement(children)
    ? cloneElement(children, {
        id: controlId,
        "aria-describedby": describedBy,
        "aria-invalid": error ? true : childProps["aria-invalid"],
        "aria-required": required || childProps["aria-required"] || undefined,
      } as Record<string, unknown>)
    : children;

  return (
    <div className={["tui-field", inline ? "tui-field--inline" : "", className ?? ""].filter(Boolean).join(" ")}>
      <label className="tui-field__label" htmlFor={controlId}>
        {label}
        {required && (
          <span className="tui-field__required" aria-hidden="true">
            *
          </span>
        )}
      </label>
      <div className="tui-field__control">{control}</div>
      {error ? (
        <p className="tui-field__error" id={errorId} role="alert">
          {error}
        </p>
      ) : help ? (
        <p className="tui-field__help" id={helpId}>
          {help}
        </p>
      ) : null}
    </div>
  );
}
