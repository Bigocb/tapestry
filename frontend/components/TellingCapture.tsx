"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { api } from "@/lib/api";

export function TellingCapture() {
  const router = useRouter();
  const [transcript, setTranscript] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const telling = await api.createTelling(transcript);
      router.push(`/tellings/${telling.id}`);
    } catch {
      setError("Could not submit your story.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <label className="block">
        <span className="block font-medium mb-1">What do you want to tell?</span>
        <textarea
          className="w-full border rounded p-3 h-40"
          value={transcript}
          onChange={(event) => setTranscript(event.target.value)}
        />
      </label>
      <button
        type="submit"
        disabled={busy}
        className="bg-indigo-600 text-white px-4 py-2 rounded hover:bg-indigo-700 disabled:opacity-50"
      >
        {busy ? "Splitting…" : "Tell it"}
      </button>
      {error && <p className="text-red-600">{error}</p>}
    </form>
  );
}
