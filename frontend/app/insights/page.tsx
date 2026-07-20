"use client";

import { Layout } from "@/components/Layout";
import { Protected } from "@/lib/auth";
import { Insights } from "@/components/Insights";

export default function InsightsPage() {
  return (
    <Protected>
      <Layout>
        <Insights />
      </Layout>
    </Protected>
  );
}
