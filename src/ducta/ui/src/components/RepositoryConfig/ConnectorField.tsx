import { useId } from "react";
import { colors, styles } from "../../theme/tokens";

export interface FieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  placeholder?: string;
  required?: boolean;
  /** Error message; shows a red border and the message below the input. */
  error?: string;
}

/**
 * Shared form field component used by all repository connectors (AWS, Azure, GitHub).
 * Provides consistent styling and behavior across connector forms.
 */
export function ConnectorField({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
  required = false,
  error,
}: FieldProps) {
  const inputId = useId();
  return (
    <div style={{ marginBottom: 12 }}>
      <label
        htmlFor={inputId}
        style={{
          display: "block",
          ...styles.fontSans,
          fontSize: 11,
          color: colors.textMuted,
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          marginBottom: 5,
        }}
      >
        {label}
        {required && <span style={{ color: colors.red, marginLeft: 3 }}>*</span>}
      </label>
      <input
        id={inputId}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${inputId}-error` : undefined}
        style={{
          width: "100%",
          padding: "7px 10px",
          background: colors.bg,
          border: `1px solid ${error ? colors.red : colors.border}`,
          borderRadius: 6,
          color: colors.text,
          fontSize: 13,
          ...styles.fontSans,
          outline: "none",
          boxSizing: "border-box",
        }}
      />
      {error && (
        <span
          id={`${inputId}-error`}
          role="alert"
          style={{ ...styles.fontSans, fontSize: 11, color: colors.red, marginTop: 4, display: "block" }}
        >
          {error}
        </span>
      )}
    </div>
  );
}
