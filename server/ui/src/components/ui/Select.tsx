import React, { useId } from "react";
import { IconChevronDown } from "@tabler/icons-react";
import { cx } from "../../utils/classNames";
import "./Select.css";

export interface SelectProps extends Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "size"> {
  label?: string;
  size?: "sm" | "md";
  mono?: boolean;
  error?: boolean;
  fullWidth?: boolean;
  helperText?: string;
  helperTextId?: string;
  containerClassName?: string;
}

/**
 * Standardized Select component for the Ducta Design System.
 * Supports consistent appearance, focus rings, custom chevron, and compatibility with Field.
 */
export const Select = React.forwardRef<HTMLSelectElement, SelectProps>(function Select(
  {
    label,
    size = "md",
    mono = false,
    error = false,
    fullWidth = true,
    helperText = "",
    helperTextId,
    id,
    disabled = false,
    required = false,
    className,
    containerClassName,
    children,
    style,
    ...rest
  },
  ref,
) {
  const generatedId = useId();
  // Always an id: the helper text's id is derived from it, and a Select with
  // helper text but no label would otherwise point at "undefined-helper".
  const selectId = id || `select-${generatedId}`;
  const resolvedHelperTextId = helperText ? helperTextId || `${selectId}-helper` : undefined;

  const selectElement = (
    <div className={cx("select-container", !fullWidth && "select-container--auto", containerClassName)}>
      <select
        ref={ref}
        id={selectId}
        disabled={disabled}
        required={required}
        className={cx(
          "select-field",
          `select-field--${size}`,
          mono && "select-field--mono",
          error && "select-error",
          className,
        )}
        style={style}
        aria-invalid={error || undefined}
        aria-describedby={resolvedHelperTextId}
        {...rest}
      >
        {children}
      </select>
      <span className="select-chevron" aria-hidden="true">
        <IconChevronDown size={size === "sm" ? 13 : 15} stroke={1.8} />
      </span>
    </div>
  );

  if (!label && !helperText) {
    return selectElement;
  }

  return (
    <div className={cx("select-wrapper", fullWidth && "select-wrapper--full")}>
      {label && (
        <label htmlFor={selectId} className="select-label">
          {label}
          {required && <span className="select-required">*</span>}
        </label>
      )}
      {selectElement}
      {helperText && (
        <div id={resolvedHelperTextId} className={cx("select-helper", error && "select-helper-error")}>
          {helperText}
        </div>
      )}
    </div>
  );
});
