"use client";

import { Layout } from "@/components/Layout";
import { Protected } from "@/lib/auth";
import { EntityBrowser } from "@/components/EntityBrowser";

export default function PlacesPage() {
  return (
    <Protected>
      <Layout>
        <EntityBrowser kind="place" title="Places" />
      </Layout>
    </Protected>
  );
}
