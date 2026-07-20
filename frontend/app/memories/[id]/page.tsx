"use client";

import { useParams } from "next/navigation";
import { Layout } from "@/components/Layout";
import { Protected } from "@/lib/auth";
import { MemoryEditor } from "@/components/MemoryEditor";

export default function MemoryPage() {
  const params = useParams();
  const id = params.id as string;

  return (
    <Protected>
      <Layout>
        <MemoryEditor id={id} />
      </Layout>
    </Protected>
  );
}
