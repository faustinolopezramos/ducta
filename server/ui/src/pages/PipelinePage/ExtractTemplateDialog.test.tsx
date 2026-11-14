import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ExtractTemplateDialog } from "./ExtractTemplateDialog";

describe("ExtractTemplateDialog", () => {
  it("suggests a name from the node and sends the parameters", () => {
    const onExtract = vi.fn();
    render(<ExtractTemplateDialog node="silver.clean_student" onExtract={onExtract} onCancel={() => {}} />);
    expect(screen.getByLabelText(/Template name/)).toHaveValue("clean_student");
    fireEvent.change(screen.getByLabelText(/Parameters/), { target: { value: "run, timeout_seconds" } });
    fireEvent.click(screen.getByRole("button", { name: "Make template" }));
    expect(onExtract).toHaveBeenCalledWith("clean_student", ["run", "timeout_seconds"]);
  });

  it("refuses a name that is not a file name", () => {
    render(<ExtractTemplateDialog node="x" onExtract={() => {}} onCancel={() => {}} />);
    fireEvent.change(screen.getByLabelText(/Template name/), { target: { value: "a/b" } });
    expect(screen.getByRole("button", { name: "Make template" })).toBeDisabled();
  });
});
