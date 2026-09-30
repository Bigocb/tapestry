"use client";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "/api";

function getToken() {
  if (typeof window === "undefined") return null;
  try {
    return localStorage.getItem("token");
  } catch {
    return null;
  }
}

function setToken(token: string | null) {
  if (typeof window === "undefined") return;
  try {
    if (token) localStorage.setItem("token", token);
    else localStorage.removeItem("token");
  } catch {
    // ignore storage errors
  }
}

function redirectToLogin() {
  if (typeof window === "undefined") return;
  if (window.location.pathname === "/login") return;
  window.location.href = "/login";
}

// ---------------------------------------------------------------------------
// Privacy unlocks.
//
// Unlocked memory ids live in sessionStorage, so they are specific to this tab
// and disappear when it closes. Crucially they are NOT persisted, so a page
// refresh re-locks everything.
// ---------------------------------------------------------------------------
const UNLOCKED_KEY = "unlockedMemoryIds";

export function getUnlockedIds(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = sessionStorage.getItem(UNLOCKED_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

export function setUnlockedIds(ids: string[]): void {
  if (typeof window === "undefined") return;
  try {
    sessionStorage.setItem(UNLOCKED_KEY, JSON.stringify(ids));
  } catch {
    // ignore storage errors
  }
}

export function unlockMemory(id: string): void {
  const ids = getUnlockedIds();
  if (!ids.includes(id)) setUnlockedIds([...ids, id]);
}

export function relockMemory(id: string): void {
  setUnlockedIds(getUnlockedIds().filter((existing) => existing !== id));
}

export function relockAll(): void {
  setUnlockedIds([]);
}

let refreshPromise: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  const token = getToken();
  if (!token) return null;

  if (!refreshPromise) {
    refreshPromise = fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    })
      .then(async (response) => {
        if (!response.ok) return null;
        const data = await response.json().catch(() => null);
        if (data?.access_token) {
          setToken(data.access_token);
          return data.access_token as string;
        }
        return null;
      })
      .catch(() => null)
      .finally(() => {
        refreshPromise = null;
      });
  }

  return refreshPromise;
}

async function request(
  method: string,
  path: string,
  body?: unknown,
  params?: Record<string, string | number | undefined>,
  allowRetry = true
) {
  const url = new URL(`${API_BASE}${path}`, window.location.origin);
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined) url.searchParams.set(key, String(value));
    });
  }

  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (body) headers["Content-Type"] = "application/json";

  // Tell the backend which private memories this session has unlocked.
  const unlocked = getUnlockedIds();
  if (unlocked.length > 0) {
    headers["X-Unlocked-Memory-Ids"] = unlocked.join(",");
  }

  let response: Response;
  try {
    response = await fetch(url.toString(), {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    // fetch only rejects on network-level failures. A server error that
    // crashes before CORS headers are attached also lands here, so don't claim
    // the server is unreachable when it may simply have errored.
    throw new Error(`Could not reach the server (${method} ${path}).`);
  }

  if (response.status === 204) return null;

  // On an expired/invalid token, try one refresh, then retry the request.
  if (response.status === 401 && allowRetry) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      return request(method, path, body, params, false);
    }
    setToken(null);
    redirectToLogin();
    throw new Error("Session expired. Please log in again.");
  }

  const data = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status >= 500) {
      throw new Error(
        data?.detail || `Server error (${response.status}) on ${method} ${path}.`
      );
    }
    throw new Error(data?.detail || `Request failed: ${response.status}`);
  }
  return data;
}

export interface TellingSegment {
  id: string;
  ordinal: number;
  text: string;
  status: string;
  title?: string | null;
  summary?: string | null;
  event_date?: string | null;
  date_precision?: string | null;
  date_label?: string | null;
  memory_id?: string | null;
}

export interface TellingSegmentUpdate {
  text?: string;
  title?: string;
  summary?: string;
  status?: string;
  event_date?: string | null;
  event_date_end?: string | null;
  date_precision?: string | null;
  date_label?: string | null;
}

export interface Telling {
  id: string;
  raw_transcript: string;
  input_type: string;
  status: string;
  error?: string | null;
  frame_label?: string | null;
  created_at: string;
  segments: TellingSegment[];
}

export const api = {
  // No token dance on these two: a 401 here means the credentials were wrong,
  // not that a session expired. Retrying through the refresh path discards any
  // stored token and reports "Session expired", hiding the server's real reason
  // — which on a phone is usually an autocapitalised username.
  login: (username: string, password: string) =>
    request("POST", "/auth/login", { username, password }, undefined, false),
  register: (username: string, email: string, password: string) =>
    request(
      "POST",
      "/auth/register",
      { username, email, password },
      undefined,
      false
    ),
  getSessionConfig: () => request("GET", "/auth/session-config"),

  captureText: (raw_input: string) =>
    request("POST", "/memories/capture/text", { raw_input }),
  captureForm: (data: {
    raw_input: string;
    mood?: string;
    tags?: string[];
    people?: string[];
    location?: string;
    importance_level?: number;
  }) => request("POST", "/memories/capture/form", data),
  captureVoice: (file: File) => {
    const form = new FormData();
    form.append("audio", file);
    return fetch(`${API_BASE}/memories/capture/voice`, {
      method: "POST",
      headers: { Authorization: `Bearer ${getToken() || ""}` },
      body: form,
    }).then(async (r) => {
      if (r.status === 401) {
        const refreshed = await refreshAccessToken();
        if (refreshed) {
          return fetch(`${API_BASE}/memories/capture/voice`, {
            method: "POST",
            headers: { Authorization: `Bearer ${refreshed}` },
            body: form,
          }).then(async (retry) => {
            const data = await retry.json().catch(() => null);
            if (!retry.ok) throw new Error(data?.detail || `Request failed: ${retry.status}`);
            return data;
          });
        }
        setToken(null);
        redirectToLogin();
        throw new Error("Session expired. Please log in again.");
      }
      const data = await r.json().catch(() => null);
      if (!r.ok) throw new Error(data?.detail || `Request failed: ${r.status}`);
      return data;
    });
  },

  search: (query: {
    text?: string;
    semantic?: string;
    filters?: {
      tags?: string[];
      mood?: string;
      importance_min?: number;
      importance_max?: number;
    };
    limit?: number;
    offset?: number;
  }) => request("POST", "/memories/search", query),
  getMemories: (limit = 20, offset = 0) =>
    request("GET", "/memories", undefined, { limit, offset }),
  getTimeline: (params?: {
    start_date?: string;
    end_date?: string;
    tags?: string;
    mood?: string;
    limit?: number;
    offset?: number;
    order?: string;
  }) => request("GET", "/timeline", undefined, params),
  getMemory: (id: string) => request("GET", `/memories/${id}`),
  getRelatedMemories: (id: string, limit = 5) =>
    request("GET", `/memories/${id}/related`, undefined, { limit }),
  updateMemory: (
    id: string,
    update: {
      raw_input?: string;
      title?: string;
      summary?: string;
      mood?: string;
      tags?: string[];
      people?: string[];
      location?: string;
      importance_level?: number;
      event_date?: string | null;
      event_date_end?: string | null;
      date_precision?: string | null;
      date_label?: string | null;
      is_private?: boolean;
    }
  ) => request("PATCH", `/memories/${id}`, update),  deleteMemory: (id: string) => request("DELETE", `/memories/${id}`),

  generateStory: (data: {
    memory_ids: string[];
    story_type: string;
    custom_prompt?: string;
  }) => request("POST", "/stories/generate", data),
  getStories: () => request("GET", "/stories"),
  exportStory: (id: string, format: string) =>
    request("POST", `/stories/${id}/export`, { format }),

  getInsightsStats: () => request("GET", "/insights/stats"),
  getInsightsTrends: () => request("GET", "/insights/trends"),
  getInsightsWordCloud: () => request("GET", "/insights/word-cloud"),
  getInsightsAchievements: () => request("GET", "/insights/achievements"),

  getReviewQueue: (limit = 50, offset = 0) =>
    request("GET", "/review", undefined, { limit, offset }),
  getReviewCount: () => request("GET", "/review/count"),

  getEntities: (kind?: string, limit = 50, offset = 0) =>
    request("GET", "/entities", undefined, { kind, limit, offset }),
  getEntityCounts: () => request("GET", "/entities/counts"),
  getEntity: (id: string) => request("GET", `/entities/${id}`),
  getMergeSuggestions: () => request("GET", "/entities/merge-suggestions"),
  mergeEntities: (source_id: string, target_id: string) =>
    request("POST", "/entities/merge", { source_id, target_id }),
  undoEntityMerge: (mergeId: string) =>
    request("POST", `/entities/merge/${mergeId}/undo`, {}),

  createTelling: (raw_transcript: string) =>
    request("POST", "/tellings", { raw_transcript }) as Promise<Telling>,
  getTelling: (id: string) =>
    request("GET", `/tellings/${id}`) as Promise<Telling>,
  createVoiceTelling: (file: File) => {
    const form = new FormData();
    form.append("audio", file);
    return fetch(`${API_BASE}/tellings/voice`, {
      method: "POST",
      headers: { Authorization: `Bearer ${getToken() || ""}` },
      body: form,
    }).then(async (response) => {
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(data?.detail || `Upload failed (${response.status})`);
      }
      return data as Telling;
    });
  },
  updateTellingTranscript: (id: string, rawTranscript: string) =>
    request("PATCH", `/tellings/${id}`, {
      raw_transcript: rawTranscript,
    }) as Promise<Telling>,
  updateTellingSegment: (
    tellingId: string,
    segmentId: string,
    update: TellingSegmentUpdate
  ) =>
    request(
      "PATCH",
      `/tellings/${tellingId}/segments/${segmentId}`,
      update
    ) as Promise<TellingSegment>,
  commitTelling: (id: string) =>
    request("POST", `/tellings/${id}/commit`, {}) as Promise<Telling>,

  // Reshaping a draft. Each returns the whole telling back, so the screen is
  // rebuilt from one source of truth rather than patched locally.
  mergeTellingSegments: (tellingId: string, segmentIds: string[]) =>
    request("POST", `/tellings/${tellingId}/segments/merge`, {
      segment_ids: segmentIds,
    }) as Promise<Telling>,
  splitTellingSegment: (tellingId: string, segmentId: string, at: number) =>
    request("POST", `/tellings/${tellingId}/segments/${segmentId}/split`, {
      at,
    }) as Promise<Telling>,
  deleteTellingSegment: (tellingId: string, segmentId: string) =>
    request(
      "DELETE",
      `/tellings/${tellingId}/segments/${segmentId}`
    ) as Promise<Telling>,
  reorderTellingSegments: (tellingId: string, segmentIds: string[]) =>
    request("POST", `/tellings/${tellingId}/segments/reorder`, {
      segment_ids: segmentIds,
    }) as Promise<Telling>,

  getTellingMemories: (tellingId: string) =>
    request("GET", `/tellings/${tellingId}/memories`) as Promise<unknown[]>,
  deleteTellingMemories: (tellingId: string) =>
    request("DELETE", `/tellings/${tellingId}/memories`) as Promise<Telling>,
};
