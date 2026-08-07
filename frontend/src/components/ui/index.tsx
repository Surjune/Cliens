/**
 * Shared presentational components.
 *
 * These exist so repeated Tailwind class strings become one named component
 * rather than being copied between screens. No business logic lives here.
 */
import type { ReactNode } from 'react';

import { ApiError } from '@/lib/api-client';

export function Card({
  title,
  step,
  children,
}: {
  title: string;
  step?: number;
  children: ReactNode;
}) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="mb-4 flex items-center gap-2 text-base font-semibold text-slate-900">
        {step !== undefined && (
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-slate-900 text-xs font-bold text-white">
            {step}
          </span>
        )}
        {title}
      </h2>
      {children}
    </section>
  );
}

export function Button({
  children,
  onClick,
  disabled = false,
  variant = 'primary',
  type = 'button',
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: 'primary' | 'secondary';
  type?: 'button' | 'submit';
}) {
  const base =
    'inline-flex items-center justify-center rounded-md px-4 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50';
  const styles =
    variant === 'primary'
      ? 'bg-slate-900 text-white hover:bg-slate-700'
      : 'border border-slate-300 bg-white text-slate-800 hover:bg-slate-50';

  return (
    <button type={type} onClick={onClick} disabled={disabled} className={`${base} ${styles}`}>
      {children}
    </button>
  );
}

export function Spinner({ label }: { label: string }) {
  return (
    <p role="status" className="flex items-center gap-2 text-sm text-slate-600">
      <span
        aria-hidden="true"
        className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-slate-800"
      />
      {label}
    </p>
  );
}

/**
 * Renders a failure in a way the user can act on.
 *
 * A missing third-party credential is presented as a setup step rather than a
 * fault, because that is what it is — and the correlation ID is always shown so a
 * report can be tied to server logs.
 */
export function ErrorNotice({ error }: { error: unknown }) {
  if (error instanceof ApiError) {
    return (
      <div
        role="alert"
        className={`rounded-md border p-4 text-sm ${
          error.isUnconfigured
            ? 'border-amber-300 bg-amber-50 text-amber-900'
            : 'border-red-300 bg-red-50 text-red-900'
        }`}
      >
        <p className="font-medium">
          {error.isUnconfigured ? 'Setup needed' : 'Something went wrong'}
        </p>
        <p className="mt-1">{error.message}</p>
        {error.requestId !== undefined && (
          <p className="mt-2 font-mono text-xs opacity-70">Request ID: {error.requestId}</p>
        )}
      </div>
    );
  }

  return (
    <div role="alert" className="rounded-md border border-red-300 bg-red-50 p-4 text-sm text-red-900">
      <p>{error instanceof Error ? error.message : 'An unexpected error occurred.'}</p>
    </div>
  );
}

export function Stat({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`text-2xl font-semibold ${accent ?? 'text-slate-900'}`}>{value}</p>
    </div>
  );
}
