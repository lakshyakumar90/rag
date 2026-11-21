"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { AuthGuard } from "../../../components/auth-guard";
import { ThemeToggle } from "../../../components/theme-toggle";
import { WorkspacePicker } from "../../../components/workspace-picker";

export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  const params = useParams<{ workspaceId: string }>();
  const workspaceId = params.workspaceId;
  const links = [
    ["documents", "Documents"],
    ["chat", "Chat"],
    ["members", "Members"],
    ["settings", "Settings"],
  ] as const;

  return (
    <AuthGuard>
      <div className="min-h-screen">
        <header className="flex flex-wrap items-center gap-4 border-b border-border px-6 py-3">
          <Link href="/dashboard" className="font-semibold">RAG</Link>
          <WorkspacePicker workspaceId={workspaceId} />
          <nav className="flex flex-1 gap-3 text-sm">
            {links.map(([segment, label]) => (
              <Link
                key={segment}
                href={`/workspaces/${workspaceId}/${segment}`}
                className="text-muted-foreground hover:text-foreground"
              >
                {label}
              </Link>
            ))}
          </nav>
          <ThemeToggle />
        </header>
        <div className="p-6">{children}</div>
      </div>
    </AuthGuard>
  );
}
