import { colors, styles } from "../../theme/tokens";

export interface FieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  placeholder?: string;
  required?: boolean;
}

/**
 * Shared form field component used by all repository connectors (AWS, Azure, GitHub).
 * Provides consistent styling and behavior across connector forms.
 */
export function ConnectorField({ label, value, onChange, type = "text", placeholder, required = false }: FieldProps) {
  return (
    <div style={{ marginBottom: 12 }}>
      <label
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
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        required={required}
        style={{
          width: "100%",
          padding: "7px 10px",
          background: colors.bg,
          border: `1px solid ${colors.border}`,
          borderRadius: 6,
          color: colors.text,
          fontSize: 13,
          ...styles.fontSans,
          outline: "none",
          boxSizing: "border-box",
        }}
      />
    </div>
  );
}
