import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useEditorBuffer } from "./useEditorBuffer";

type Props = { value: string; file?: string; draft?: string };

const setup = (initial: Props) =>
  renderHook(({ value, file, draft }: Props) => useEditorBuffer(value, file, draft), { initialProps: initial });

describe("useEditorBuffer", () => {
  it("starts a new buffer for another file even when the content is the same", () => {
    const { result, rerender } = setup({ value: "", file: "a/__init__.py" });
    act(() => result.current.setText("import x\n"));
    expect(result.current.isDirty).toBe(true);

    rerender({ value: "", file: "b/__init__.py" });
    expect(result.current.text).toBe("");
    expect(result.current.isDirty).toBe(false);
  });

  it("restores a draft when a file is opened again", () => {
    const { result } = setup({ value: "a = 1\n", file: "a.py", draft: "a = 2\n" });
    expect(result.current.text).toBe("a = 2\n");
    expect(result.current.isDirty).toBe(true);
  });

  it("keeps what was typed while a save was on its way", () => {
    const { result, rerender } = setup({ value: "v1", file: "a.py" });
    act(() => result.current.setText("v2"));
    act(() => result.current.markSaved("v2"));
    expect(result.current.isDirty).toBe(false);

    // Still the old content until the refetch lands: the buffer stays.
    rerender({ value: "v1", file: "a.py" });
    expect(result.current.text).toBe("v2");

    act(() => result.current.setText("v2 and more"));
    rerender({ value: "v2", file: "a.py" });
    expect(result.current.text).toBe("v2 and more");
    expect(result.current.isDirty).toBe(true);
  });

  it("takes other new content for the same file", () => {
    const { result, rerender } = setup({ value: "v1", file: "a.py" });
    rerender({ value: "changed on disk", file: "a.py" });
    expect(result.current.text).toBe("changed on disk");
    expect(result.current.isDirty).toBe(false);
  });

  it("reads unsaved again when the save fails", async () => {
    const { result } = setup({ value: "v1", file: "a.py" });
    act(() => result.current.setText("v2"));
    const failed = Promise.reject(new Error("409"));
    await act(async () => {
      result.current.markSaved("v2", failed);
      await failed.catch(() => {});
    });
    expect(result.current.text).toBe("v2");
    expect(result.current.isDirty).toBe(true);
  });

  it("reverts to the file as loaded", () => {
    const { result } = setup({ value: "v1", file: "a.py" });
    act(() => result.current.setText("v2"));
    act(() => result.current.revert());
    expect(result.current.text).toBe("v1");
    expect(result.current.isDirty).toBe(false);
  });
});
