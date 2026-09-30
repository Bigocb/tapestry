"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";

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
    <form onSubmit={handleSubmit} className="space-y-4 max-w-sm mx-auto">
      <h2 className="text-2xl font-bold">Login</h2>
      {error && <p className="text-red-600">{error}</p>}
      <input
        type="text"
        placeholder="Username"
        autoCapitalize="none" autoCorrect="off" spellCheck={false} autoComplete="username"
        className="w-full border rounded px-3 py-2"
        value={username}
        onChange={(e) => setUsername(e.target.value)}
        required
      />
      <input
        type="password"
        placeholder="Password"
        autoCapitalize="none" autoCorrect="off" autoComplete="current-password"
        className="w-full border rounded px-3 py-2"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        required
      />
      <button
        type="submit"
        className="w-full bg-indigo-600 text-white rounded py-2 hover:bg-indigo-700"
      >
        Login
      </button>
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
    <form onSubmit={handleSubmit} className="space-y-4 max-w-sm mx-auto">
      <h2 className="text-2xl font-bold">Sign up</h2>
      {error && <p className="text-red-600">{error}</p>}
      <input
        type="text"
        placeholder="Username"
        autoCapitalize="none" autoCorrect="off" spellCheck={false} autoComplete="username"
        className="w-full border rounded px-3 py-2"
        value={username}
        onChange={(e) => setUsername(e.target.value)}
        required
      />
      <input
        type="email"
        placeholder="Email"
        autoCapitalize="none" autoCorrect="off" spellCheck={false} autoComplete="email"
        className="w-full border rounded px-3 py-2"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        required
      />
      <input
        type="password"
        placeholder="Password"
        autoCapitalize="none" autoCorrect="off" autoComplete="new-password"
        className="w-full border rounded px-3 py-2"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        required
      />
      <input
        type="password"
        placeholder="Confirm password"
        autoCapitalize="none" autoCorrect="off" autoComplete="new-password"
        className="w-full border rounded px-3 py-2"
        value={confirm}
        onChange={(e) => setConfirm(e.target.value)}
        required
      />
      <button
        type="submit"
        className="w-full bg-indigo-600 text-white rounded py-2 hover:bg-indigo-700"
      >
        Sign up
      </button>
    </form>
  );
}
