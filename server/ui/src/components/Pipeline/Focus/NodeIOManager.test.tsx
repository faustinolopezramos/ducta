import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { NodeInputsSection, NodeOutputsSection } from "./NodeIOManager";

describe("NodeInputsSection", () => {
  const sampleInputs = [
    { name: "bronze.orders", declared: true, alias: "orders_df" },
    { name: "bronze.customers", declared: true },
  ];

  it("renders inputs list and parameter aliases", () => {
    render(
      <NodeInputsSection
        inputs={sampleInputs}
        onSelectDataset={vi.fn()}
      />
    );

    expect(screen.getByText("bronze.orders")).toBeInTheDocument();
    expect(screen.getByText("orders_df")).toBeInTheDocument();
    expect(screen.getByText("bronze.customers")).toBeInTheDocument();
  });

  it("adds an input with dataset name and alias", () => {
    const onAddInput = vi.fn();
    render(
      <NodeInputsSection
        inputs={sampleInputs}
        onSelectDataset={vi.fn()}
        onAddInput={onAddInput}
        availableDatasets={["silver.products", "bronze.vendors"]}
      />
    );

    // Open add input form
    const addBtn = screen.getByRole("button", { name: "Add input dataset" });
    fireEvent.click(addBtn);

    const dsInput = screen.getByPlaceholderText("Dataset name...");
    const aliasInput = screen.getByPlaceholderText("Parameter alias (optional)...");

    fireEvent.change(dsInput, { target: { value: "silver.products" } });
    fireEvent.change(aliasInput, { target: { value: "products_df" } });

    const connectBtn = screen.getByRole("button", { name: /Connect/i });
    fireEvent.click(connectBtn);

    expect(onAddInput).toHaveBeenCalledWith("silver.products", "products_df");
  });

  it("triggers disconnect when clicking remove button", () => {
    const onDisconnect = vi.fn();
    render(
      <NodeInputsSection
        inputs={sampleInputs}
        onSelectDataset={vi.fn()}
        onDisconnect={onDisconnect}
      />
    );

    const removeBtn = screen.getByRole("button", { name: "Stop reading bronze.orders" });
    fireEvent.click(removeBtn);

    expect(onDisconnect).toHaveBeenCalledWith("bronze.orders");
  });
});

describe("NodeOutputsSection", () => {
  const sampleOutputs = [
    { name: "silver.clean_orders", declared: true, format: "parquet" },
  ];

  it("renders outputs list", () => {
    render(
      <NodeOutputsSection
        outputs={sampleOutputs}
        onSelectDataset={vi.fn()}
        nodeName="clean_orders_node"
      />
    );

    expect(screen.getByText("silver.clean_orders")).toBeInTheDocument();
  });

  it("adds an output with dataset name and format", () => {
    const onAddOutput = vi.fn();
    render(
      <NodeOutputsSection
        outputs={sampleOutputs}
        onSelectDataset={vi.fn()}
        onAddOutput={onAddOutput}
        nodeName="clean_orders_node"
      />
    );

    const addBtn = screen.getByRole("button", { name: "Add output dataset" });
    fireEvent.click(addBtn);

    const dsInput = screen.getByPlaceholderText(/Dataset name/i);
    fireEvent.change(dsInput, { target: { value: "silver.orders_summary" } });

    const formatSelect = screen.getByLabelText("Dataset format");
    fireEvent.change(formatSelect, { target: { value: "delta" } });

    const addOutputBtn = screen.getByRole("button", { name: /^Add Output$/i });
    fireEvent.click(addOutputBtn);

    expect(onAddOutput).toHaveBeenCalledWith("silver.orders_summary", { format: "delta" });
  });

  it("triggers remove output when clicking remove button", () => {
    const onRemoveOutput = vi.fn();
    render(
      <NodeOutputsSection
        outputs={sampleOutputs}
        onSelectDataset={vi.fn()}
        onRemoveOutput={onRemoveOutput}
        nodeName="clean_orders_node"
      />
    );

    const removeBtn = screen.getByRole("button", { name: "Remove output silver.clean_orders" });
    fireEvent.click(removeBtn);

    expect(onRemoveOutput).toHaveBeenCalledWith("silver.clean_orders");
  });
});
