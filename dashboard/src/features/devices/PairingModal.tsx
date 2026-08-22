/**
 * The pairing modal (spec B.2) — the most demo-critical screen in the system.
 *
 * A code is issued, shown large with a QR beside it, and counts down from 15
 * minutes. The modal then **waits**, and closes itself when the server pushes
 * `device.paired`. That self-confirmation is the whole point: the alternative
 * is asking somebody standing on scaffolding to press Refresh.
 *
 * Two failure modes are handled deliberately. The code is shown **once** with a
 * plain warning, because it is single-use and re-issuing is the safe recovery.
 * And if the socket never connects, the modal still works — the countdown runs,
 * and the operator can close it and see the camera in the Devices list, which
 * the folder's 60-second poll fills in. Realtime makes it feel finished; it is
 * not what makes it correct.
 */

import { useEffect, useState } from 'react';

import { ErrorState } from '@/components/common';
import { Modal } from '@/components/modal';
import { useIssuePairingToken, type PairingTicket } from '@/lib/owner';

const FACES = [
  { value: 'front_diagonal', label: 'Front diagonal', hint: 'Recommended' },
  { value: 'front', label: 'Front', hint: '' },
  { value: 'back_diagonal', label: 'Back diagonal', hint: '' },
  { value: 'back', label: 'Back', hint: '' },
];

interface PairingModalProps {
  projectId: string;
  /** Set when the server pushes `device.paired` for this project. */
  pairedDeviceName?: string | null;
  onClose: () => void;
}

function Countdown({ seconds }: { seconds: number }) {
  const minutes = Math.floor(Math.max(seconds, 0) / 60);
  const rest = Math.max(seconds, 0) % 60;
  const expired = seconds <= 0;
  return (
    <span
      className={`font-mono text-sm tabular-nums ${expired ? 'text-rose-700' : 'text-slate-600'}`}
    >
      {expired ? 'Expired' : `${String(minutes)}:${String(rest).padStart(2, '0')}`}
    </span>
  );
}

export function PairingModal({ projectId, pairedDeviceName, onClose }: PairingModalProps) {
  const [face, setFace] = useState(FACES[0]?.value ?? 'front_diagonal');
  const [ticket, setTicket] = useState<PairingTicket | null>(null);
  const [remaining, setRemaining] = useState(0);
  const issue = useIssuePairingToken(projectId);

  useEffect(() => {
    if (!ticket) return undefined;
    setRemaining(ticket.expires_in_seconds);
    const timer = setInterval(() => {
      setRemaining((value) => value - 1);
    }, 1000);
    return () => {
      clearInterval(timer);
    };
  }, [ticket]);

  const request = () => {
    issue.mutate(face, { onSuccess: setTicket });
  };

  return (
    <Modal title="Pair an ESP32 camera" onClose={onClose} size="lg">
      {pairedDeviceName ? (
        <div className="text-center">
          <p className="text-3xl" aria-hidden="true">
            ✅
          </p>
          <p className="mt-2 font-medium text-slate-900">{pairedDeviceName} paired</p>
          <p className="mt-1 text-sm text-slate-500">
            The camera will upload on its capture schedule.
          </p>
          <button
            type="button"
            onClick={onClose}
            className="mt-5 rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
          >
            Done
          </button>
        </div>
      ) : !ticket ? (
        <div>
          <fieldset>
            <legend className="text-sm font-medium text-slate-700">Which face of the site?</legend>
            <div className="mt-2 grid grid-cols-2 gap-2">
              {FACES.map((option) => (
                <label
                  key={option.value}
                  className={`cursor-pointer rounded-lg border px-3 py-2 text-sm transition ${
                    face === option.value
                      ? 'border-sky-500 bg-sky-50 text-sky-900 ring-1 ring-sky-500'
                      : 'border-slate-200 hover:border-sky-300'
                  }`}
                >
                  <input
                    type="radio"
                    name="face"
                    value={option.value}
                    checked={face === option.value}
                    onChange={() => {
                      setFace(option.value);
                    }}
                    className="sr-only"
                  />
                  {option.label}
                  {option.hint && (
                    <span className="ml-1 text-xs text-slate-500">· {option.hint}</span>
                  )}
                </label>
              ))}
            </div>
          </fieldset>

          {issue.isError && (
            <div className="mt-4">
              <ErrorState title="Could not issue a code" message={issue.error.message} />
            </div>
          )}

          <button
            type="button"
            onClick={request}
            disabled={issue.isPending}
            className="mt-5 w-full rounded-md bg-slate-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-60"
          >
            {issue.isPending ? 'Generating…' : 'Generate pairing code'}
          </button>
        </div>
      ) : (
        <div>
          <div className="blueprint-frame flex flex-col items-center gap-3 rounded-lg border border-sky-200 bg-sky-50/60 p-5">
            {ticket.qr_png_base64 && (
              <img
                src={`data:image/png;base64,${ticket.qr_png_base64}`}
                alt="Pairing QR code"
                className="h-40 w-40 rounded border border-white bg-white p-1.5 shadow-sm"
              />
            )}
            <p className="font-mono text-2xl font-semibold tracking-[0.2em] text-slate-900">
              {ticket.formatted_code}
            </p>
            <Countdown seconds={remaining} />
            <p className="text-center text-xs text-amber-800">
              Shown once. If you lose it, generate a new code — this one cannot be recovered.
            </p>
          </div>

          <ol className="mt-4 list-decimal space-y-1 pl-5 text-sm text-slate-600">
            <li>Power the camera.</li>
            <li>
              Join the Wi-Fi network <span className="font-medium">GeoVision-Setup-XXXX</span>.
            </li>
            <li>Enter your site Wi-Fi details and the code above.</li>
          </ol>

          <p className="mt-4 text-center text-sm text-slate-500" aria-live="polite">
            {remaining > 0
              ? 'Waiting for the camera to claim this code…'
              : 'This code has expired.'}
          </p>

          <button
            type="button"
            onClick={() => {
              setTicket(null);
            }}
            className="mt-3 w-full rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Generate a new code
          </button>
        </div>
      )}
    </Modal>
  );
}
