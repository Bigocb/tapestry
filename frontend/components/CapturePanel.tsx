"use client";

import { useState, useRef } from "react";
import { api } from "@/lib/api";
import { TellingCapture } from "@/components/TellingCapture";
import { MicrophoneIcon } from "@heroicons/react/24/outline";

const COPY = {
  memory: { eyebrow: "New entry", headline: "Say what happened." },
  story: { eyebrow: "New story", headline: "Tell the story." },
} as const;

export function CapturePanel() {
  const [entryType, setEntryType] = useState<"memory" | "story">("memory");
  const [mode, setMode] = useState<"text" | "voice" | "form">("text");

  return (
    <div className="max-w-2xl">
      <div className="bg-bg-raised border border-line rounded-3xl p-6 md:p-9 relative overflow-hidden mb-9">
        <div
          className="absolute -right-16 -top-16 w-64 h-64 rounded-full pointer-events-none"
          style={{ background: "radial-gradient(circle, rgba(139,135,255,.18), rgba(139,135,255,0) 65%)" }}
        />
        <p className="stamp text-violet mb-2 relative">{COPY[entryType].eyebrow}</p>
        <h1 className="text-3xl md:text-4xl font-extrabold mb-6 relative max-w-[14ch]">
          {COPY[entryType].headline}
        </h1>

        <div className="flex items-center gap-4 mb-6 relative">
          <span className="stamp text-ink-muted">
            This is a{" "}
            <button
              type="button"
              onClick={() => setEntryType("memory")}
              className={`${entryType === "memory" ? "text-flash border-flash" : "text-ink-faint border-transparent hover:text-ink"} border-b`}
            >
              Memory
            </button>
            {" / "}
            <button
              type="button"
              onClick={() => setEntryType("story")}
              className={`${entryType === "story" ? "text-flash border-flash" : "text-ink-faint border-transparent hover:text-ink"} border-b`}
            >
              Story
            </button>
          </span>
        </div>

        {entryType === "memory" && (
          <div className="flex gap-2 relative">
            <ModeButton active={mode === "text"} onClick={() => setMode("text")}>
              Text
            </ModeButton>
            <ModeButton active={mode === "voice"} onClick={() => setMode("voice")}>
              Voice
            </ModeButton>
            <ModeButton active={mode === "form"} onClick={() => setMode("form")}>
              Form
            </ModeButton>
          </div>
        )}
      </div>

      {entryType === "memory" ? (
        <>
          {mode === "text" && <TextCapture />}
          {mode === "voice" && <VoiceCapture />}
          {mode === "form" && <FormCapture />}
        </>
      ) : (
        <TellingCapture />
      )}
    </div>
  );
}

function ModeButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-4 py-1.5 rounded-full text-sm font-medium border transition ${
        active
          ? "bg-flash text-flash-ink border-flash"
          : "bg-surface text-ink-muted border-line hover:border-flash hover:text-flash"
      }`}
    >
      {children}
    </button>
  );
}

const fieldClass =
  "border border-line rounded-lg bg-surface placeholder:text-ink-faint focus:outline-none focus:ring-2 focus:ring-flash/30 focus:border-flash";

function TextCapture() {
  const [raw, setRaw] = useState("");
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const data = await api.captureText(raw);
      setResult(data);
      setRaw("");
    } catch (err: any) {
      setError(err.message || "Capture failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <textarea
        className={`w-full p-3 h-40 ${fieldClass}`}
        placeholder="What happened today?"
        value={raw}
        onChange={(e) => setRaw(e.target.value)}
        required
      />
      <button
        type="submit"
        disabled={busy}
        className="bg-flash text-flash-ink font-semibold px-5 py-2.5 rounded-lg hover:bg-flash-dark disabled:opacity-50 transition"
      >
        {busy ? "Processing…" : "Capture"}
      </button>
      {error && <p className="text-coral">{error}</p>}
      {result && <MemoryPreview memory={result} />}
    </form>
  );
}

function VoiceCapture() {
  const [recording, setRecording] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState("");
  const mediaRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  const start = async () => {
    setError("");
    chunksRef.current = [];
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = async () => {
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        try {
          const data = await api.captureVoice(new File([blob], "voice.webm"));
          setResult(data);
        } catch (err: any) {
          setError(err.message || "Voice capture failed");
        }
        setRecording(false);
      };
      mediaRef.current = recorder;
      recorder.start();
      setRecording(true);
    } catch {
      setError("Microphone access denied or unavailable");
    }
  };

  const stop = () => {
    mediaRef.current?.stop();
    mediaRef.current?.stream.getTracks().forEach((t) => t.stop());
  };

  return (
    <div className="flex flex-col items-start gap-4">
      <div className="flex items-center gap-4">
        <button
          onClick={recording ? stop : start}
          aria-label={recording ? "Stop recording" : "Start recording"}
          className={`w-20 h-20 rounded-full flex items-center justify-center transition ${
            recording
              ? "bg-coral text-white fab-pulse"
              : "bg-flash text-flash-ink hover:scale-105"
          }`}
        >
          <MicrophoneIcon className="w-7 h-7" />
        </button>
        <p className="stamp text-ink-muted">
          {recording ? "Listening…" : "Tap to speak"}
        </p>
      </div>
      {error && <p className="text-coral">{error}</p>}
      {result && <MemoryPreview memory={result} />}
    </div>
  );
}

function FormCapture() {
  const [fields, setFields] = useState({
    raw_input: "",
    mood: "",
    tags: "",
    people: "",
    location: "",
    importance_level: 3,
  });
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const data = await api.captureForm({
        raw_input: fields.raw_input,
        mood: fields.mood || undefined,
        tags: fields.tags ? fields.tags.split(",").map((t) => t.trim()) : undefined,
        people: fields.people
          ? fields.people.split(",").map((p) => p.trim())
          : undefined,
        location: fields.location || undefined,
        importance_level: fields.importance_level,
      });
      setResult(data);
    } catch (err: any) {
      setError(err.message || "Capture failed");
    } finally {
      setBusy(false);
    }
  };

  const update = (key: keyof typeof fields, value: string | number) =>
    setFields((f) => ({ ...f, [key]: value }));

  return (
    <form onSubmit={submit} className="space-y-4">
      <textarea
        className={`w-full p-3 h-32 ${fieldClass}`}
        placeholder="Memory description"
        value={fields.raw_input}
        onChange={(e) => update("raw_input", e.target.value)}
        required
      />
      <div className="grid grid-cols-2 gap-4">
        <input
          type="text"
          placeholder="Mood"
          className={`p-2 ${fieldClass}`}
          value={fields.mood}
          onChange={(e) => update("mood", e.target.value)}
        />
        <input
          type="text"
          placeholder="Location"
          className={`p-2 ${fieldClass}`}
          value={fields.location}
          onChange={(e) => update("location", e.target.value)}
        />
        <input
          type="text"
          placeholder="Tags (comma separated)"
          className={`p-2 ${fieldClass}`}
          value={fields.tags}
          onChange={(e) => update("tags", e.target.value)}
        />
        <input
          type="text"
          placeholder="People (comma separated)"
          className={`p-2 ${fieldClass}`}
          value={fields.people}
          onChange={(e) => update("people", e.target.value)}
        />
      </div>
      <label className="block text-sm text-ink-muted">
        Importance (1-5)
        <input
          type="range"
          min={1}
          max={5}
          value={fields.importance_level}
          onChange={(e) => update("importance_level", Number(e.target.value))}
          className="w-full accent-flash mt-1"
        />
      </label>
      <button
        type="submit"
        disabled={busy}
        className="bg-flash text-flash-ink font-semibold px-5 py-2.5 rounded-lg hover:bg-flash-dark disabled:opacity-50 transition"
      >
        {busy ? "Processing…" : "Capture"}
      </button>
      {error && <p className="text-coral">{error}</p>}
      {result && <MemoryPreview memory={result} />}
    </form>
  );
}

function MemoryPreview({ memory }: { memory: any }) {
  return (
    <div className="border border-mint/30 rounded-lg p-4 bg-mint/10 flash-in">
      <h3 className="font-semibold text-mint flex items-center gap-2">
        <span className="stamp bg-mint text-flash-ink px-1.5 py-0.5 rounded-sm">Saved</span>
        Memory captured
      </h3>
      <p className="stamp text-ink-muted mt-1">{memory.processing_state}</p>
      <p className="mt-2 text-ink">{memory.summary || memory.raw_input}</p>
      {memory.tags?.length > 0 && (
        <div className="flex flex-wrap gap-2 mt-3">
          {memory.tags.map((tag: string) => (
            <span key={tag} className="text-xs bg-surface border border-line text-ink-muted px-2 py-1 rounded">
              {tag}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
