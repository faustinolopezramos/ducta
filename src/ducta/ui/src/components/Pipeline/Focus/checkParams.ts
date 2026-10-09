import type { QualityCheckParam } from "../../../api/qualityApi";

const typeOf = (spec?: QualityCheckParam): string => {
  const t = spec?.type;
  return (Array.isArray(t) ? t.find((x) => x !== "null") : t) ?? "any";
};

/** A parameter's value as the one-line text its field shows. */
export function paramToText(value: unknown, spec?: QualityCheckParam): string {
  if (value === undefined || value === null) return "";
  const t = typeOf(spec);
  if (t === "array" && Array.isArray(value) && value.every((v) => typeof v !== "object")) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/**
 * The field's text back as the parameter's value, or `undefined` for an empty
 * field (the parameter is left out). Throws with a readable message when the
 * text cannot be that type.
 */
export function textToParam(text: string, spec?: QualityCheckParam): unknown {
  const raw = text.trim();
  if (raw === "") return undefined;
  const t = typeOf(spec);
  if (t === "integer" || t === "number") {
    const n = Number(raw);
    if (!Number.isFinite(n) || (t === "integer" && !Number.isInteger(n))) throw new Error(`expects ${t === "integer" ? "a whole number" : "a number"}`);
    return n;
  }
  if (t === "boolean") {
    if (/^(true|yes|1)$/i.test(raw)) return true;
    if (/^(false|no|0)$/i.test(raw)) return false;
    throw new Error("expects true or false");
  }
  if (t === "array") {
    if (raw.startsWith("[")) return JSON.parse(raw);
    return raw.split(",").map((s) => s.trim()).filter(Boolean);
  }
  if (t === "object") {
    try {
      return JSON.parse(raw);
    } catch {
      throw new Error("expects JSON, e.g. {\"key\": 1}");
    }
  }
  if (t === "any" && /^[[{]/.test(raw)) {
    try {
      return JSON.parse(raw);
    } catch {
      /* plain text */
    }
  }
  if (t === "any" && raw !== "" && Number.isFinite(Number(raw))) return Number(raw);
  return raw;
}
