import React, { useEffect, useState, useRef } from "react";
import { colors, styles } from "../../theme/tokens";

export function PerfMonitor() {
  const [fps, setFps] = useState(0);
  const [latency, setLatency] = useState(0);
  const framesRef = useRef(0);
  const lastTimeRef = useRef(performance.now());
  const requestRef = useRef<number | null>(null);

  const isEnabled = import.meta.env.VITE_DEBUG_PERF === "true" || import.meta.env.DEV;

  useEffect(() => {
    if (!isEnabled) return;

    const loop = (time: number) => {
      framesRef.current++;
      if (time > lastTimeRef.current + 1000) {
        setFps(Math.round((framesRef.current * 1000) / (time - lastTimeRef.current)));
        setLatency(Math.round(1000 / ((framesRef.current * 1000) / (time - lastTimeRef.current))));
        framesRef.current = 0;
        lastTimeRef.current = time;
      }
      requestRef.current = requestAnimationFrame(loop);
    };

    requestRef.current = requestAnimationFrame(loop);
    return () => {
      if (requestRef.current) cancelAnimationFrame(requestRef.current);
    };
  }, [isEnabled]);

  if (!isEnabled) return null;

  return (
    <div
      style={{
        position: "fixed",
        bottom: 10,
        right: 10,
        background: "rgba(0,0,0,0.7)",
        color: fps < 30 ? colors.red : colors.green,
        padding: "2px 6px",
        borderRadius: 4,
        fontSize: 10,
        ...styles.fontMono,
        pointerEvents: "none",
        zIndex: 9999,
        border: `1px solid ${fps < 30 ? colors.redA30 : colors.greenA30}`,
        display: "flex",
        gap: 8,
      }}
    >
      <span>{fps} FPS</span>
      <span style={{ color: colors.textDim }}>{latency}ms/frame</span>
    </div>
  );
}
