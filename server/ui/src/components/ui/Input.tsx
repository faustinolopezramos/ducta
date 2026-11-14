import { useId, type CSSProperties } from "react";
import "./Input.css";

export interface InputProps {
  label: string;
  value: any;
  onChange: (v: any) => void;
  id?: string;
  name?: string;
  placeholder?: string;
  type?: string;
  fullWidth?: boolean;
  disabled?: boolean;
  required?: boolean;
  error?: boolean;
  helperText?: string;
  helperTextId?: string;
  ariaDescribedBy?: string;
  style?: CSSProperties;
  mono?: boolean;
}

/**
 * Input component using CSS custom properties
 * Replaces MUI TextField with prototype-style CSS
 */
export function Input({
  label,
  value,
  onChange,
  id,
  name,
  placeholder = "",
  type = "text",
  fullWidth = true,
  disabled = false,
  required = false,
  error = false,
  helperText = "",
  helperTextId,
  ariaDescribedBy,
  style = {},
  mono = false,
}: InputProps) {
  const generatedId = useId();
  const inputId = id || `input-${generatedId}`;
  const resolvedHelperTextId = helperText ? helperTextId || `${inputId}-helper` : undefined;
  const resolvedAriaDescribedBy = ariaDescribedBy || resolvedHelperTextId;

  return (
    <div className={`input-wrapper ${fullWidth ? "input-full-width" : ""}`} style={style}>
      {label && (
        <label htmlFor={inputId} className="input-label">
          {label}
          {required && <span className="input-required">*</span>}
        </label>
      )}
      <input
        id={inputId}
        name={name}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        required={required}
        className={`input-field ${error ? "input-error" : ""} ${mono ? "input-mono" : ""}`}
        aria-describedby={resolvedAriaDescribedBy}
        aria-invalid={error || undefined}
      />
      {helperText && (
        <div id={resolvedHelperTextId} className={`input-helper ${error ? "input-helper-error" : ""}`}>
          {helperText}
        </div>
      )}
    </div>
  );
}
