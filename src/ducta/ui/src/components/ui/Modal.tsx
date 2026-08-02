import { useRef, useCallback, useId, useEffect } from "react";
import type { ReactNode } from "react";
import { IconX } from "@tabler/icons-react";
import { useDialogA11y } from "../../hooks/useDialogA11y";
import "./Modal.css";

interface ModalProps {
  open?: boolean;
  title: string;
  children: ReactNode;
  onClose: () => void;
  width?: number;
  id?: string;
  ariaDescribedBy?: string;
}

/**
 * Modal Component - WCAG 2.1 AA Compliant
 *
 * Accessibility features:
 * - Focus trap (Tab cycles within modal)
 * - Keyboard navigation (Escape to close)
 * - aria-modal="true"
 * - aria-labelledby for title
 * - Body scroll lock during open
 */
export function Modal({
  open = true,
  title,
  children,
  onClose,
  width = 560,
  id,
  ariaDescribedBy,
}: ModalProps) {
  const generatedId = useId();
  const dialogId = id || `modal-${generatedId}`;
  const modalRef = useRef<HTMLDivElement>(null);

  // Escape-to-close, Tab focus trap, and focus restore on unmount.
  useDialogA11y(modalRef, onClose);

  // Lock body scroll while open.
  useEffect(() => {
    if (!open) return;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  const handleBackdropClick = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      if (event.target === event.currentTarget) {
        onClose();
      }
    },
    [onClose]
  );

  if (!open) return null;

  return (
    <div className="modal-overlay" onClick={handleBackdropClick}>
      <div
        className="modal"
        ref={modalRef}
        id={dialogId}
        tabIndex={-1}
        aria-labelledby={`${dialogId}-title`}
        aria-describedby={ariaDescribedBy}
        aria-modal="true"
        role="dialog"
        style={{ maxWidth: width, outline: "none" }}
      >
        <div className="modal-header">
          <h2 id={`${dialogId}-title`} className="modal-title">
            {title}
          </h2>
          <button
            className="modal-close"
            onClick={onClose}
            aria-label="Close modal"
          >
            <IconX size={20} />
          </button>
        </div>
        <div className="modal-content">{children}</div>
      </div>
    </div>
  );
}
