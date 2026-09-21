"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { Memory } from "./MemoryCard";

export function MemoryEditor({ id }: { id: string }) {
  const router = useRouter();
  const [memory, setMemory] = useState<Memory | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api
      .getMemory(id)
      .then((data) => {
        setMemory(data);
        setLoading(false);
      })
      .catch((err: any) => {
        setError(err.message || "Failed to load memory");
        setLoading(false);
      });
  }, [id]);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!memory) return;
    setSaving(true);
    setError("");
    try {
      await api.updateMemory(id, {
        refined_text: memory.refined_text,
        title: memory.title,
        mood: memory.mood,
        tags: memory.tags,
        people: memory.people,
        location: memory.location,
        importance_score: memory.importance_score,
        event_date: memory.event_date,
      });
      router.push("/search");
    } catch (err: any) {
      setError(err.message || "Failed to update memory");
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!confirm("Delete this memory?")) return;
    try {
      await api.deleteMemory(id);
      router.push("/search");
    } catch (err: any) {
      setError(err.message || "Delete failed");
    }
  };

  if (loading) return <p>Loading...</p>;
  if (error) return <p className="text-red-600">{error}</p>;
  if (!memory) return <p>Memory not found.</p>;

  const update = (key: keyof Memory, value: any) =>
    setMemory((m) => (m ? { ...m, [key]: value } : null));

  return (
    <form onSubmit={save} className="max-w-2xl mx-auto space-y-4">
      <h1 className="text-2xl font-bold">Edit memory</h1>
      <input
        type="text"
        placeholder="Title"
        className="w-full border rounded p-2"
        value={memory.title || ""}
        onChange={(e) => update("title", e.target.value)}
      />
      <textarea
        className="w-full border rounded p-3 h-40"
        placeholder="Refined text"
        value={memory.refined_text || memory.raw_input}
        onChange={(e) => update("refined_text", e.target.value)}
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
        Importance (1-5)
        <input
          type="range"
          min={1}
          max={5}
          value={memory.importance_score || 3}
          onChange={(e) => update("importance_score", Number(e.target.value))}
          className="w-full"
        />
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
