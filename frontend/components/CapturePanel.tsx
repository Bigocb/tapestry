"use client";

import { useState, useRef } from "react";
import { api } from "@/lib/api";
import { TellingCapture } from "@/components/TellingCapture";

export function CapturePanel() {
  const [mode, setMode] = useState<"text" | "voice" | "form" | "story">("text");

  return (
    <div className="max-w-2xl mx-auto">
      <h1 className="text-2xl font-bold mb-4">Capture a memory</h1>
      <div className="flex gap-2 mb-6">
        <ModeButton active={mode === "text"} onClick={() => setMode("text")}>
          Text
        </ModeButton>
        <ModeButton active={mode === "voice"} onClick={() => setMode("voice")}>
          Voice
        </ModeButton>
        <ModeButton active={mode === "form"} onClick={() => setMode("form")}>
          Form
        </ModeButton>
        <ModeButton active={mode === "story"} onClick={() => setMode("story")}>
          Story
        </ModeButton>
      </div>
      {mode === "text" && <TextCapture />}
      {mode === "voice" && <VoiceCapture />}
      {mode === "form" && <FormCapture />}
      {mode === "story" && <TellingCapture />}
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
      onClick={onClick}
      className={`px-4 py-2 rounded ${
        active
          ? "bg-indigo-600 text-white"
          : "bg-gray-100 text-gray-700 hover:bg-gray-200"
      }`}
    >
      {children}
    </button>
  );
}

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
        className="w-full border rounded p-3 h-40"
        placeholder="What happened today?"
        value={raw}
        onChange={(e) => setRaw(e.target.value)}
        required
      />
      <button
        type="submit"
        disabled={busy}
        className="bg-indigo-600 text-white px-4 py-2 rounded hover:bg-indigo-700 disabled:opacity-50"
      >
        {busy ? "Processing..." : "Capture"}
      </button>
      {error && <p className="text-red-600">{error}</p>}
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
    <div className="space-y-4">
      <button
        onClick={recording ? stop : start}
        className={`px-6 py-3 rounded-full font-semibold ${
          recording
            ? "bg-red-600 text-white animate-pulse"
            : "bg-indigo-600 text-white hover:bg-indigo-700"
        }`}
      >
        {recording ? "Stop Recording" : "Start Recording"}
      </button>
      {error && <p className="text-red-600">{error}</p>}
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
        className="w-full border rounded p-3 h-32"
        placeholder="Memory description"
        value={fields.raw_input}
        onChange={(e) => update("raw_input", e.target.value)}
        required
      />
      <div className="grid grid-cols-2 gap-4">
        <input
          type="text"
          placeholder="Mood"
          className="border rounded p-2"
          value={fields.mood}
          onChange={(e) => update("mood", e.target.value)}
        />
        <input
          type="text"
          placeholder="Location"
          className="border rounded p-2"
          value={fields.location}
          onChange={(e) => update("location", e.target.value)}
        />
        <input
          type="text"
          placeholder="Tags (comma separated)"
          className="border rounded p-2"
          value={fields.tags}
          onChange={(e) => update("tags", e.target.value)}
        />
        <input
          type="text"
          placeholder="People (comma separated)"
          className="border rounded p-2"
          value={fields.people}
          onChange={(e) => update("people", e.target.value)}
        />
      </div>
      <label className="block">
        Importance (1-5)
        <input
          type="range"
          min={1}
          max={5}
          value={fields.importance_level}
          onChange={(e) => update("importance_level", Number(e.target.value))}
          className="w-full"
        />
      </label>
      <button
        type="submit"
        disabled={busy}
        className="bg-indigo-600 text-white px-4 py-2 rounded hover:bg-indigo-700 disabled:opacity-50"
      >
        {busy ? "Processing..." : "Capture"}
      </button>
      {error && <p className="text-red-600">{error}</p>}
      {result && <MemoryPreview memory={result} />}
    </form>
  );
}

function MemoryPreview({ memory }: { memory: any }) {
  return (
    <div className="border rounded p-4 bg-green-50">
      <h3 className="font-semibold text-green-800">Memory captured</h3>
      <p className="text-sm text-gray-600">Status: {memory.processing_state}</p>
      <p className="mt-2">{memory.summary || memory.raw_input}</p>
      {memory.tags?.length > 0 && (
        <p className="text-sm mt-2">Tags: {memory.tags.join(", ")}</p>
      )}
    </div>
  );
}
