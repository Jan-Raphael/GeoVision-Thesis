/**
 * Sign in and registration.
 *
 * Registration redirects to `/me`, which is what the spec asks for and also the
 * right instinct: the first thing a new owner needs is somewhere to press
 * "Create project", not a marketing page.
 */

import { useState } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';

import { ErrorState } from '@/components/common';
import { login, register, type RegisterInput } from '@/lib/auth';
import { useSession } from '@/features/auth/session';

const ROLES = [
  'engineer',
  'architect',
  'project_manager',
  'contractor',
  'home_owner',
  'student',
  'other',
];

function Field({
  label,
  value,
  onChange,
  type = 'text',
  ...rest
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
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
    </label>
  );
}

function Shell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-md">
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      <div className="mt-6">{children}</div>
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
        <Field label="Username" value={form.username} onChange={set('username')} required minLength={3} />
        <Field label="Email" value={form.email} onChange={set('email')} type="email" required />
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
              <option key={role} value={role}>
                {role.replace('_', ' ')}
              </option>
            ))}
          </select>
        </label>
        <Field
          label="Password"
          value={form.password}
          onChange={set('password')}
          type="password"
          required
          minLength={12}
          autoComplete="new-password"
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
