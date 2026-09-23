"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Memory } from "./MemoryCard";

interface Story {
  id: string;
  title: string;
  story_type: string;
  content: string;
  created_at: string;
}

export function StoriesPanel() {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [storyType, setStoryType] = useState("chronological");
  const [prompt, setPrompt] = useState("");
  const [stories, setStories] = useState<Story[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .getMemories(200, 0)
      .then((data) => {
        const items: Memory[] = data.items || data.memories || data || [];
        setMemories(items);
      })
      .catch((err: any) => setError(err.message || "Failed to load memories"));
    loadStories();
  }, []);

  const loadStories = async () => {
    try {
      const data = await api.getStories();
      setStories(data.stories || []);
    } catch {}
  };

  const toggle = (id: string) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  };

  const generate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (selected.size === 0) {
      setError("Select at least one memory");
      return;
    }
    setError("");
    setBusy(true);
    try {
      await api.generateStory({
        memory_ids: Array.from(selected),
        story_type: storyType,
        custom_prompt: prompt || undefined,
      });
      await loadStories();
      setSelected(new Set());
    } catch (err: any) {
      setError(err.message || "Story generation failed");
    } finally {
      setBusy(false);
    }
  };

  const exportStory = async (id: string, format: string) => {
    try {
      const data = await api.exportStory(id, format);
      const blob = new Blob([data.content || JSON.stringify(data, null, 2)], {
        type: format === "json" ? "application/json" : "text/plain",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `story-${id}.${format}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err: any) {
      setError(err.message || "Export failed");
    }
  };

  return (
    <div className="space-y-8">
      <section>
        <h1 className="text-2xl font-bold mb-4">Build a story</h1>
        {error && <p className="text-red-600 mb-4">{error}</p>}
        <form onSubmit={generate} className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-h-64 overflow-y-auto border rounded p-3">
            {memories.map((memory) => (
              <label key={memory.id} className="flex items-start gap-2">
                <input
                  type="checkbox"
                  checked={selected.has(memory.id)}
                  onChange={() => toggle(memory.id)}
                />
                <span className="text-sm">
                  {memory.title || memory.summary || memory.raw_input}
                </span>
              </label>
            ))}
          </div>
          <select
            className="border rounded p-2"
            value={storyType}
            onChange={(e) => setStoryType(e.target.value)}
          >
            <option value="chronological">Chronological</option>
            <option value="thematic">Thematic</option>
            <option value="curated">Curated</option>
            <option value="digest">Digest</option>
          </select>
          <input
            type="text"
            placeholder="Custom prompt (optional)"
            className="w-full border rounded p-2"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
          />
          <button
            type="submit"
            disabled={busy}
            className="bg-indigo-600 text-white px-4 py-2 rounded hover:bg-indigo-700 disabled:opacity-50"
          >
            {busy ? "Generating..." : "Generate story"}
          </button>
        </form>
      </section>

      <section>
        <h2 className="text-xl font-bold mb-4">Your stories</h2>
        <div className="grid gap-4">
          {stories.map((story) => (
            <div key={story.id} className="border rounded p-4 bg-white">
              <div className="flex justify-between items-start">
                <div>
                  <h3 className="font-semibold">{story.title}</h3>
                  <p className="text-sm text-gray-500">
                    {story.story_type} ·{" "}
                    {new Date(story.created_at).toLocaleDateString()}
                  </p>
                </div>
                <div className="flex gap-2">
                  {["markdown", "txt", "json"].map((fmt) => (
                    <button
                      key={fmt}
                      onClick={() => exportStory(story.id, fmt)}
                      className="text-xs bg-gray-100 hover:bg-gray-200 px-2 py-1 rounded"
                    >
                      .{fmt}
                    </button>
                  ))}
                </div>
              </div>
              <div className="mt-3 prose prose-sm max-w-none">
                <pre className="whitespace-pre-wrap font-sans text-gray-700">
                  {story.content}
                </pre>
              </div>
            </div>
          ))}
          {stories.length === 0 && <p>No stories yet.</p>}
        </div>
      </section>
    </div>
  );
}
