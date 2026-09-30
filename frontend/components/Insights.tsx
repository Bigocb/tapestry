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

  const COLORS = ["#ffd23f", "#8b87ff", "#5fe3b3", "#ff6b5e", "#e6bb2e"];
  const chartAxisProps = { stroke: "#5e5969", fontSize: 12 };
  const tooltipStyle = {
    background: "#201d27",
    border: "1px solid #322e3b",
    borderRadius: 8,
    color: "#f4f2f6",
    fontSize: 13,
  };

  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">Insights</h1>
      {error && <p className="text-coral mb-4">{error}</p>}

      {stats && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
          <div className="bg-surface border border-line rounded-2xl p-4">
            <p className="stamp text-ink-muted">Total memories</p>
            <p className="font-mono text-3xl mt-1">{stats.total_memories}</p>
          </div>
          <div className="bg-surface border border-line rounded-2xl p-4">
            <p className="stamp text-ink-muted">Avg importance</p>
            <p className="font-mono text-3xl mt-1">
              {stats.average_importance.toFixed(1)}
            </p>
          </div>
          <div className="bg-surface border border-line rounded-2xl p-4">
            <p className="stamp text-ink-muted">Distinct tags</p>
            <p className="font-mono text-3xl mt-1">{tagCounts.length}</p>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="bg-surface border border-line rounded-2xl p-4">
          <h2 className="font-semibold mb-2">Memories over time</h2>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={monthlyCounts}>
                <XAxis dataKey="name" {...chartAxisProps} />
                <YAxis allowDecimals={false} {...chartAxisProps} />
                <Tooltip contentStyle={tooltipStyle} />
                <Bar dataKey="value" fill="#ffd23f" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="bg-surface border border-line rounded-2xl p-4">
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
                <Legend wrapperStyle={{ fontSize: 13, color: "#948fa0" }} />
                <Tooltip contentStyle={tooltipStyle} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="bg-surface border border-line rounded-2xl p-4 md:col-span-2">
          <h2 className="font-semibold mb-2">Top tags</h2>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={tagCounts} layout="vertical">
                <XAxis type="number" allowDecimals={false} {...chartAxisProps} />
                <YAxis dataKey="name" type="category" width={100} {...chartAxisProps} />
                <Tooltip contentStyle={tooltipStyle} />
                <Bar dataKey="value" fill="#5fe3b3" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="bg-surface border border-line rounded-2xl p-4 md:col-span-2">
          <h2 className="font-semibold mb-2">Word cloud</h2>
          <div className="flex flex-wrap gap-2">
            {wordCloud.map((item) => (
              <span
                key={item.word}
                className="bg-violet/10 text-violet px-2 py-1 rounded"
                style={{ fontSize: `${Math.min(24, 11 + item.frequency * 2)}px` }}
              >
                {item.word}
              </span>
            ))}
            {wordCloud.length === 0 && (
              <p className="text-ink-muted text-sm">No words yet.</p>
            )}
          </div>
        </div>

        <div className="bg-surface border border-line rounded-2xl p-4 md:col-span-2">
          <h2 className="font-semibold mb-2">Achievements</h2>
          <ul className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {achievements.map((a) => (
              <li
                key={a.id}
                className={`border rounded-xl p-3 ${
                  a.earned ? "bg-mint/10 border-mint/30" : "border-line"
                }`}
              >
                <div className="flex justify-between">
                  <span className="font-medium">{a.name}</span>
                  {a.earned && <span className="text-mint text-sm">Earned</span>}
                </div>
                <p className="text-sm text-ink-muted">{a.description}</p>
                {!a.earned && a.progress !== undefined && (
                  <div className="w-full bg-surface-2 rounded h-2 mt-2">
                    <div
                      className="bg-flash h-2 rounded"
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
