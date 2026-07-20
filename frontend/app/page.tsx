"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

export default function Home() {
  const { token, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (isLoading) return;
    router.push(token ? "/capture" : "/login");
  }, [token, isLoading, router]);

  return <div className="p-8">Loading...</div>;
}
