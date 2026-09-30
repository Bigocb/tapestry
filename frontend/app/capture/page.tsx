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
        <section>
          <h2>Or tell the whole story</h2>
          <p>
            Give one long account and review how it splits into memories before
            anything is saved.
          </p>
          <TellingCapture />
        </section>
      </Layout>
    </Protected>
  );
}
