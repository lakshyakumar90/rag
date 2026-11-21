"use client";

import { useParams, usePathname } from "next/navigation";
import { AuthGuard } from "../../../components/auth-guard";
import { AppShell } from "../../../components/app-shell";

export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const pathname = usePathname();
  const segment = pathname.split("/").pop() ?? "documents";
  const titles: Record<string, string> = {
    documents: "Documents",
    chat: "Chat",
    members: "Members",
    usage: "Usage",
    settings: "Settings",
  };
  return (
    <AuthGuard>
      <AppShell
        workspaceId={workspaceId}
        fillViewport={segment === "chat"}
        title={titles[segment] ?? "Workspace"}
        description={
          segment === "documents"
            ? "Upload files and watch ingestion finish."
            : segment === "chat"
              ? "Ask questions, verify the sources."
              : undefined
        }
      >
        {children}
      </AppShell>
    </AuthGuard>
  );
}
