/** How dangerous an environment is to run in, from its name. Drives colour and confirmations. */
export type EnvKind = "prod" | "staging" | "dev" | "base";

const PROD = /^(prod|production|prd|live)$/i;
const STAGING = /^(staging|stage|stg|sandbox|preprod|pre-prod|qa|uat|test)$/i;

export function envKind(env: string | null | undefined): EnvKind {
  if (!env || env === "base") return "base";
  if (PROD.test(env)) return "prod";
  if (STAGING.test(env)) return "staging";
  return "dev";
}
