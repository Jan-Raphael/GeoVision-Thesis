/**
 * The one dialog shell every popup in the app is built on.
 *
 * Before this, the backdrop, the Escape-to-close handler, and the panel
 * chrome were each hand-copied into four different files (the pairing modal,
 * the approval dialog, the report modal, the capture lightbox) — four
 * places that could quietly drift in behaviour or appearance. Centralising
 * it means Escape closes every dialog the same way, and a visual change here
 * reaches all four at once.
 */

import { useEffect } from 'react';

interface ModalProps {
  title?: string;
  /** Accessible label when there is no visible title (e.g. the lightbox). */
  ariaLabel?: string;
  onClose: () => void;
  children: React.ReactNode;
  /** `md` fits a form; `lg` fits the pairing QR; `xl` fits the lightbox. */
  size?: 'md' | 'lg' | 'xl';
  /** Clicking the backdrop closes the dialog. Off for flows mid-upload. */
  closeOnBackdrop?: boolean;
}

const SIZES: Record<NonNullable<ModalProps['size']>, string> = {
  md: 'max-w-md',
  lg: 'max-w-lg',
  xl: 'max-w-4xl',
};

export function Modal({
  title,
  ariaLabel,
  onClose,
  children,
  size = 'md',
  closeOnBackdrop = false,
}: ModalProps) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
    };
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 p-4 backdrop-blur-[1px]"
      role="dialog"
      aria-modal="true"
      aria-label={title ? undefined : ariaLabel}
      aria-labelledby={title ? 'modal-title' : undefined}
      onClick={closeOnBackdrop ? onClose : undefined}
    >
      <div
        className={`blueprint-frame max-h-[90vh] w-full overflow-y-auto rounded-lg border border-slate-200 bg-white shadow-2xl ${SIZES[size]}`}
        onClick={(event) => {
          event.stopPropagation();
        }}
      >
        {title && (
          <div className="flex items-start justify-between gap-4 border-b border-slate-100 bg-slate-50/60 px-6 py-4">
            <h2 id="modal-title" className="text-lg font-semibold tracking-tight text-slate-900">
              {title}
            </h2>
            <button
              type="button"
              onClick={onClose}
              className="rounded p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 focus:outline-none focus:ring-2 focus:ring-sky-500"
              aria-label="Close"
            >
              ✕
            </button>
          </div>
        )}
        <div className="p-6">{children}</div>
      </div>
    </div>
  );
}
