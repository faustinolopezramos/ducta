import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfirmDialog } from "./ConfirmDialog";
import { ActionButton } from "./ActionButton";

describe("ConfirmDialog", () => {
  const base = {
    open: true,
    title: "Delete run 3f9a2c?",
    onConfirm: vi.fn(),
    onCancel: vi.fn(),
  };

  it("renders nothing when closed", () => {
    render(<ConfirmDialog {...base} open={false} />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("is a modal dialog labelled by its title", () => {
    render(<ConfirmDialog {...base} />);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleName("Delete run 3f9a2c?");
  });

  it("confirms and cancels through their buttons", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(<ConfirmDialog {...base} onConfirm={onConfirm} onCancel={onCancel} />);

    await user.click(screen.getByRole("button", { name: "Confirm" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("cancels on Escape", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(<ConfirmDialog {...base} onCancel={onCancel} />);

    await user.keyboard("{Escape}");

    expect(onCancel).toHaveBeenCalled();
  });

  it("puts focus on the confirm button so Enter is the obvious next step", () => {
    render(<ConfirmDialog {...base} />);
    expect(screen.getByRole("button", { name: "Confirm" })).toHaveFocus();
  });

  describe("typed confirmation", () => {
    it("keeps confirm disabled until the text matches exactly", async () => {
      const user = userEvent.setup();
      render(<ConfirmDialog {...base} requireTyping="v7" confirmLabel="Delete version" />);

      const confirm = screen.getByRole("button", { name: "Delete version" });
      expect(confirm).toBeDisabled();

      await user.type(screen.getByRole("textbox"), "v");
      expect(confirm).toBeDisabled();

      await user.type(screen.getByRole("textbox"), "7");
      expect(confirm).toBeEnabled();
    });

    it("focuses the input rather than the confirm button", () => {
      render(<ConfirmDialog {...base} requireTyping="v7" />);
      expect(screen.getByRole("textbox")).toHaveFocus();
    });

    it("clears what was typed between openings", async () => {
      const user = userEvent.setup();
      const { rerender } = render(<ConfirmDialog {...base} requireTyping="v7" />);
      await user.type(screen.getByRole("textbox"), "v7");

      rerender(<ConfirmDialog {...base} requireTyping="v7" open={false} />);
      rerender(<ConfirmDialog {...base} requireTyping="v7" open />);

      expect(screen.getByRole("textbox")).toHaveValue("");
    });
  });
});

describe("ActionButton confirmation", () => {
  it("asks in-app instead of through window.confirm", async () => {
    // The regression this replaces: the native dialog cannot be styled, gives
    // every action the same weight, and can be suppressed by the browser — at
    // which point the destructive action runs unconfirmed.
    const user = userEvent.setup();
    const nativeConfirm = vi.spyOn(window, "confirm");
    const onAction = vi.fn();

    render(
      <ActionButton confirm="Delete this?" onAction={onAction}>
        Delete
      </ActionButton>
    );
    await user.click(screen.getByRole("button", { name: "Delete" }));

    expect(nativeConfirm).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(onAction).not.toHaveBeenCalled();

    nativeConfirm.mockRestore();
  });

  it("runs the action only after the dialog is confirmed", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();

    render(
      <ActionButton confirm="Delete this?" onAction={onAction}>
        Delete
      </ActionButton>
    );
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Confirm" }));

    expect(onAction).toHaveBeenCalledTimes(1);
  });

  it("does not run the action when cancelled", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();

    render(
      <ActionButton confirm="Delete this?" onAction={onAction}>
        Delete
      </ActionButton>
    );
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onAction).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("runs immediately when no confirmation is configured", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();

    render(<ActionButton onAction={onAction}>Run</ActionButton>);
    await user.click(screen.getByRole("button", { name: "Run" }));

    expect(onAction).toHaveBeenCalledTimes(1);
  });

  it("labels a destructive confirmation as such", async () => {
    const user = userEvent.setup();
    render(
      <ActionButton
        confirm={{ title: "Delete connection?", tone: "danger" }}
        onAction={vi.fn()}
      >
        Delete
      </ActionButton>
    );
    await user.click(screen.getByRole("button", { name: "Delete" }));

    // A danger-toned confirmation defaults its action label to "Delete".
    expect(screen.getAllByRole("button", { name: "Delete" }).length).toBeGreaterThan(1);
  });
});
