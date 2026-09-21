"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Legend,
} from "recharts";

interface Stats {
  total_memories: number;
  memories_by_mood: Record<string, number>;
  memories_by_tag: Record<string, number>;
  average_importance: number;
}

interface TrendPoint {
  timestamp: string;
  value: number;
}

interface Trends {
  memories_per_week: TrendPoint[];
  mood_trend: TrendPoint[];
}

interface WordCloudItem {
  word: string;
  frequency: number;
}

interface Achievement {
  id: string;
  name: string;
  description: string;
  earned: boolean;
  progress?: number;
}

export function Insights() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [trends, setTrends] = useState<Trends | null>(null);
  const [wordCloud, setWordCloud] = useState<WordCloudItem[]>([]);
  const [achievements, setAchievements] = useState<Achievement[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      api.getInsightsStats(),
      api.getInsightsTrends(),
      api.getInsightsWordCloud(),
      api.getInsightsAchievements(),
    ])
      .then(([statsData, trendsData, cloudData, achievementData]) => {
        setStats(statsData);
        setTrends(trendsData);
        setWordCloud(cloudData || []);
        setAchievements(achievementData || []);
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load insights")
      );
  }, []);

  const moodCounts = useMemo(
    () =>
      Object.entries(stats?.memories_by_mood || {}).map(([name, value]) => ({
        name,
        value,
      })),
    [stats]
  );

  const tagCounts = useMemo(
    () =>
      Object.entries(stats?.memories_by_tag || {})
        .map(([name, value]) => ({ name, value }))
        .sort((a, b) => b.value - a.value)
        .slice(0, 10),
    [stats]
  );

  const monthlyCounts = useMemo(
    () =>
      (trends?.memories_per_week || []).map((point) => ({
        name: new Date(point.timestamp).toLocaleDateString(),
        value: point.value,
      })),
    [trends]
  );

  const COLORS = ["#4f46e5", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6"];

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Insights</h1>
      {error && <p className="text-red-600 mb-4">{error}</p>}

      {stats && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
          <div className="bg-white border rounded p-4">
            <p className="text-sm text-gray-500">Total memories</p>
            <p className="text-3xl font-bold">{stats.total_memories}</p>
          </div>
          <div className="bg-white border rounded p-4">
            <p className="text-sm text-gray-500">Avg importance</p>
            <p className="text-3xl font-bold">
              {stats.average_importance.toFixed(1)}
            </p>
          </div>
          <div className="bg-white border rounded p-4">
            <p className="text-sm text-gray-500">Distinct tags</p>
            <p className="text-3xl font-bold">{tagCounts.length}</p>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="bg-white border rounded p-4">
          <h2 className="font-semibold mb-2">Memories over time</h2>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={monthlyCounts}>
                <XAxis dataKey="name" />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="value" fill="#4f46e5" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="bg-white border rounded p-4">
          <h2 className="font-semibold mb-2">Moods</h2>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={moodCounts}
                  dataKey="value"
                  nameKey="name"
                  cx="50%"
                  cy="50%"
                  outerRadius={80}
                >
                  {moodCounts.map((_, index) => (
                    <Cell key={index} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Legend />
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="bg-white border rounded p-4 md:col-span-2">
          <h2 className="font-semibold mb-2">Top tags</h2>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={tagCounts} layout="vertical">
                <XAxis type="number" allowDecimals={false} />
                <YAxis dataKey="name" type="category" width={100} />
                <Tooltip />
                <Bar dataKey="value" fill="#10b981" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="bg-white border rounded p-4 md:col-span-2">
          <h2 className="font-semibold mb-2">Word cloud</h2>
          <div className="flex flex-wrap gap-2">
            {wordCloud.map((item) => (
              <span
                key={item.word}
                className="bg-indigo-50 text-indigo-700 px-2 py-1 rounded"
                style={{ fontSize: `${Math.min(24, 11 + item.frequency * 2)}px` }}
              >
                {item.word}
              </span>
            ))}
            {wordCloud.length === 0 && (
              <p className="text-gray-500 text-sm">No words yet.</p>
            )}
          </div>
        </div>

        <div className="bg-white border rounded p-4 md:col-span-2">
          <h2 className="font-semibold mb-2">Achievements</h2>
          <ul className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {achievements.map((a) => (
              <li
                key={a.id}
                className={`border rounded p-3 ${
                  a.earned ? "bg-green-50 border-green-300" : ""
                }`}
              >
                <div className="flex justify-between">
                  <span className="font-medium">{a.name}</span>
                  {a.earned && <span className="text-green-700 text-sm">Earned</span>}
                </div>
                <p className="text-sm text-gray-500">{a.description}</p>
                {!a.earned && a.progress !== undefined && (
                  <div className="w-full bg-gray-200 rounded h-2 mt-2">
                    <div
                      className="bg-indigo-600 h-2 rounded"
                      style={{ width: `${Math.round(a.progress * 100)}%` }}
                    />
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
