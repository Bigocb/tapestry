"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

export default function Home() {
  const { token } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (token === null) return;
    router.push(token ? "/capture" : "/login");
  }, [token, router]);

  return <div className="p-8">Loading...</div>;
}
