"use client";

import { useParams } from "next/navigation";
import { Layout } from "@/components/Layout";
import { Protected } from "@/lib/auth";
import { EntityDetailView } from "@/components/EntityDetailView";

export default function EntityPage() {
  const params = useParams();
  const id = params.id as string;

  return (
    <Protected>
      <Layout>
        <EntityDetailView id={id} />
      </Layout>
    </Protected>
  );
}
