"use client";

import { useParams } from "next/navigation";

import { Layout } from "@/components/Layout";
import { TellingReview } from "@/components/TellingReview";
import { Protected } from "@/lib/auth";

export default function TellingPage() {
  const params = useParams();
  const id = params.id as string;

  return (
    <Protected>
      <Layout>
        <TellingReview tellingId={id} />
      </Layout>
    </Protected>
  );
}
