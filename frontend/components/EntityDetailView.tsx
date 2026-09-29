"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";

interface EntityMemoryRef {
  id: string;
  title?: string;
  summary?: string;
  role?: string;
  event_date?: string;
  date_label?: string;
  created_at: string;
}

interface EntityDetail {
  id: string;
  kind: string;
  canonical_name: string;
  description?: string;
  attributes?: Record<string, unknown>;
  parent_entity_id?: string;
  mention_count: number;
  first_seen_at?: string;
  last_seen_at?: string;
  aliases: string[];
  memories: EntityMemoryRef[];
}

interface EntitySummaryBase {
  id: string;
  canonical_name: string;
  kind: string;
  mention_count: number;
}

interface MergeSuggestion {
  source: EntitySummaryBase;
  target: EntitySummaryBase;
  reason: string;
}

interface AppliedMerge {
  merge_id: string;
  source_id: string;
  target_id: string;
  source_name: string;
  target_name: string;
}

function formatWhen(memory: EntityMemoryRef): string {
  if (memory.date_label) return memory.date_label;
  if (memory.event_date) {
    return new Date(memory.event_date).toLocaleDateString();
  }
  return new Date(memory.created_at).toLocaleDateString();
}

export function EntityDetailView({ id }: { id: string }) {
  const [entity, setEntity] = useState<EntityDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [suggestions, setSuggestions] = useState<MergeSuggestion[]>([]);
  const [busy, setBusy] = useState(false);
  const [lastMerge, setLastMerge] = useState<AppliedMerge | null>(null);
  const [notice, setNotice] = useState("");

  const load = useCallback(() => {
    return api
      .getEntity(id)
      .then((data) => {
        setEntity(data);
        setError("");
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Failed to load entity");
      })
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(() => {
    let active = true;
    load();
    api
      .getMergeSuggestions()
      .then((data) => {
        if (!active) return;
        // Only suggestions involving this entity are actionable here.
        setSuggestions(
          (data || []).filter(
            (s: MergeSuggestion) =>
              s.source.id === id || s.target.id === id
          )
        );
      })
      .catch(() => {
        /* suggestions are optional */
      });
    return () => {
      active = false;
    };
  }, [id, load]);

  const doMerge = async (suggestion: MergeSuggestion) => {
    if (!entity) return;
    setBusy(true);
    setNotice("");
    try {
      const result = await api.mergeEntities(
        suggestion.source.id,
        suggestion.target.id
      );
      setLastMerge({
        merge_id: result.merge_id,
        source_id: suggestion.source.id,
        target_id: suggestion.target.id,
        source_name: suggestion.source.canonical_name,
        target_name: suggestion.target.canonical_name,
      });
      setNotice(
        `Merged ${suggestion.source.canonical_name} into ${suggestion.target.canonical_name}.`
      );
      setSuggestions([]);
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Merge failed");
    } finally {
      setBusy(false);
    }
  };

  const undo = async () => {
    if (!lastMerge) return;
    setBusy(true);
    try {
      await api.undoEntityMerge(lastMerge.merge_id);
      setNotice(
        `Undid the merge of ${lastMerge.source_name} into ${lastMerge.target_name}.`
      );
      setLastMerge(null);
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Undo failed");
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <p>Loading...</p>;
  if (error) return <p className="text-red-600">{error}</p>;
  if (!entity) return <p>Entity not found.</p>;

  const kindLabel =
    entity.kind === "person"
      ? "Person"
      : entity.kind === "place"
        ? "Place"
        : "Organization";

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div>
        <p className="text-sm text-gray-500">{kindLabel}</p>
        <h1 className="text-2xl font-bold">{entity.canonical_name}</h1>
        <p className="text-sm text-gray-500 mt-1">
          {entity.mention_count}{" "}
          {entity.mention_count === 1 ? "memory" : "memories"}
        </p>
      </div>

      {notice && (
        <div className="bg-green-50 border border-green-200 rounded p-3 text-sm flex items-center justify-between gap-3">
          <span>{notice}</span>
          {lastMerge && (
            <button
              onClick={undo}
              disabled={busy}
              className="text-green-800 underline disabled:opacity-50 shrink-0"
            >
              Undo merge
            </button>
          )}
        </div>
      )}

      {entity.aliases.length > 0 && (
        <section>
          <h2 className="font-semibold mb-2">Also known as</h2>
          <div className="flex flex-wrap gap-2">
            {entity.aliases.map((alias) => (
              <span
                key={alias}
                className="text-xs bg-gray-100 text-gray-700 px-2 py-1 rounded"
              >
                {alias}
              </span>
            ))}
          </div>
        </section>
      )}

      {suggestions.length > 0 && (
        <section className="border border-amber-200 bg-amber-50 rounded p-4">
          <h2 className="font-semibold mb-1">Possible duplicate</h2>
          {suggestions.map((s) => (
            <div
              key={`${s.source.id}-${s.target.id}`}
              className="flex items-center justify-between gap-3 text-sm"
            >
              <span>
                &ldquo;{s.source.canonical_name}&rdquo; may be the same as{" "}
                &ldquo;{s.target.canonical_name}&rdquo;.
              </span>
              <button
                onClick={() => doMerge(s)}
                disabled={busy}
                className="bg-amber-600 text-white px-3 py-1 rounded hover:bg-amber-700 disabled:opacity-50 shrink-0"
              >
                {busy ? "Merging..." : "Merge them"}
              </button>
            </div>
          ))}
          <p className="text-xs text-amber-800 mt-2">
            Merging keeps the more-used name and is reversible.
          </p>
        </section>
      )}

      <section>
        <h2 className="font-semibold mb-3">Memories</h2>
        <ul className="space-y-2">
          {entity.memories.map((memory) => (
            <li key={memory.id} className="border rounded p-3 bg-white">
              <Link
                href={`/memories/${memory.id}`}
                className="font-medium hover:text-indigo-600"
              >
                {memory.title || memory.summary || "Untitled memory"}
              </Link>
              <p className="text-sm text-gray-500 mt-1">
                {formatWhen(memory)}
                {memory.role && (
                  <span className="ml-2 text-xs bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded">
                    {memory.role}
                  </span>
                )}
              </p>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
