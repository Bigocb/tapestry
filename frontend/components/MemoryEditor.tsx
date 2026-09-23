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
    <form onSubmit={save} className="max-w-2xl mx-auto space-y-4">
      <h1 className="text-2xl font-bold">Edit memory</h1>

      <label className="block">
        Original text
        <textarea
          className="w-full border rounded p-3 h-40"
          placeholder="The memory as you told it"
          value={memory.raw_input || ""}
          onChange={(e) => update("raw_input", e.target.value)}
        />
      </label>
      {sourceChanged && (
        <p className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded p-2">
          You changed the original text. Saving will re-run the AI to re-extract
          the title, summary, entities, mood and date. Fields you edited here
          will be kept.
        </p>
      )}

      <input
        type="text"
        placeholder="Title"
        className="w-full border rounded p-2"
        value={memory.title || ""}
        onChange={(e) => update("title", e.target.value)}
      />
      <textarea
        className="w-full border rounded p-3 h-32"
        placeholder="Summary"
        value={memory.summary || ""}
        onChange={(e) => update("summary", e.target.value)}
      />
      <div className="grid grid-cols-2 gap-4">
        <input
          type="text"
          placeholder="Mood"
          className="border rounded p-2"
          value={memory.mood || ""}
          onChange={(e) => update("mood", e.target.value)}
        />
        <input
          type="text"
          placeholder="Location"
          className="border rounded p-2"
          value={memory.location || ""}
          onChange={(e) => update("location", e.target.value)}
        />
        <input
          type="text"
          placeholder="Tags (comma separated)"
          className="border rounded p-2"
          value={(memory.tags || []).join(", ")}
          onChange={(e) =>
            update(
              "tags",
              e.target.value.split(",").map((t) => t.trim()).filter(Boolean)
            )
          }
        />
        <input
          type="text"
          placeholder="People (comma separated)"
          className="border rounded p-2"
          value={(memory.people || []).join(", ")}
          onChange={(e) =>
            update(
              "people",
              e.target.value.split(",").map((p) => p.trim()).filter(Boolean)
            )
          }
        />
        <label className="block col-span-2">
          Event date
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
        </label>
      </div>
      <label className="block">
        Importance (1-10)
        <input
          type="range"
          min={1}
          max={10}
          value={memory.importance_level || 5}
          onChange={(e) => update("importance_level", Number(e.target.value))}
          className="w-full"
        />
        <span className="text-sm text-gray-500">{memory.importance_level || 5}</span>
      </label>
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
