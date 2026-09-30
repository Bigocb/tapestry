"use client";

import Link from "next/link";
import { useState } from "react";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";

const inputClass =
  "w-full border border-line rounded-lg px-3 py-2.5 bg-bg-raised text-ink placeholder:text-ink-faint focus:outline-none focus:ring-2 focus:ring-flash/30 focus:border-flash";

export function LoginForm() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      const data = await api.login(username, password);
      login(data.access_token);
    } catch (err: any) {
      setError(err.message || "Login failed");
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <h2 className="text-2xl font-bold">Welcome back</h2>
      {error && <p className="text-coral text-sm">{error}</p>}
      <input
        type="text"
        placeholder="Username"
        autoCapitalize="none" autoCorrect="off" spellCheck={false} autoComplete="username"
        className={inputClass}
        value={username}
        onChange={(e) => setUsername(e.target.value)}
        required
      />
      <input
        type="password"
        placeholder="Password"
        autoCapitalize="none" autoCorrect="off" autoComplete="current-password"
        className={inputClass}
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        required
      />
      <button
        type="submit"
        className="w-full bg-flash text-flash-ink rounded-lg py-2.5 font-semibold hover:bg-flash-dark transition"
      >
        Login
      </button>
      <Link
        href="/forgot-password"
        className="block text-sm text-violet hover:underline"
      >
        Forgot your password?
      </Link>
    </form>
  );
}

export function SignupForm({ onDone }: { onDone?: () => void }) {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (password !== confirm) {
      setError("Passwords do not match");
      return;
    }
    try {
      await api.register(username, email, password);
      const data = await api.login(username, password);
      login(data.access_token);
      onDone?.();
    } catch (err: any) {
      setError(err.message || "Signup failed");
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <h2 className="text-2xl font-bold">Start your archive</h2>
      {error && <p className="text-coral text-sm">{error}</p>}
      <input
        type="text"
        placeholder="Username"
        autoCapitalize="none" autoCorrect="off" spellCheck={false} autoComplete="username"
        className={inputClass}
        value={username}
        onChange={(e) => setUsername(e.target.value)}
        required
      />
      <input
        type="email"
        placeholder="Email"
        autoCapitalize="none" autoCorrect="off" spellCheck={false} autoComplete="email"
        className={inputClass}
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        required
      />
      <input
        type="password"
        placeholder="Password"
        autoCapitalize="none" autoCorrect="off" autoComplete="new-password"
        className={inputClass}
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        required
      />
      <input
        type="password"
        placeholder="Confirm password"
        autoCapitalize="none" autoCorrect="off" autoComplete="new-password"
        className={inputClass}
        value={confirm}
        onChange={(e) => setConfirm(e.target.value)}
        required
      />
      <button
        type="submit"
        className="w-full bg-flash text-flash-ink rounded-lg py-2.5 font-semibold hover:bg-flash-dark transition"
      >
        Sign up
      </button>
    </form>
  );
}
