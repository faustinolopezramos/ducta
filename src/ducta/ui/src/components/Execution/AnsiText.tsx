import React from "react";

const ANSI_COLORS: Record<string, string> = {
  // Standard colors (30-37)
  "30": "#000000",
  "31": "#ff5555", // Red
  "32": "#50fa7b", // Green
  "33": "#f1fa8c", // Yellow
  "34": "#8be9fd", // Blue (Changed to Cyan for better terminal look)
  "35": "#ff79c6", // Magenta
  "36": "#8be9fd", // Cyan
  "37": "#f8f8f2", // White
  // High intensity colors (90-97)
  "90": "#6272a4", // Gray
  "91": "#ff6e6e", // Bright Red
  "92": "#69ff94", // Bright Green
  "93": "#ffffa5", // Bright Yellow
  "94": "#d6acff", // Bright Blue
  "95": "#ff92df", // Bright Magenta
  "96": "#a4ffff", // Bright Cyan
  "97": "#ffffff", // Bright White
};

export function AnsiText({ text }: { text: string }) {
  if (!text.includes("\u001b[")) return <>{text}</>;

  const parts = text.split(/\u001b\[(\d+(?:;\d+)*)m/);
  const result: React.ReactNode[] = [];
  let currentColor: string | undefined;
  let isBold = false;
  let isDim = false;

  for (let i = 0; i < parts.length; i++) {
    if (i % 2 === 1) {
      // Escape sequence
      const codes = parts[i].split(";");
      for (const code of codes) {
        if (code === "0") {
          currentColor = undefined;
          isBold = false;
          isDim = false;
        } else if (code === "1") {
          isBold = true;
          isDim = false;
        } else if (code === "2") {
          isDim = true;
          isBold = false;
        } else if (ANSI_COLORS[code]) {
          currentColor = ANSI_COLORS[code];
        }
      }
    } else {
      // Text content
      const content = parts[i];
      if (content) {
        result.push(
          <span
            key={i}
            style={{
              color: currentColor,
              fontWeight: isBold ? "bold" : "normal",
              opacity: isDim ? 0.6 : 1,
            }}
          >
            {content}
          </span>
        );
      }
    }
  }

  return <>{result}</>;
}
