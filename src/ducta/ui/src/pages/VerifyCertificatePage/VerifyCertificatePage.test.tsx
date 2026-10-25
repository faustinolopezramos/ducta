import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { VerifyCertificatePage } from "./index";

vi.mock("../../api/certificatesApi", () => ({
  useVerifyCertificateStandalone: () => ({ mutate: vi.fn(), data: undefined, isPending: false }),
}));

describe("Verify a certificate", () => {
  it("shows the signing key as an optional disclosure", () => {
    render(
      <MemoryRouter>
        <VerifyCertificatePage />
      </MemoryRouter>
    );
    const toggle = screen.getByRole("button", { name: "Signing key (optional)" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByLabelText("Signing key")).toBeInTheDocument();
  });

  it("opens with the certificate loaded and the key field showing, from a certificate's 'Check with key'", () => {
    render(
      <MemoryRouter initialEntries={[{ pathname: "/verify-certificate", state: { certificateJson: '{"run_id":"r1"}', withKey: true } }]}>
        <VerifyCertificatePage />
      </MemoryRouter>
    );
    expect(screen.getByDisplayValue('{"run_id":"r1"}')).toBeInTheDocument();
    expect(screen.getByLabelText("Signing key")).toBeInTheDocument();
  });
});
