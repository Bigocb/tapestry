"use client";

import { Layout } from "@/components/Layout";
import { Protected } from "@/lib/auth";
import { SearchPanel } from "@/components/SearchPanel";

export default function SearchPage() {
  return (
    <Protected>
      <Layout>
        <SearchPanel />
      </Layout>
    </Protected>
  );
}
