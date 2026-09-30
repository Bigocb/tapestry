"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";

import { api } from "@/lib/api";

export function ForgotPasswordForm() {
  const [identifier, setIdentifier] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await api.forgotPassword(identifier);
      setSent(true);
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <div className="max-w-sm mx-auto mt-12 space-y-3">
        <h1 className="text-2xl font-bold">Check your email</h1>
        <p className="text-gray-600">
          If that account exists, a reset link has been created. On a
          self-hosted setup with no mail configured, the link is written to the
          server log instead.
        </p>
        <Link href="/login" className="text-indigo-700 underline text-sm">
          Back to login
        </Link>
      </div>
    );
  }

  return (
    <form
      onSubmit={submit}
      className="space-y-4 max-w-sm mx-auto mt-12"
    >
      <h1 className="text-2xl font-bold">Forgot your password?</h1>
      <label className="block">
        <span className="block font-medium mb-1">Username or email</span>
        <input
          type="text"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          className="w-full border rounded px-3 py-2"
          value={identifier}
          onChange={(event) => setIdentifier(event.target.value)}
          required
        />
      </label>
      <button
        type="submit"
        disabled={busy}
        className="w-full bg-indigo-600 text-white rounded py-2 hover:bg-indigo-700 disabled:opacity-50"
      >
        Send reset link
      </button>
      <Link href="/login" className="block text-indigo-700 underline text-sm">
        Back to login
      </Link>
    </form>
  );
}

export function ResetPasswordForm() {
  const [token, setToken] = useState("");
  const [password, setPassword] = useState("");
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // Read from the URL rather than useSearchParams, which would need a
    // Suspense boundary for no benefit here.
    const params = new URLSearchParams(window.location.search);
    setToken(params.get("token") ?? "");
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.resetPassword(token, password);
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "That link did not work.");
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div className="max-w-sm mx-auto mt-12 space-y-3">
        <h1 className="text-2xl font-bold">Password changed</h1>
        <Link href="/login" className="text-indigo-700 underline text-sm">
          Log in with your new password
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-4 max-w-sm mx-auto mt-12">
      <h1 className="text-2xl font-bold">Choose a new password</h1>
      {error && <p className="text-red-600">{error}</p>}
      <label className="block">
        <span className="block font-medium mb-1">New password</span>
        <input
          type="password"
          autoCapitalize="none"
          autoCorrect="off"
          autoComplete="new-password"
          className="w-full border rounded px-3 py-2"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          required
          minLength={8}
        />
      </label>
      <button
        type="submit"
        disabled={busy || !token}
        className="w-full bg-indigo-600 text-white rounded py-2 hover:bg-indigo-700 disabled:opacity-50"
      >
        Set new password
      </button>
    </form>
  );
}
