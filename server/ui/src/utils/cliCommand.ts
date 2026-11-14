/**
 * Build the equivalent `ducta start` CLI command for a UI-triggered run.
 *
 * This reinforces CLI↔UI parity: anything launched from the UI can be reproduced
 * verbatim from a terminal. The command is meant to be run from the workspace/
 * source root (the UI's source directory), so no project/source flag is emitted —
 * the CLI discovers config relative to the working directory.
 *
 * Flags mirror the `start` subcommand in `src/ducta/cli/cli.py`.
 */

export interface StartCommandParams {
  pipelineName: string;
  env?: string;
  /** Single node to run (node-level execution). */
  nodeName?: string;
  startDate?: string;
  endDate?: string;
  dryRun?: boolean;
  validateOnly?: boolean;
}

/** Characters that are always safe unquoted in a POSIX shell argument. */
const SAFE_ARG = /^[A-Za-z0-9._\-/:]+$/;

/** Quote a value for safe pasting into a POSIX shell. */
export function shellQuote(value: string): string {
  if (value === "") return "''";
  if (SAFE_ARG.test(value)) return value;
  // Wrap in single quotes, escaping any embedded single quote.
  return `'${value.replace(/'/g, `'\\''`)}'`;
}

/**
 * Return the `ducta start …` command string equivalent to the given run.
 * Only flags with a value/enabled are emitted.
 */
export function buildStartCommand(params: StartCommandParams): string {
  const parts: string[] = ["ducta", "start"];

  parts.push("--pipeline", shellQuote(params.pipelineName));

  if (params.env) parts.push("--env", shellQuote(params.env));
  if (params.nodeName) parts.push("--node", shellQuote(params.nodeName));
  if (params.startDate) parts.push("--start-date", shellQuote(params.startDate));
  if (params.endDate) parts.push("--end-date", shellQuote(params.endDate));
  if (params.dryRun) parts.push("--dry-run");
  if (params.validateOnly) parts.push("--validate-only");

  return parts.join(" ");
}
