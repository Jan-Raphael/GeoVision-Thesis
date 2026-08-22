/**
 * Sign in and registration.
 *
 * Registration redirects to `/me`, which is what the spec asks for and also the
 * right instinct: the first thing a new owner needs is somewhere to press
 * "Create project", not a marketing page.
 */

import { useState } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';

import { ErrorState, FieldHint } from '@/components/common';
import { login, register, type RegisterInput } from '@/lib/auth';
import { useSession } from '@/features/auth/session';

/**
 * The ten values of the server's `ProfessionalRole` enum, in its order.
 *
 * This list is a **copy of a server contract**, so it is written out in full
 * rather than abbreviated to the roles that seem likely: anything not in
 * `app/domain/enums.py` is rejected as a validation error at registration, and
 * anything missing from here is a person who cannot describe themselves
 * correctly. An earlier version of this file invented `project_manager` — which
 * the server does not have, splitting that idea into `manager` and
 * `project_handler` — and silently dropped `foreman` and `surveyor`.
 * `backend/tests/unit/test_role_options.py` now fails if the two drift again.
 *
 * The role is descriptive only. It grants nothing: authorization comes from
 * membership on a specific project (Roles-and-Permissions).
 */
const ROLES: readonly { value: string; label: string }[] = [
  { value: 'manager', label: 'Manager' },
  { value: 'project_handler', label: 'Project handler' },
  { value: 'engineer', label: 'Engineer' },
  { value: 'architect', label: 'Architect' },
  { value: 'foreman', label: 'Foreman' },
  { value: 'contractor', label: 'Contractor' },
  { value: 'surveyor', label: 'Surveyor' },
  { value: 'home_owner', label: 'Home owner' },
  { value: 'student', label: 'Student' },
  { value: 'other', label: 'Other' },
];

function Field({
  label,
  value,
  onChange,
  type = 'text',
  hint,
  ...rest
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  /** Small, semi-transparent format guidance shown under the input. */
  hint?: React.ReactNode;
} & Record<string, unknown>) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-slate-700">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
        }}
        className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500"
        {...rest}
      />
      {hint && <FieldHint>{hint}</FieldHint>}
    </label>
  );
}

/**
 * The sign-in / registration card.
 *
 * Framed like the rest of the app's primary panels (the drafting corner
 * marks), but standalone on the page rather than inside `PublicLayout`'s
 * shell padding — the first thing a new visitor sees should read as a single,
 * deliberate document, not a form loose on the page.
 */
function Shell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-md">
      <div className="blueprint-frame rounded-lg border border-slate-200 bg-white p-8 shadow-sm">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{title}</h1>
        <div className="mt-6">{children}</div>
      </div>
    </div>
  );
}

export function LoginPage() {
  const { user, refresh } = useSession();
  const navigate = useNavigate();
  const [identifier, setIdentifier] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to="/me" replace />;

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    login(identifier, password).then(
      () => {
        refresh();
        navigate('/me');
      },
      (cause: unknown) => {
        setBusy(false);
        setError(cause instanceof Error ? cause.message : 'Could not sign in.');
      },
    );
  };

  return (
    <Shell title="Sign in">
      <form onSubmit={submit} className="flex flex-col gap-4">
        <Field
          label="Username or email"
          value={identifier}
          onChange={setIdentifier}
          required
          autoComplete="username"
        />
        <Field
          label="Password"
          value={password}
          onChange={setPassword}
          type="password"
          required
          autoComplete="current-password"
        />
        {error && <ErrorState title="Sign in failed" message={error} />}
        <button
          type="submit"
          disabled={busy}
          className="rounded-md bg-slate-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-60"
        >
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
      <p className="mt-4 text-sm text-slate-600">
        No account?{' '}
        <Link to="/register" className="font-medium text-sky-700 hover:underline">
          Create one
        </Link>
      </p>
    </Shell>
  );
}

const EMPTY: RegisterInput = {
  username: '',
  email: '',
  password: '',
  full_name: '',
  professional_role: 'engineer',
};

export function RegisterPage() {
  const { user, refresh } = useSession();
  const navigate = useNavigate();
  const [form, setForm] = useState<RegisterInput>(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to="/me" replace />;

  const set = (key: keyof RegisterInput) => (value: string) => {
    setForm((current) => ({ ...current, [key]: value }));
  };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    register(form).then(
      () => {
        refresh();
        // Straight to the profile, per spec B: the first thing a new owner
        // needs is the Create Project button.
        navigate('/me');
      },
      (cause: unknown) => {
        setBusy(false);
        setError(cause instanceof Error ? cause.message : 'Could not create the account.');
      },
    );
  };

  return (
    <Shell title="Create an account">
      <form onSubmit={submit} className="flex flex-col gap-4">
        <Field label="Full name" value={form.full_name} onChange={set('full_name')} required />
        <Field
          label="Username"
          value={form.username}
          onChange={set('username')}
          required
          minLength={3}
          maxLength={30}
          pattern="[a-zA-Z0-9_.]{3,30}"
          autoComplete="username"
          hint="3–30 characters. Letters, numbers, underscore ( _ ) and dot ( . ) only — no spaces."
        />
        <Field
          label="Email"
          value={form.email}
          onChange={set('email')}
          type="email"
          required
          autoComplete="email"
          hint="Used to sign in and for account recovery. Never shown on your public profile."
        />
        <label className="block">
          <span className="mb-1 block text-sm font-medium text-slate-700">Professional role</span>
          <select
            value={form.professional_role}
            onChange={(event) => {
              set('professional_role')(event.target.value);
            }}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500"
          >
            {ROLES.map((role) => (
              <option key={role.value} value={role.value}>
                {role.label}
              </option>
            ))}
          </select>
          <FieldHint>Descriptive only — it does not grant any permission by itself.</FieldHint>
        </label>
        <Field
          label="Password"
          value={form.password}
          onChange={set('password')}
          type="password"
          required
          minLength={8}
          maxLength={128}
          autoComplete="new-password"
          hint="At least 8 characters, with at least one letter and one number. Avoid common passwords."
        />
        {error && <ErrorState title="Registration failed" message={error} />}
        <button
          type="submit"
          disabled={busy}
          className="rounded-md bg-slate-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-60"
        >
          {busy ? 'Creating…' : 'Create account'}
        </button>
      </form>
      <p className="mt-4 text-sm text-slate-600">
        Already have an account?{' '}
        <Link to="/login" className="font-medium text-sky-700 hover:underline">
          Sign in
        </Link>
      </p>
    </Shell>
  );
}
