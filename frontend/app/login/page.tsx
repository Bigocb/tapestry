"use client";

import Link from "next/link";
import { Layout } from "@/components/Layout";
import { LoginForm } from "@/components/AuthForm";

export default function LoginPage() {
  return (
    <Layout>
      <div className="max-w-md mx-auto mt-12">
        <LoginForm />
        <p className="mt-4 text-center text-sm">
          Don&apos;t have an account?{" "}
          <Link href="/signup" className="text-indigo-600 hover:underline">
            Sign up
          </Link>
        </p>
      </div>
    </Layout>
  );
}
