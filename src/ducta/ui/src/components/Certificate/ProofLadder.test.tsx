import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ProofLadder } from "./ProofLadder";
import type { CertificateVerifyResult } from "../../api/certificatesApi";

function verify(overrides: Partial<CertificateVerifyResult>): CertificateVerifyResult {
  return { ok: true, run_id: "run-1", reason: "hash matches — untampered", signature: "unsigned", ...overrides };
}

describe("ProofLadder", () => {
  it("shows a pending state before verification runs", () => {
    render(<ProofLadder verify={null} reproduce={{ status: "idle" }} />);
    expect(screen.getByText("Not yet verified")).toBeInTheDocument();
  });

  it("reads as verified when signed and valid", () => {
    render(<ProofLadder verify={verify({ signature: "valid", reason: "hash matches and signature valid" })} reproduce={{ status: "idle" }} />);
    expect(screen.getByText("Verified — signed and untampered")).toBeInTheDocument();
  });

  it("treats unsigned as untampered, not as a failure", () => {
    render(<ProofLadder verify={verify({ signature: "unsigned" })} reproduce={{ status: "idle" }} />);
    expect(screen.getByText("Untampered — not signed")).toBeInTheDocument();
    expect(screen.getByText("This certificate was never signed.")).toBeInTheDocument();
  });

  it("flags a signed-but-unkeyed certificate as a weaker pass, not a plain valid", () => {
    render(
      <ProofLadder
        verify={verify({ ok: true, signature: "present (no key)", reason: "hash matches — untampered (signed; no key provided to verify signature)" })}
        reproduce={{ status: "idle" }}
      />
    );
    expect(screen.getByText("Untampered — signed, no key to check it")).toBeInTheDocument();
  });

  it("reports a stripped signature as tampering", () => {
    render(
      <ProofLadder
        verify={verify({ ok: false, signature: "stripped", reason: "certificate declares signed=true but carries no signature — the signature was removed" })}
        reproduce={{ status: "idle" }}
      />
    );
    expect(screen.getByText("Tampered — signature was removed")).toBeInTheDocument();
  });

  it("reports a hash mismatch as tampering, distinct from a signature failure", () => {
    render(
      <ProofLadder
        verify={verify({ ok: false, signature: "unsigned", reason: "hash mismatch — certificate was modified (stored a, recomputed b)" })}
        reproduce={{ status: "idle" }}
      />
    );
    expect(screen.getByText("Hash mismatch — certificate was modified")).toBeInTheDocument();
  });

  it("shows reproducibility as unavailable in standalone mode", () => {
    render(<ProofLadder verify={verify({})} reproduce={{ status: "unavailable" }} />);
    expect(screen.getByText("Not available — no local execution to re-run.")).toBeInTheDocument();
  });

  it("compact mode omits the hero and inline actions", () => {
    render(<ProofLadder compact verify={verify({ signature: "valid" })} reproduce={{ status: "idle" }} onVerify={() => {}} />);
    expect(screen.queryByText("Verified — signed and untampered")).not.toBeInTheDocument();
    expect(screen.queryByText("Re-verify")).not.toBeInTheDocument();
  });
});
