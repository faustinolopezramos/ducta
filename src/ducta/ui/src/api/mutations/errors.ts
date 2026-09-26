import { toastStore } from "../../hooks/useModalStack";

// ── Shared error helpers ──────────────────────────────────────────────────────

/**
 * Extract structured error info from an API error response.
 * Handles both the DuctaAPIError envelope ({ error, message, detail, request_id })
 * and the legacy FastAPI HTTPException shape ({ detail }).
 * Also handles plain-text 429 responses from the rate limiter.
 */
export interface ExtractedError {
  code: string;
  message: string;
  detail?: unknown;
  requestId?: string;
  status?: number;
}

export function extractError(error: unknown): ExtractedError {
  const err = error as {
    response?: {
      status?: number;
      data?: { error?: string; message?: string; detail?: unknown; request_id?: string } | string;
    };
    message?: string;
  };

  const status = err?.response?.status;
  const data = err?.response?.data;

  if (typeof data === "string") {
    return {
      code: status === 429 ? "RATE_LIMIT_EXCEEDED" : "UNKNOWN_ERROR",
      message: data,
      status,
    };
  }

  if (data && typeof data === "object") {
    const code = data.error ?? (status ? `HTTP_${status}` : "UNKNOWN_ERROR");
    return {
      code,
      message: data.message ?? String(data.detail ?? "Unknown error"),
      detail: data.detail,
      requestId: data.request_id,
      status,
    };
  }

  return {
    code: "NETWORK_ERROR",
    message: err?.message ?? "Unknown error",
    status,
  };
}

/**
 * Human-readable message for an API error, falling back to a caller-supplied
 * default when nothing meaningful could be extracted. Thin wrapper over
 * extractError for the many `onError` callbacks that just need a string.
 */
export function apiErrorMessage(error: unknown, fallback = "Operation failed"): string {
  const { message } = extractError(error);
  return message && message !== "Unknown error" ? message : fallback;
}

/**
 * Map error codes to user-friendly action messages. Keys are the `error`
 * values the API actually sends (ErrorCode in api/models/responses.py).
 */
export const ERROR_ACTION_MAP: Record<string, string> = {
  CONCURRENCY_ERROR: "Data was modified by another user. Please refresh and try again.",
  PROJECT_ALREADY_EXISTS: "A project with this name already exists.",
  WORKSPACE_NOT_FOUND: "No workspace is configured. Please select a workspace first.",
  PIPELINE_NOT_FOUND: "The requested pipeline does not exist.",
  NODE_NOT_FOUND: "The requested node does not exist.",
  CONFIG_FILE_NOT_FOUND: "The requested configuration file does not exist.",
  EXECUTION_NOT_FOUND: "The requested execution record does not exist.",
  PROJECT_NOT_FOUND: "The requested project does not exist.",
  AUTHENTICATION_ERROR: "Authentication failed. Please log in again.",
  INVALID_TOKEN: "Your session token is invalid. Please log in again.",
  TOKEN_EXPIRED: "Your session has expired. Please log in again.",
  EXECUTION_ERROR: "Pipeline execution failed. Check the logs for details.",
  RATE_LIMIT_EXCEEDED: "Too many requests. Please wait a moment and try again.",
  GIT_ERROR: "A Git operation failed. Check your repository state.",
  SYNTAX_ERROR: "The code contains syntax errors. Please fix and try again.",
  CONFIG_VALIDATION_ERROR: "Configuration validation failed. Please check the config format.",
};

export function getErrorAction(code: string): string | null {
  return ERROR_ACTION_MAP[code] ?? null;
}

export function defaultOnError(error: unknown, _variables: unknown, _context: unknown) {
  const extracted = extractError(error);
  const action = getErrorAction(extracted.code);
  const msg = action
    ? `${extracted.message} — ${action}`
    : `Operation failed: ${extracted.message}`;

  const toastMsg = extracted.requestId
    ? `${msg} (ID: ${extracted.requestId})`
    : msg;

  toastStore.getState().error(toastMsg);
}

/**
 * Specialized error handler for 403 Forbidden responses.
 */
export function onForbiddenError(error: unknown, _variables: unknown, _context: unknown) {
  const extracted = extractError(error);
  if (extracted.status === 403) {
    toastStore.getState().error(
      `Access denied: ${extracted.message}. Contact an administrator to request access.`,
    );
  } else {
    defaultOnError(error, _variables, _context);
  }
}
