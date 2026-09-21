"use client";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/api";

function getToken() {
  if (typeof window === "undefined") return null;
  try {
    return localStorage.getItem("token");
  } catch {
    return null;
  }
}

async function request(
  method: string,
  path: string,
  body?: unknown,
  params?: Record<string, string | number | undefined>
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

  const response = await fetch(url.toString(), {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (response.status === 204) return null;

  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(data?.detail || `Request failed: ${response.status}`);
  }
  return data;
}

export const api = {
  login: (username: string, password: string) =>
    request("POST", "/auth/login", { username, password }),
  register: (username: string, email: string, password: string) =>
    request("POST", "/auth/register", { username, email, password }),

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
  updateMemory: (id: string, update: Record<string, unknown>) =>
    request("PATCH", `/memories/${id}`, update),
  deleteMemory: (id: string) => request("DELETE", `/memories/${id}`),

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
};
