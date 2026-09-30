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
    <form onSubmit={submit}>
      <label>
        What do you want to tell?
        <textarea
          value={transcript}
          onChange={(event) => setTranscript(event.target.value)}
        />
      </label>
      <button type="submit" disabled={busy}>
        Tell it
      </button>
      {error ? <p>{error}</p> : null}
    </form>
  );
}
