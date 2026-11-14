import { useEffect, useRef } from "react";
import { useExecutionList } from "../api/queries";

export function useExecutionNotifications() {
  const { data } = useExecutionList();
  const knownStates = useRef<Record<string, string>>({});

  useEffect(() => {
    // Request notification permission on first user interaction.
    // Browsers require this to happen inside a user-gesture handler.
    if ("Notification" in globalThis && Notification.permission === "default") {
      const requestOnInteraction = () => {
        Notification.requestPermission();
        globalThis.removeEventListener("click", requestOnInteraction);
        globalThis.removeEventListener("keydown", requestOnInteraction);
      };
      globalThis.addEventListener("click", requestOnInteraction, { once: true });
      globalThis.addEventListener("keydown", requestOnInteraction, { once: true });
      return () => {
        globalThis.removeEventListener("click", requestOnInteraction);
        globalThis.removeEventListener("keydown", requestOnInteraction);
      };
    }
  }, []);

  useEffect(() => {
    if (!data?.executions) return;

    data.executions.forEach((exec: { id: string; status: string; pipeline_name: string }) => {
      const prevStatus = knownStates.current[exec.id];
      const currentStatus = exec.status;

      // Transitioned from active to finished
      if (prevStatus && (prevStatus === "running" || prevStatus === "pending")) {
        if (currentStatus === "success" || currentStatus === "failed" || currentStatus === "error") {
          const title = `Ducta Pipeline: ${exec.pipeline_name}`;
          const body = `Execution ${currentStatus.toUpperCase()}`;

          if ("Notification" in globalThis && Notification.permission === "granted") {
            try {
              new Notification(title, { body });
            } catch (e) {
              console.error("Failed to send desktop notification", e);
            }
          }
        }
      }

      knownStates.current[exec.id] = currentStatus;
    });
  }, [data]);
}
