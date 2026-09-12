import React from "react";
import { cx } from "../../utils/classNames";
import "./Button.css";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** Visual emphasis. `primary` = main action, one per view. */
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Show a spinner and block interaction without collapsing layout. */
  loading?: boolean;
  /** Icon before the label (decorative — kept out of the a11y tree). */
  leftIcon?: React.ReactNode;
  /** Icon after the label (decorative). */
  rightIcon?: React.ReactNode;
  /** Stretch to the container width. */
  fullWidth?: boolean;
  /** Icon-only button: requires `aria-label` for screen readers. */
  iconOnly?: boolean;
}

/**
 * Canonical button primitive for the redesigned Ducta UI.
 *
 * Three emphasis levels + danger, built entirely on design tokens. Keyboard
 * focus is handled by the global `:focus-visible` ring (no JS focus handlers).
 * When `loading`, the button is `aria-busy` and non-interactive but preserves
 * its width so surrounding layout never shifts.
 */
export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = "secondary",
    size = "md",
    loading = false,
    leftIcon,
    rightIcon,
    fullWidth = false,
    iconOnly = false,
    disabled,
    className,
    children,
    type = "button",
    ...rest
  },
  ref,
) {
  const classes = cx(
    "tui-btn",
    `tui-btn--${variant}`,
    `tui-btn--${size}`,
    fullWidth && "tui-btn--block",
    iconOnly && "tui-btn--icon",
    loading && "is-loading",
    className,
  );

  return (
    <button
      ref={ref}
      type={type}
      className={classes}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading && <span className="tui-btn__spinner" aria-hidden="true" />}
      <span className="tui-btn__content">
        {leftIcon && (
          <span className="tui-btn__icon" aria-hidden="true">
            {leftIcon}
          </span>
        )}
        {children && <span className="tui-btn__label">{children}</span>}
        {rightIcon && (
          <span className="tui-btn__icon" aria-hidden="true">
            {rightIcon}
          </span>
        )}
      </span>
    </button>
  );
});
