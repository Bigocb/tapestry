"use client";

import { Layout } from "@/components/Layout";
import { Protected } from "@/lib/auth";
import { ReviewQueue } from "@/components/ReviewQueue";

export default function ReviewPage() {
  return (
    <Protected>
      <Layout>
        <ReviewQueue />
      </Layout>
    </Protected>
  );
}
