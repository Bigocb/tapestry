"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";

export interface EntitySummary {
  id: string;
  kind: string;
  canonical_name: string;
  description?: string;
  attributes?: Record<string, unknown>;
  parent_entity_id?: string;
  mention_count: number;
  first_seen_at?: string;
  last_seen_at?: string;
}

/**
 * Browse a kind of entity (people or places).
 *
 * Mention counts come from the server already filtered to visible memories, so
 * a person who appears only in locked memories is absent rather than showing a
 * misleading zero.
 */
export function EntityBrowser({ kind, title }: { kind: string; title: string }) {
  const [items, setItems] = useState<EntitySummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    api
      .getEntities(kind, 200, 0)
      .then((data) => {
        if (!active) return;
        setItems(data.items || []);
        setTotal(data.total ?? 0);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : `Failed to load ${title}`);
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [kind, title]);

  const plural = kind === "person" ? "people" : "places";

  return (
    <div className="max-w-3xl mx-auto">
      <h1 className="text-2xl font-bold mb-2">{title}</h1>
      <p className="text-sm text-gray-500 mb-6">
        {total} {total === 1 ? plural.slice(0, -1) : plural}, most mentioned first.
      </p>

      {error && <p className="text-red-600 mb-4">{error}</p>}
      {loading && <p>Loading...</p>}

      {!loading && items.length === 0 && !error && (
        <p className="text-gray-500">
          No {plural} yet. Capture a memory mentioning one and it will appear here.
        </p>
      )}

      <ul className="space-y-2">
        {items.map((entity) => (
          <li key={entity.id} className="border rounded bg-white">
            <Link
              href={`/entities/${entity.id}`}
              className="flex items-center justify-between p-4 hover:bg-gray-50"
            >
              <span className="font-medium">{entity.canonical_name}</span>
              <span className="text-sm text-gray-500">
                {entity.mention_count}{" "}
                {entity.mention_count === 1 ? "memory" : "memories"}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
