"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getAccessToken } from "../lib/auth-client";

export default function Home() {
  const router = useRouter();
  useEffect(() => {
    router.replace(getAccessToken() ? "/dashboard" : "/login");
  }, [router]);
  return <div className="p-8 text-muted-foreground">Loading…</div>;
}
