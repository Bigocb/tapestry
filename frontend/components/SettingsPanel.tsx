"use client";

import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";

const fieldClass =
  "bg-bg-raised border border-line rounded-lg p-2.5 text-sm text-ink placeholder:text-ink-faint focus:outline-none focus:ring-2 focus:ring-flash/30 focus:border-flash w-full";
const btnSolid =
  "bg-flash text-flash-ink rounded-lg px-4 py-2 text-sm font-bold hover:bg-flash-dark transition disabled:opacity-40";
const actionBox = "bg-surface border border-line rounded-2xl p-5";

export function SettingsPanel() {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const tooShort = newPassword.length > 0 && newPassword.length < 8;
  const mismatch = confirmPassword.length > 0 && newPassword !== confirmPassword;
  const canSubmit =
    currentPassword.length > 0 &&
    newPassword.length >= 8 &&
    newPassword === confirmPassword;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setNotice("");
    setBusy(true);
    try {
      await api.changePassword(currentPassword, newPassword);
      setNotice("Your password has been changed.");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err: unknown) {
      setError(
        err instanceof Error ? err.message : "Could not change your password"
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-3xl font-bold mb-1">Settings</h1>
        <p className="text-ink-muted text-sm">Your account and this app.</p>
      </div>

      <section className={actionBox}>
        <p className="font-semibold mb-1">Change your password</p>
        <p className="text-sm text-ink-muted mb-4">
          Enter your current password, then choose a new one.
        </p>

        <form onSubmit={submit} className="space-y-3">
          <label className="block">
            <span className="stamp text-ink-faint">Current password</span>
            <input
              type="password"
              autoComplete="current-password"
              className={`${fieldClass} mt-1`}
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
            />
          </label>
          <label className="block">
            <span className="stamp text-ink-faint">New password</span>
            <input
              type="password"
              autoComplete="new-password"
              className={`${fieldClass} mt-1`}
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
            />
          </label>
          <label className="block">
            <span className="stamp text-ink-faint">Confirm new password</span>
            <input
              type="password"
              autoComplete="new-password"
              className={`${fieldClass} mt-1`}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
            />
          </label>

          {tooShort && (
            <p className="text-sm text-coral">
              A password needs at least 8 characters.
            </p>
          )}
          {mismatch && (
            <p className="text-sm text-coral">The two new passwords differ.</p>
          )}
          {error && <p className="text-sm text-coral">{error}</p>}
          {notice && <p className="text-sm text-mint">{notice}</p>}

          <div className="flex items-center gap-3 pt-1">
            <button type="submit" disabled={busy || !canSubmit} className={btnSolid}>
              {busy ? "Changing…" : "Change password"}
            </button>
            <Link
              href="/forgot-password"
              className="text-sm text-ink-muted hover:text-flash underline"
            >
              I don&rsquo;t know my current password
            </Link>
          </div>
        </form>

        <p className="text-xs text-ink-faint mt-4">
          If you have forgotten the current password, use the reset link instead
          — it lets you set a new one by email without knowing the old one.
        </p>
      </section>
    </div>
  );
}
