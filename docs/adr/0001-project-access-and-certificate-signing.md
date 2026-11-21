# ADR-0001: Per-project access and asymmetric certificate signing

**Status:** Proposed. Nothing is implemented; the decision is the maintainer's.
**Date:** 2026-11-20
**Origin:** the 2026-11-20 security review for enterprise deployments.

## Context

Ducta's API server is meant to run in companies that handle critical data. The
2026-11-20 review fixed the proven flaws: code execution through
`quality/failing-rows`, the signing key reaching runs, secrets in git diffs,
prod rows and `metadata.pii` columns shown to every role, unredacted run logs
and the debug-run environment. Two limits are by design and remain:

1. **Permissions are global.** A role applies to every project in the
   workspace. A `viewer` of the marketing project also reads the finance
   project, and a `developer` of one can run code in all of them. Companies
   usually separate teams by project or domain.
2. **Certificates use HMAC (a shared key).** The server now signs them, and the
   key no longer reaches a run. But HMAC uses one key for both signing and
   verifying: an auditor who verifies a certificate can also forge one. An
   external auditor therefore has to trust the server, or receive a key that
   lets them sign.

## Decision (proposed)

Do both, in this order, each as a separate change:

- **A. Per-project roles.** A membership table `(user, project, role)` next to
  the global role. A user's effective permissions on project P are their global
  role plus their role in P. Routes with a `project_id` check P; listing
  projects shows only the user's projects. An admin keeps `*` everywhere.
  Without memberships everything works as today (backward compatible).
- **B. Ed25519 signatures.** A new `signature_alg: ed25519`. The server signs
  with a private key (`DUCTA_CERTIFICATE_PRIVATE_KEY`, a PEM file).
  `ducta certify verify --public-key` verifies with the public key, which can be
  published. HMAC stays as the default and for existing certificates. It needs
  `cryptography`, which is not a declared dependency today; it would be an
  optional extra, `ducta[signing]`.

## Options considered

### A1. Per-project roles in the server's database (recommended)

| Dimension | Assessment |
|---|---|
| Complexity | Medium: a table, a dependency on every `project_id` route, CLI `ducta-server user grant` |
| Cost | No new services |
| Scalability | Good up to hundreds of projects and users |
| Familiarity | Same model as today's roles |

**Pros:** separates teams; keeps the four roles; the RBAC test
(`tests/server/test_rbac.py`) can enumerate routes per project.
**Cons:** every new route must take the project into account; the workspace
file and git routes have no `project_id` (they work on paths) and need mapping
from path to project.

### A2. Delegate to an IdP (OIDC groups → roles)

**Pros:** companies manage access in their IdP; offboarding happens there.
**Cons:** a large dependency (OIDC flow, token validation, group mapping) for
an alpha project maintained by one person. It does not replace A1: groups still
have to map to projects. Revisit after A1.

### A3. One server per team

**Pros:** zero code; complete isolation (processes, files, keys).
**Cons:** operations multiply; no cross-project view. This is the recommended
interim measure and should be written into the deployment guide meanwhile.

### B1. Ed25519 (recommended) vs B2. keep HMAC

| Dimension | Ed25519 | HMAC |
|---|---|---|
| Who can forge | only the holder of the private key (the server) | anyone holding the key, verifiers included |
| Public verification | yes, with a public key | no |
| Cost | medium: new field, CLI flag, key rotation by `key_id` | none |

## Trade-offs

- A1 adds a check to roughly 150 routes. The risk is forgetting one. The RBAC
  test should fail for any `project_id` route without the dependency, just as
  it already fails for a write route a viewer can reach.
- B1 keeps backward compatibility only if `verify` dispatches on
  `signature_alg`. Old certificates (HMAC) keep verifying with the old key.

## Consequences

- **Easier:** an auditor verifies without being able to sign; one server
  serves several teams.
- **Harder:** creating projects needs an owner; tests and the UI must learn
  memberships (UI changes need a mockup first).
- **To revisit:** OIDC (A2) once A1 exists; storing the private key in a KMS.

## Action items (only on approval)

1. [ ] A3 now: document "one server per team" in the deployment guide.
2. [ ] A1: memberships, a project-aware dependency, CLI `grant`/`revoke`, and an
   RBAC test per project.
3. [ ] B1: `signature_alg`, `DUCTA_CERTIFICATE_PRIVATE_KEY`, `certify verify
   --public-key`, and rotation by `key_id`.
