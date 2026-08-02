const WINDOWS_DRIVE_RE = /^[a-zA-Z]:[\\/]/;
const WINDOWS_UNC_RE = /^(\\\\|\/\/)[^\\/]+[\\/][^\\/]+/;
const GIT_URL_RE = /^(https?:\/\/|git:\/\/|ssh:\/\/|[^@\s]+@[^:\s]+:)/i;

function stripOuterQuotes(value: string): string {
  const trimmed = value.trim();
  if (
    (trimmed.startsWith('"') && trimmed.endsWith('"')) ||
    (trimmed.startsWith("'") && trimmed.endsWith("'"))
  ) {
    return trimmed.slice(1, -1).trim();
  }
  return trimmed;
}

function looksLikeWindowsPath(value: string): boolean {
  return WINDOWS_DRIVE_RE.test(value) || WINDOWS_UNC_RE.test(value);
}

function looksLikePosixPath(value: string): boolean {
  return value.startsWith("~/") || value.startsWith("/") || value.startsWith("./") || value.startsWith("../");
}

export function normalizeSourceInput(rawValue: string | null | undefined): string | null {
  if (!rawValue) return null;

  let value = stripOuterQuotes(rawValue);
  if (!value) return null;

  if (GIT_URL_RE.test(value)) {
    return value;
  }

  if (looksLikeWindowsPath(value)) {
    value = value.replace(/\//g, "\\");
    value = value.replace(/\\{3,}/g, "\\\\");
    return value;
  }

  if (looksLikePosixPath(value)) {
    value = value.replace(/\\/g, "/");
    value = value.replace(/\/{2,}/g, "/");
    return value;
  }

  return value;
}
