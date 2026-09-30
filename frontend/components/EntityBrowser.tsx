"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { MapPinIcon } from "@heroicons/react/24/outline";

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
  const isPerson = kind === "person";

  return (
    <div>
      <h1 className="text-3xl font-bold mb-2">{title}</h1>
      <p className="stamp text-ink-muted mb-6">
        {total} {total === 1 ? plural.slice(0, -1) : plural} &middot; most mentioned first
      </p>

      {error && <p className="text-coral mb-4">{error}</p>}
      {loading && <p className="text-ink-muted">Loading&hellip;</p>}

      {!loading && items.length === 0 && !error && (
        <p className="text-ink-muted border border-dashed border-line rounded-lg p-6">
          No {plural} yet. Capture a memory mentioning one and it will appear here.
        </p>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {items.map((entity) => (
          <Link
            key={entity.id}
            href={`/entities/${entity.id}`}
            className="flex items-center gap-3 p-4 bg-surface border border-line rounded-lg hover:border-flash transition"
          >
            <span
              className={`shrink-0 w-10 h-10 rounded-full flex items-center justify-center font-display text-lg ${
                isPerson ? "bg-violet/15 text-violet" : "bg-mint/15 text-mint"
              }`}
            >
              {isPerson ? (
                entity.canonical_name.charAt(0).toUpperCase()
              ) : (
                <MapPinIcon className="w-5 h-5" />
              )}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block font-medium text-ink truncate">
                {entity.canonical_name}
              </span>
              <span className="block stamp text-ink-muted mt-0.5">
                {entity.mention_count}{" "}
                {entity.mention_count === 1 ? "memory" : "memories"}
              </span>
            </span>
          </Link>
        ))}
      </div>
    </div>
  );
}
