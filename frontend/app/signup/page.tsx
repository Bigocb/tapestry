"use client";

import Link from "next/link";
import { Layout } from "@/components/Layout";
import { SignupForm } from "@/components/AuthForm";

export default function SignupPage() {
  return (
    <Layout>
      <div className="max-w-md mx-auto mt-12">
        <SignupForm />
        <p className="mt-4 text-center text-sm">
          Already have an account?{" "}
          <Link href="/login" className="text-indigo-600 hover:underline">
            Login
          </Link>
        </p>
      </div>
    </Layout>
  );
}
