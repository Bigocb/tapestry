"use client";

import { Layout } from "@/components/Layout";
import { Protected } from "@/lib/auth";
import { CapturePanel } from "@/components/CapturePanel";
import { TellingCapture } from "@/components/TellingCapture";

export default function CapturePage() {
  return (
    <Protected>
      <Layout>
        <CapturePanel />
        <section className="max-w-2xl mx-auto mt-12">
          <h2 className="text-2xl font-bold mb-2">Or tell the whole story</h2>
          <p className="text-gray-600 mb-4">
            Give one long account and review how it splits into memories before
            anything is saved.
          </p>
          <TellingCapture />
        </section>
      </Layout>
    </Protected>
  );
}
