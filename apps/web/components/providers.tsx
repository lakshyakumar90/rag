"use client";

import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { usePathname } from "next/navigation";
import { AuthProvider } from "../lib/auth/auth-provider";
import { TooltipProvider } from "./ui/tooltip";

export function Providers({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const publicDocs = pathname === "/docs" || pathname?.startsWith("/docs/") || pathname === "/floorplan";
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 30_000 },
        },
      }),
  );

  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider delayDuration={200}>
          {publicDocs ? children : <AuthProvider>{children}</AuthProvider>}
        </TooltipProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
