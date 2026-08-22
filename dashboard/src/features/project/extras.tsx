/**
 * The three remaining folder pieces: the capture lightbox, the report modal,
 * and blueprint upload.
 *
 * The lightbox is where the system finally shows its working — the photograph,
 * the stage the model chose, its confidence, the runner-up, and the boxes the
 * detector drew. Normalised coordinates make that overlay possible at any size:
 * a box stored in pixels would be right on exactly one rendering and silently
 * wrong everywhere else.
 */

import { useState } from 'react';

import { Coordinates, EmptyState, ErrorState, RelativeTime } from '@/components/common';
import { Modal } from '@/components/modal';
import { useImageDetail, useRequestReport, useUploadAsset, type Asset } from '@/lib/owner';

// ---------------------------------------------------------------------------
// Capture lightbox
// ---------------------------------------------------------------------------

export function CaptureLightbox({
  projectId,
  imageId,
  onClose,
}: {
  projectId: string;
  imageId: string;
  onClose: () => void;
}) {
  const detail = useImageDetail(projectId, imageId);
  const [showBoxes, setShowBoxes] = useState(true);

  return (
    <Modal
      title={detail.data?.filename ?? 'Capture'}
      onClose={onClose}
      size="xl"
      closeOnBackdrop
    >
      {detail.isPending && <div className="h-80 animate-pulse rounded-lg bg-slate-200" />}
      {detail.isError && (
        <ErrorState title="Could not load this capture" message={detail.error.message} />
      )}

      {detail.isSuccess && (
        <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_16rem]">
          <div>
            <div className="relative overflow-hidden rounded-lg border border-slate-200 bg-slate-100">
              {detail.data.original_url ? (
                <img
                  src={detail.data.original_url}
                  alt={`Capture taken ${new Date(detail.data.captured_at).toLocaleString()}`}
                  className="w-full"
                />
              ) : (
                <div className="flex h-64 items-center justify-center text-sm text-slate-400">
                  Image unavailable
                </div>
              )}

              {showBoxes &&
                detail.data.detections.map((box, index) => (
                  <div
                    key={`${box.class_name}-${String(index)}`}
                    // Percentages, because the boxes are normalised — the same
                    // numbers land correctly on a thumbnail and on the
                    // full-resolution original.
                    style={{
                      left: `${String(box.bbox.x * 100)}%`,
                      top: `${String(box.bbox.y * 100)}%`,
                      width: `${String(box.bbox.width * 100)}%`,
                      height: `${String(box.bbox.height * 100)}%`,
                    }}
                    className="pointer-events-none absolute border-2 border-sky-400"
                  >
                    <span className="absolute -top-5 left-0 whitespace-nowrap rounded bg-sky-500 px-1 text-[10px] font-medium text-white">
                      {box.class_name} {(box.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                ))}
            </div>

            {detail.data.detections.length > 0 && (
              <label className="mt-2 flex items-center gap-2 text-sm text-slate-600">
                <input
                  type="checkbox"
                  checked={showBoxes}
                  onChange={(event) => {
                    setShowBoxes(event.target.checked);
                  }}
                  className="h-4 w-4 rounded border-slate-300"
                />
                Show detections ({detail.data.detections.length})
              </label>
            )}
          </div>

          <div className="flex flex-col gap-4 text-sm">
            <div>
              <p className="text-xs uppercase tracking-wide text-slate-500">Captured</p>
              <p className="text-slate-800">
                <RelativeTime value={detail.data.captured_at} />
              </p>
            </div>

            {detail.data.prediction ? (
              <div>
                <p className="text-xs uppercase tracking-wide text-slate-500">AI estimate</p>
                <p className="text-lg font-semibold text-slate-900">
                  {detail.data.prediction.stage}
                </p>
                <p className="text-slate-600">
                  {(detail.data.prediction.confidence * 100).toFixed(0)}% confidence
                </p>
                {detail.data.prediction.low_confidence && (
                  <p className="mt-1 rounded bg-amber-50 px-2 py-1 text-xs text-amber-900">
                    Below the confidence gate — excluded from the progress figure.
                  </p>
                )}
                <details className="mt-2">
                  <summary className="cursor-pointer text-xs text-slate-500">
                    All class probabilities
                  </summary>
                  <ul className="mt-1 space-y-0.5 text-xs">
                    {Object.entries(detail.data.prediction.class_probabilities)
                      .sort(([, a], [, b]) => b - a)
                      .slice(0, 5)
                      .map(([name, value]) => (
                        <li key={name} className="flex justify-between gap-2">
                          <span className="text-slate-600">{name}</span>
                          <span className="tabular-nums text-slate-500">
                            {(value * 100).toFixed(1)}%
                          </span>
                        </li>
                      ))}
                  </ul>
                </details>
              </div>
            ) : (
              <div>
                <p className="text-xs uppercase tracking-wide text-slate-500">Status</p>
                <p className="text-slate-800">{detail.data.status}</p>
                {detail.data.rejected_reason && (
                  <p className="mt-1 text-xs text-slate-500">{detail.data.rejected_reason}</p>
                )}
              </div>
            )}

            {detail.data.latitude !== null && detail.data.longitude !== null && (
              <div>
                <p className="text-xs uppercase tracking-wide text-slate-500">Location</p>
                <Coordinates latitude={detail.data.latitude} longitude={detail.data.longitude} />
              </div>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Report modal
// ---------------------------------------------------------------------------

export function ReportModal({
  projectId,
  onClose,
}: {
  projectId: string;
  onClose: () => void;
}) {
  const request = useRequestReport(projectId);
  const [kind, setKind] = useState('weekly');
  const [format, setFormat] = useState('pdf');
  const [queued, setQueued] = useState(false);

  return (
    <Modal title="Generate a report" onClose={onClose}>
      {queued ? (
        <div>
          <p className="text-sm text-slate-600">
            Queued. Reports render in the background — this one appears in the project&rsquo;s
            report list when it is ready.
          </p>
          <button
            type="button"
            onClick={onClose}
            className="mt-4 rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white"
          >
            Done
          </button>
        </div>
      ) : (
        <>
          <div className="flex flex-col gap-4">
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-slate-700">Period</span>
              <select
                value={kind}
                onChange={(event) => { setKind(event.target.value); }}
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              >
                <option value="weekly">Last complete week</option>
                <option value="monthly">Last complete month</option>
              </select>
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-slate-700">Format</span>
              <select
                value={format}
                onChange={(event) => { setFormat(event.target.value); }}
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              >
                <option value="pdf">PDF — the presentation document</option>
                <option value="csv">CSV — the raw rows</option>
              </select>
            </label>
            <p className="text-xs text-slate-500">
              Periods are always complete: a weekly report covers the last full Monday to
              Sunday in the project&rsquo;s timezone, never a partial week.
            </p>
          </div>

          {request.isError && (
            <div className="mt-3">
              <ErrorState title="Could not queue the report" message={request.error.message} />
            </div>
          )}

          <div className="mt-5 flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={request.isPending}
              onClick={() => {
                request.mutate(
                  { kind, report_format: format },
                  { onSuccess: () => { setQueued(true); } },
                );
              }}
              className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
            >
              {request.isPending ? 'Queuing…' : 'Generate'}
            </button>
          </div>
        </>
      )}
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Reference assets
// ---------------------------------------------------------------------------

/**
 * Blueprints and renders are **stored and shown, not modelled** (ADR-010).
 * The panel says so, because "upload references for the AI to follow" is the
 * spec's wording and quietly implying the model reads them would overstate
 * what the system does.
 */
export function AssetPanel({
  projectId,
  assets,
  canUpload,
}: {
  projectId: string;
  assets: Asset[];
  canUpload: boolean;
}) {
  const upload = useUploadAsset(projectId);
  const [kind, setKind] = useState('blueprint');
  const [notes, setNotes] = useState('');

  return (
    <div>
      {assets.length === 0 ? (
        <EmptyState title="No reference files" />
      ) : (
        <ul className="mb-3 flex flex-col gap-2 text-sm">
          {assets.map((asset) => (
            <li
              key={asset.id}
              className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 px-3 py-2"
            >
              <span className="min-w-0">
                <span className="block truncate">{asset.original_filename}</span>
                <span className="block text-xs capitalize text-slate-500">
                  {asset.kind} · {(asset.size_bytes / 1024).toFixed(0)} kB
                </span>
              </span>
              {asset.download_url && (
                <a
                  href={asset.download_url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="shrink-0 text-xs font-medium text-sky-700 hover:underline"
                >
                  Download ↗
                </a>
              )}
            </li>
          ))}
        </ul>
      )}

      {canUpload && (
        <div className="flex flex-col gap-2 border-t border-slate-100 pt-3">
          <div className="flex gap-2">
            <select
              value={kind}
              onChange={(event) => { setKind(event.target.value); }}
              className="rounded-md border border-slate-300 px-2 py-1 text-sm"
            >
              <option value="blueprint">Blueprint</option>
              <option value="render">3D render</option>
              <option value="permit">Permit</option>
              <option value="other">Other</option>
            </select>
            <input
              value={notes}
              onChange={(event) => { setNotes(event.target.value); }}
              placeholder="Notes (optional)"
              className="min-w-0 flex-1 rounded-md border border-slate-300 px-2 py-1 text-sm"
            />
          </div>
          <input
            type="file"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) {
                upload.mutate({ file, kind, notes }, { onSuccess: () => { setNotes(''); } });
              }
            }}
            className="text-sm file:mr-2 file:rounded-md file:border-0 file:bg-slate-900 file:px-3 file:py-1.5 file:text-sm file:text-white"
          />
          {upload.isError && (
            <ErrorState title="Upload failed" message={upload.error.message} />
          )}
          <p className="text-xs text-slate-500">
            Stored and shown alongside the project, and included in reports. The model does not
            read them — comparing captures against a plan is future work (ADR-010).
          </p>
        </div>
      )}
    </div>
  );
}
