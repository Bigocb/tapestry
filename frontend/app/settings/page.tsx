"use client";

import { Layout } from "@/components/Layout";
import { Protected } from "@/lib/auth";
import { SettingsPanel } from "@/components/SettingsPanel";

export default function SettingsPage() {
  return (
    <Protected>
      <Layout>
        <SettingsPanel />
      </Layout>
    </Protected>
  );
}
