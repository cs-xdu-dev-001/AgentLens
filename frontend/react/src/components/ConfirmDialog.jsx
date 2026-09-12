import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

export function ConfirmDialog({
  open = false,
  title,
  description,
  confirmLabel = "确认",
  cancelLabel = "取消",
  danger = false,
  busy = false,
  onConfirm,
  onCancel,
}) {
  const dialogRef = useRef(null);
  const confirmRef = useRef(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return undefined;
    if (open && !dialog.open) {
      dialog.showModal();
      window.requestAnimationFrame(() => confirmRef.current?.focus());
    } else if (!open && dialog.open) {
      dialog.close();
    }
    return undefined;
  }, [open]);

  if (!open) return null;

  return createPortal(
    <dialog
      ref={dialogRef}
      className={`confirm-dialog${danger ? " is-danger" : ""}`}
      aria-labelledby="confirm-dialog-title"
      aria-describedby={description ? "confirm-dialog-description" : undefined}
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onCancel?.();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget && !busy) onCancel?.();
      }}
    >
      <div className="confirm-dialog-surface">
        <div className="confirm-dialog-copy">
          <h2 id="confirm-dialog-title">{title}</h2>
          {description ? (
            <p id="confirm-dialog-description">{description}</p>
          ) : null}
        </div>
        <div className="confirm-dialog-actions">
          <button type="button" disabled={busy} onClick={() => onCancel?.()}>
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            className={danger ? "danger" : "primary"}
            type="button"
            disabled={busy}
            onClick={() => onConfirm?.()}
          >
            {busy ? "处理中..." : confirmLabel}
          </button>
        </div>
      </div>
    </dialog>,
    document.body,
  );
}
