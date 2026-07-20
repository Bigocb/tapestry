"use client";

import { Layout } from "@/components/Layout";
import { Protected } from "@/lib/auth";
import { StoriesPanel } from "@/components/StoriesPanel";

export default function StoriesPage() {
  return (
    <Protected>
      <Layout>
        <StoriesPanel />
      </Layout>
    </Protected>
  );
}
