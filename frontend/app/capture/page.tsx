"use client";

import { Layout } from "@/components/Layout";
import { Protected } from "@/lib/auth";
import { CapturePanel } from "@/components/CapturePanel";

export default function CapturePage() {
  return (
    <Protected>
      <Layout>
        <CapturePanel />
      </Layout>
    </Protected>
  );
}
