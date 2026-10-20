import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ConnectionModal } from "./ConnectionModal";

describe("ConnectionModal", () => {
  it("renders source and target node information and available outputs", () => {
    render(
      <ConnectionModal
        open={true}
        onClose={vi.fn()}
        sourceNode="ingest_orders"
        targetNode="clean_orders"
        availableOutputs={["bronze.orders", "bronze.audit"]}
        targetInputs={["bronze.customers"]}
        onConnect={vi.fn()}
        onConnectAll={vi.fn()}
      />
    );

    expect(screen.getByText("Connect Nodes")).toBeInTheDocument();
    expect(screen.getAllByText("ingest_orders").length).toBeGreaterThan(0);
    expect(screen.getAllByText("clean_orders").length).toBeGreaterThan(0);
    expect(screen.getAllByText("bronze.orders").length).toBeGreaterThan(0);
    expect(screen.getByText("bronze.audit")).toBeInTheDocument();
    expect(screen.getByText("Already reading: bronze.customers")).toBeInTheDocument();
  });

  it("allows selecting a specific output and connects with alias", () => {
    const onConnect = vi.fn();
    const onClose = vi.fn();

    render(
      <ConnectionModal
        open={true}
        onClose={onClose}
        sourceNode="ingest_orders"
        targetNode="clean_orders"
        availableOutputs={["bronze.orders", "bronze.audit"]}
        onConnect={onConnect}
      />
    );

    // Select second output
    const auditBtn = screen.getByRole("radio", { name: "bronze.audit" });
    fireEvent.click(auditBtn);

    // Change alias
    const aliasInput = screen.getByLabelText(/Target Function Parameter Alias/i);
    fireEvent.change(aliasInput, { target: { value: "audit_log" } });

    // Click Connect
    const connectBtn = screen.getByRole("button", { name: /^Connect$/i });
    fireEvent.click(connectBtn);

    expect(onConnect).toHaveBeenCalledWith("bronze.audit", "audit_log");
    expect(onClose).toHaveBeenCalled();
  });

  it("calls onConnectAll when Connect All is clicked", () => {
    const onConnectAll = vi.fn();
    const onClose = vi.fn();

    render(
      <ConnectionModal
        open={true}
        onClose={onClose}
        sourceNode="ingest_orders"
        targetNode="clean_orders"
        availableOutputs={["bronze.orders", "bronze.audit"]}
        onConnect={vi.fn()}
        onConnectAll={onConnectAll}
      />
    );

    const connectAllBtn = screen.getByRole("button", { name: "Connect all (2)" });
    fireEvent.click(connectAllBtn);

    expect(onConnectAll).toHaveBeenCalledWith(["bronze.orders", "bronze.audit"]);
    expect(onClose).toHaveBeenCalled();
  });
});
