"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { Memory } from "./MemoryCard";

export function MemoryEditor({ id }: { id: string }) {
  const router = useRouter();
  const [memory, setMemory] = useState<Memory | null>(null);
  const [original, setOriginal] = useState<Memory | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api
      .getMemory(id)
      .then((data) => {
        setMemory(data);
        setOriginal(data);
        setLoading(false);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Failed to load memory");
        setLoading(false);
      });
  }, [id]);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!memory || !original) return;
    setSaving(true);
    setError("");
    try {
      // Send only what actually changed. Rewriting the source text triggers
      // full reprocessing, so untouched fields must not be resent.
      const payload: Record<string, unknown> = {};
      if (memory.raw_input !== original.raw_input) payload.raw_input = memory.raw_input;
      if (memory.title !== original.title) payload.title = memory.title;
      if (memory.summary !== original.summary) payload.summary = memory.summary;
      if (memory.mood !== original.mood) payload.mood = memory.mood;
      if ((memory.tags || []).join(",") !== (original.tags || []).join(","))
        payload.tags = memory.tags;
      if ((memory.people || []).join(",") !== (original.people || []).join(","))
        payload.people = memory.people;
      if (memory.location !== original.location) payload.location = memory.location;
      if (memory.importance_level !== original.importance_level)
        payload.importance_level = memory.importance_level;
      if (memory.event_date !== original.event_date)
        payload.event_date = memory.event_date;

      if (Object.keys(payload).length === 0) {
        router.push("/search");
        return;
      }

      await api.updateMemory(id, payload);
      router.push("/search");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to update memory");
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!confirm("Delete this memory?")) return;
    try {
      await api.deleteMemory(id);
      router.push("/search");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  };

  if (loading) return <p>Loading...</p>;
  if (error) return <p className="text-red-600">{error}</p>;
  if (!memory) return <p>Memory not found.</p>;

  const update = (key: keyof Memory, value: unknown) =>
    setMemory((m) => (m ? { ...m, [key]: value } : null));

  const sourceChanged =
    original !== null && memory.raw_input !== original.raw_input;

  return (
    <form onSubmit={save} className="max-w-2xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold">Edit memory</h1>

      <section className="space-y-1">
        <Field
          label="Original text"
          hint="The memory exactly as you told it. This is the source everything else is derived from."
        >
          <textarea
            className="w-full border rounded p-3 h-40"
            placeholder="e.g. On May 25th 2011, Maxwell Joseph Francis Cloutier was born."
            value={memory.raw_input || ""}
            onChange={(e) => update("raw_input", e.target.value)}
          />
        </Field>
        {sourceChanged ? (
          <p className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded p-2">
            <strong>You changed the original text.</strong> Saving re-runs the AI
            to regenerate the title, summary, mood, tags and date below. Any
            field you edited on this screen is kept as you set it.
          </p>
        ) : (
          <p className="text-xs text-gray-500">
            Change this only if the memory itself was recorded wrong — the AI
            will re-read it and rebuild the fields below.
          </p>
        )}
      </section>

      <hr className="border-gray-200" />

      <section className="space-y-4">
        <h2 className="font-semibold text-gray-800">Details</h2>
        <Field
          label="Title"
          hint="Short heading, shown in lists and on the timeline."
        >
          <input
            type="text"
            className="w-full border rounded p-2"
            placeholder="e.g. Birth of Maxwell Joseph Francis Cloutier"
            value={memory.title || ""}
            onChange={(e) => update("title", e.target.value)}
          />
        </Field>
        <Field
          label="Summary"
          hint="One or two sentences describing the memory."
        >
          <textarea
            className="w-full border rounded p-3 h-28"
            placeholder="e.g. Maxwell was born on May 25, 2011."
            value={memory.summary || ""}
            onChange={(e) => update("summary", e.target.value)}
          />
        </Field>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field label="Mood" hint="One word, e.g. joyful.">
            <input
              type="text"
              className="w-full border rounded p-2"
              placeholder="joyful"
              value={memory.mood || ""}
              onChange={(e) => update("mood", e.target.value)}
            />
          </Field>
          <Field label="Location" hint="Where it happened, if relevant.">
            <input
              type="text"
              className="w-full border rounded p-2"
              placeholder="e.g. Conway, South Carolina"
              value={memory.location || ""}
              onChange={(e) => update("location", e.target.value)}
            />
          </Field>
          <Field label="Tags" hint="Comma separated. Used for filtering.">
            <input
              type="text"
              className="w-full border rounded p-2"
              placeholder="birth, family, milestone"
              value={(memory.tags || []).join(", ")}
              onChange={(e) =>
                update(
                  "tags",
                  e.target.value.split(",").map((t) => t.trim()).filter(Boolean)
                )
              }
            />
          </Field>
          <Field label="People" hint="Comma separated names mentioned.">
            <input
              type="text"
              className="w-full border rounded p-2"
              placeholder="Maxwell Joseph Francis Cloutier"
              value={(memory.people || []).join(", ")}
              onChange={(e) =>
                update(
                  "people",
                  e.target.value.split(",").map((p) => p.trim()).filter(Boolean)
                )
              }
            />
          </Field>
        </div>

        <Field
          label="Event date"
          hint="When the memory happened. This places it on your timeline — without it, the memory is hidden from the timeline and listed under Review."
        >
          <input
            type="datetime-local"
            className="w-full border rounded p-2"
            value={
              memory.event_date
                ? new Date(memory.event_date).toISOString().slice(0, 16)
                : ""
            }
            onChange={(e) =>
              update(
                "event_date",
                e.target.value ? new Date(e.target.value).toISOString() : undefined
              )
            }
          />
        </Field>

        <Field
          label={`Importance: ${memory.importance_level || 5}/10`}
          hint="How significant this memory is, 1 (minor) to 10 (life-changing)."
        >
          <input
            type="range"
            min={1}
            max={10}
            value={memory.importance_level || 5}
            onChange={(e) => update("importance_level", Number(e.target.value))}
            className="w-full"
          />
        </Field>
      </section>

      <div className="flex gap-3">
        <button
          type="submit"
          disabled={saving}
          className="bg-indigo-600 text-white px-4 py-2 rounded hover:bg-indigo-700 disabled:opacity-50"
        >
          {saving ? "Saving..." : "Save changes"}
        </button>
        <button
          type="button"
          onClick={remove}
          className="bg-red-600 text-white px-4 py-2 rounded hover:bg-red-700"
        >
          Delete
        </button>
      </div>
      {error && <p className="text-red-600">{error}</p>}
    </form>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="block font-medium text-sm text-gray-800 mb-1">{label}</span>
      {children}
      {hint && <span className="block text-xs text-gray-500 mt-1">{hint}</span>}
    </label>
  );
}
