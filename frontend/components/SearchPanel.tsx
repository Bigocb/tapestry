"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { MemoryCard, Memory } from "./MemoryCard";

export function SearchPanel() {
  const [query, setQuery] = useState("");
  const [mood, setMood] = useState("");
  const [tag, setTag] = useState("");
  const [minImportance, setMinImportance] = useState(1);
  const [results, setResults] = useState<Memory[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const fetchLatest = async () => {
    try {
      const data = await api.getMemories(20, 0);
      setResults(data.items || data.memories || data || []);
    } catch (err: any) {
      setError(err.message);
    }
  };

  useEffect(() => {
    fetchLatest();
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const data = await api.search({
        text: query,
        filters: {
          mood: mood || undefined,
          tags: tag ? [tag] : undefined,
          importance_min: minImportance,
        },
      });
      setResults(data.results || []);
    } catch (err: any) {
      setError(err.message || "Search failed");
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm("Delete this memory?")) return;
    try {
      await api.deleteMemory(id);
      setResults((prev) => prev.filter((m) => m.id !== id));
    } catch (err: any) {
      setError(err.message || "Delete failed");
    }
  };

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Search memories</h1>
      <form onSubmit={submit} className="grid grid-cols-1 md:grid-cols-4 gap-3 mb-6">
        <input
          type="text"
          placeholder="Natural language search..."
          className="border rounded p-2 md:col-span-2"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <input
          type="text"
          placeholder="Mood"
          className="border rounded p-2"
          value={mood}
          onChange={(e) => setMood(e.target.value)}
        />
        <input
          type="text"
          placeholder="Tag"
          className="border rounded p-2"
          value={tag}
          onChange={(e) => setTag(e.target.value)}
        />
        <div className="flex items-center gap-2">
          <span className="text-sm">Min importance:</span>
          <input
            type="range"
            min={1}
            max={5}
            value={minImportance}
            onChange={(e) => setMinImportance(Number(e.target.value))}
          />
          <span>{minImportance}</span>
        </div>
        <button
          type="submit"
          disabled={busy}
          className="bg-indigo-600 text-white rounded p-2 hover:bg-indigo-700 disabled:opacity-50"
        >
          {busy ? "Searching..." : "Search"}
        </button>
      </form>
      {error && <p className="text-red-600 mb-4">{error}</p>}
      <div className="grid gap-4">
        {results.map((memory) => (
          <MemoryCard
            key={memory.id}
            memory={memory}
            onDelete={handleDelete}
          />
        ))}
        {results.length === 0 && !busy && <p>No memories found.</p>}
      </div>
    </div>
  );
}
