import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Toast, ToastContainer } from "./Toast";

describe("Toast", () => {
  it("renders message text", () => {
    render(<Toast id="t1" message="Hello" type="info" duration={0} onDismiss={vi.fn()} />);
    expect(screen.getByText("Hello")).toBeInTheDocument();
  });

  it("has role alert for error type", () => {
    render(<Toast id="t2" message="Error" type="error" duration={0} onDismiss={vi.fn()} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("has role status for info type", () => {
    render(<Toast id="t3" message="Info" type="info" duration={0} onDismiss={vi.fn()} />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("calls onDismiss when close button is clicked", () => {
    const onDismiss = vi.fn();
    render(<Toast id="t4" message="Close me" type="info" duration={0} onDismiss={onDismiss} />);
    fireEvent.click(screen.getByLabelText("Dismiss notification"));
    expect(onDismiss).toHaveBeenCalledWith("t4");
  });

  it("auto-dismisses after duration", () => {
    vi.useFakeTimers();
    const onDismiss = vi.fn();
    render(<Toast id="t5" message="Auto" type="info" duration={1000} onDismiss={onDismiss} />);
    expect(onDismiss).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1000);
    expect(onDismiss).toHaveBeenCalledWith("t5");
    vi.useRealTimers();
  });
});

describe("ToastContainer", () => {
  it("renders multiple toasts", () => {
    const toasts = [
      { id: "a", message: "First", type: "info" as const, duration: 0, createdAt: 1 },
      { id: "b", message: "Second", type: "error" as const, duration: 0, createdAt: 2 },
    ];
    render(<ToastContainer toasts={toasts} onDismiss={vi.fn()} />);
    expect(screen.getByText("First")).toBeInTheDocument();
    expect(screen.getByText("Second")).toBeInTheDocument();
  });
});
