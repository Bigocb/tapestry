"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { api, type TellingSummary } from "@/lib/api";

// The states that mean "this is not finished" — and so can be returned to.
const UNFINISHED = ["draft", "transcribing", "segmenting", "failed"];

function describe(telling: TellingSummary): string {
  if (telling.raw_transcript) return telling.raw_transcript.slice(0, 60);
  if (telling.status === "failed") return "A recording that could not be processed";
  return "A recording still being transcribed";
}

export function TellingCapture() {
  const router = useRouter();
  const [transcript, setTranscript] = useState("");
  const [audio, setAudio] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [waiting, setWaiting] = useState<TellingSummary[]>([]);

  useEffect(() => {
    // Without this a telling started and abandoned is reachable only if you
    // kept the URL, which is not a way to treat someone's words.
    api
      .getTellings()
      .then((tellings) =>
        setWaiting(tellings.filter((item) => UNFINISHED.includes(item.status)))
      )
      .catch(() => setWaiting([]));
  }, []);

  async function submitText(event: FormEvent) {
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

  async function submitAudio(event: FormEvent) {
    event.preventDefault();
    if (!audio) return;
    setBusy(true);
    setError(null);
    try {
      // Comes back straight away; the review screen watches it being
      // transcribed rather than holding the request open.
      const telling = await api.createVoiceTelling(audio);
      router.push(`/tellings/${telling.id}`);
    } catch {
      setError("Could not upload your recording.");
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      {waiting.length > 0 ? (
        <div className="border rounded p-4 bg-amber-50">
          <h2 className="font-semibold text-amber-900">
            You have {waiting.length} unfinished telling
            {waiting.length === 1 ? "" : "s"}
          </h2>
          <ul className="mt-2 space-y-1 text-sm">
            {waiting.map((telling) => (
              <li key={telling.id}>
                <Link
                  href={`/tellings/${telling.id}`}
                  className="text-indigo-700 underline"
                >
                  {describe(telling)}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <form onSubmit={submitText} className="space-y-4">
        <label className="block">
          <span className="block font-medium mb-1">
            What do you want to tell?
          </span>
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
      </form>

      <form onSubmit={submitAudio} className="space-y-4 border-t pt-4">
        <label className="block">
          <span className="block font-medium mb-1">
            Or upload a recording of it
          </span>
          <input
            type="file"
            accept="audio/*"
            className="block"
            onChange={(event) =>
              setAudio(event.target.files?.[0] ?? null)
            }
          />
        </label>
        <button
          type="submit"
          disabled={busy || !audio}
          className="border px-4 py-2 rounded hover:bg-gray-50 disabled:opacity-50"
        >
          {busy ? "Uploading…" : "Upload recording"}
        </button>
      </form>

      {error && <p className="text-red-600">{error}</p>}
    </div>
  );
}
