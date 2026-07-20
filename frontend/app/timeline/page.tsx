"use client";

import { Layout } from "@/components/Layout";
import { Protected } from "@/lib/auth";
import { Timeline } from "@/components/Timeline";

export default function TimelinePage() {
  return (
    <Protected>
      <Layout>
        <Timeline />
      </Layout>
    </Protected>
  );
}
