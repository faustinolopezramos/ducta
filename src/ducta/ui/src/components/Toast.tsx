// ─────────────────────────────────────────────
// TOAST NOTIFICATION COMPONENTS
// ─────────────────────────────────────────────

import React, { useEffect } from 'react';
import { IconCheck, IconX, IconAlertTriangle, IconInfoCircle } from "@tabler/icons-react";
import "./Toast.css";

export interface ToastProps {
  id: string;
  message: string;
  type?: 'success' | 'error' | 'warn' | 'info';
  duration?: number;
  /** A button on the toast, e.g. "Undo". Clicking it also dismisses the toast. */
  action?: { label: string; onClick: () => void };
  onDismiss: (id: string) => void;
}

const TOAST_CONFIG: Record<string, { icon: React.ReactNode }> = {
  success: { icon: <IconCheck size={18} /> },
  error: { icon: <IconX size={18} /> },
  warn: { icon: <IconAlertTriangle size={18} /> },
  info: { icon: <IconInfoCircle size={18} /> },
};

/**
 * Individual Toast Component
 */
export function Toast({ id, message, type = 'info', duration, action, onDismiss }: Readonly<ToastProps>) {
  useEffect(() => {
    if (duration && duration > 0) {
      const timer = setTimeout(() => onDismiss(id), duration);
      return () => clearTimeout(timer);
    }
  }, [id, duration, onDismiss]);

  const cfg = TOAST_CONFIG[type] || TOAST_CONFIG.info;
  const isErrorToast = type === "error" || type === "warn";

  const cls = ["toast", `toast--${type}`, isErrorToast ? "toast--error" : ""].filter(Boolean).join(" ");

  return (
    <div
      role={isErrorToast ? "alert" : "status"}
      aria-live={isErrorToast ? "assertive" : "polite"}
      aria-atomic="true"
      className={cls}
    >
      <span className="toast__icon">{cfg.icon}</span>
      <span className="toast__body">{message}</span>
      {action && (
        <button
          type="button"
          className="toast__action"
          onClick={() => {
            action.onClick();
            onDismiss(id);
          }}
        >
          {action.label}
        </button>
      )}
      <button
        onClick={() => onDismiss(id)}
        aria-label="Dismiss notification"
        title="Dismiss notification"
        className="toast__close"
      >
        ✕
      </button>
    </div>
  );
}

export interface ToastContainerProps {
  toasts: Omit<ToastProps, 'onDismiss'>[];
  onDismiss: (id: string) => void;
}

/**
 * Toast Container - Place this at root level
 */
export function ToastContainer({ toasts, onDismiss }: Readonly<ToastContainerProps>) {
  return (
    <div className="toast-container">
      {toasts.map(toast => (
        <div key={toast.id}>
          <Toast
            {...toast}
            onDismiss={onDismiss}
          />
        </div>
      ))}
    </div>
  );
}
