"use client";

import { Layout } from "@/components/Layout";
import { Protected } from "@/lib/auth";
import { EntityBrowser } from "@/components/EntityBrowser";

export default function PeoplePage() {
  return (
    <Protected>
      <Layout>
        <EntityBrowser kind="person" title="People" />
      </Layout>
    </Protected>
  );
}
