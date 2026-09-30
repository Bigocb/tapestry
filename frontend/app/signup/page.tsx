"use client";

import Link from "next/link";
import { Layout } from "@/components/Layout";
import { SignupForm } from "@/components/AuthForm";

export default function SignupPage() {
  return (
    <Layout>
      <div className="min-h-screen flex items-center justify-center px-4">
        <div className="w-full max-w-sm">
          <div className="flex items-center justify-center gap-2 mb-6">
            <span className="w-2.5 h-2.5 rounded-full bg-flash fab-pulse" />
            <span className="font-display text-lg">Tapestry</span>
          </div>
          <div className="bg-surface border border-line rounded-2xl p-8">
            <SignupForm />
          </div>
          <p className="mt-6 text-center text-sm text-ink-muted">
            Already have an account?{" "}
            <Link href="/login" className="text-flash hover:underline">
              Login
            </Link>
          </p>
        </div>
      </div>
    </Layout>
  );
}
