import React, { useRef, useEffect, useState } from "react";
import { TerminalStatus } from "../../hooks/useWebTerminal";
import { AnsiText } from "../Execution/AnsiText";

interface WebTerminalProps {
  output: string;
  status: TerminalStatus;
  onSendInput: (data: string) => void;
  onClear: () => void;
}

export function WebTerminal({ output, status, onSendInput, onClear }: WebTerminalProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [currentLine, setCurrentLine] = useState("");

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [output]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      onSendInput(currentLine + "\r");
      setCurrentLine("");
    } else if (e.key === "c" && e.ctrlKey) {
      onSendInput("\x03");
      setCurrentLine("");
    } else if (e.key === "l" && e.ctrlKey) {
      e.preventDefault();
      onClear();
    }
  };

  return (
    // Clicking anywhere in the terminal chrome just hands focus to the input
    // below, which owns the keystrokes — there is no separate action to bind a
    // key to, so this is a focus shim rather than a control.
    <div
      role="presentation"
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        backgroundColor: "var(--surface-elevated)",
        color: "var(--text)",
        fontFamily: "var(--font-mono)",
        borderRadius: 8,
        border: "1px solid var(--border)",
        overflow: "hidden",
      }}
      onClick={() => inputRef.current?.focus()}
    >
      <div
        ref={containerRef}
        style={{
          flex: 1,
          padding: 16,
          overflowY: "auto",
          whiteSpace: "pre-wrap",
          wordBreak: "break-all",
          fontSize: 13,
          lineHeight: 1.5,
        }}
      >
        <AnsiText text={output} />
      </div>

      {status === "connected" && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            padding: "8px 16px",
            background: "var(--surface)",
            borderTop: "1px solid var(--border)",
          }}
        >
          <span style={{ color: "var(--success)", marginRight: 8, fontWeight: "bold" }}>$</span>
          <input
            ref={inputRef}
            type="text"
            value={currentLine}
            onChange={(e) => setCurrentLine(e.target.value)}
            onKeyDown={handleKeyDown}
            // eslint-disable-next-line jsx-a11y/no-autofocus -- a terminal that does not take the caret is unusable.
            autoFocus
            style={{
              flex: 1,
              background: "transparent",
              border: "none",
              outline: "none",
              color: "var(--text)",
              fontFamily: "inherit",
              fontSize: 13,
            }}
            placeholder="Type command..."
          />
        </div>
      )}
    </div>
  );
}
