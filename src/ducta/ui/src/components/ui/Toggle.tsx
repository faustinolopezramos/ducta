import { colors, styles } from "../../theme/tokens";

interface ToggleProps {
  label: string;
  value: boolean;
  onChange: (checked: boolean) => void;
}

export function Toggle({ label, value, onChange }: ToggleProps) {
  return (
    <label
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        cursor: "pointer",
        paddingTop: 10,
        paddingBottom: 10,
        borderBottom: `1px solid ${colors.border}`,
        ...styles.fontSans,
        fontSize: 13,
        color: colors.text,
      }}
    >
      <span>{label}</span>
      <input
        type="checkbox"
        checked={value}
        onChange={(e) => onChange(e.target.checked)}
        style={{ accentColor: colors.accent, width: 16, height: 16, cursor: "pointer" }}
      />
    </label>
  );
}
