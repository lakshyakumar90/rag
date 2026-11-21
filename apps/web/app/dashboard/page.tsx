"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, LogOut, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { AuthGuard } from "../../components/auth-guard";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { RowSkeleton } from "../../components/ui/skeleton";
import { api } from "../../lib/api/client";
import { useAuth } from "../../lib/auth/auth-provider";

function Dashboard() {
  const { user, logout } = useAuth();
  const { resolvedTheme, setTheme } = useTheme();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const { data: workspaces, isLoading } = useQuery({
    queryKey: ["workspaces"],
    queryFn: api.listWorkspaces,
  });
  const create = useMutation({
    mutationFn: () => api.createWorkspace({ name, slug }),
    onSuccess: () => {
      setName("");
      setSlug("");
      queryClient.invalidateQueries({ queryKey: ["workspaces"] });
    },
  });

  return (
    <div className="min-h-dvh">
      <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-border bg-background/95 px-5 backdrop-blur">
        <span className="text-[13px] font-semibold tracking-[-0.02em]">RAG</span>
        <span className="text-[12px] text-muted-foreground">/ workspaces</span>
        <div className="ml-auto flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            aria-label="Toggle theme"
            onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
          >
            {resolvedTheme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => void logout()}>
            <LogOut size={14} /> <span className="hidden sm:inline">Sign out</span>
          </Button>
        </div>
      </header>

      <main className="mx-auto max-w-[860px] px-5 py-10 md:py-14">
        <h1 className="text-[26px] font-semibold tracking-[-0.03em] md:text-[30px]">
          Your workspaces
        </h1>
        <p className="mt-1.5 text-[13px] text-muted-foreground">
          {user?.email ?? ""} · documents stay inside their workspace.
        </p>

        <form
          className="mt-8 flex flex-col gap-2 border-b border-border pb-7 sm:flex-row"
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate();
          }}
        >
          <Input
            aria-label="Workspace name"
            placeholder="Workspace name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
          />
          <Input
            aria-label="Workspace slug"
            placeholder="slug"
            value={slug}
            onChange={(event) => setSlug(event.target.value)}
            required
            className="sm:max-w-[180px] font-mono text-[12px]"
          />
          <Button type="submit" disabled={create.isPending}>
            Create workspace
          </Button>
        </form>

        <div className="mt-4">
          {isLoading ? <RowSkeleton /> : null}
          {!isLoading && !workspaces?.length ? (
            <div className="flex flex-col items-start gap-3 py-16">
              <p className="text-[14px]">No workspaces yet.</p>
              <p className="text-[13px] text-muted-foreground">
                Create one above, then upload your first document.
              </p>
            </div>
          ) : null}
          {workspaces?.map((workspace) => (
            <Link
              key={workspace.id}
              href={`/workspaces/${workspace.id}/documents`}
              className="group flex items-center gap-4 border-b border-border px-2 py-4 hover:bg-muted"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-[14px] font-medium">{workspace.name}</p>
                <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">
                  /{workspace.slug}
                </p>
              </div>
              <span className="text-[11px] text-muted-foreground">Open</span>
              <ArrowUpRight
                size={15}
                className="text-muted-foreground transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-foreground"
              />
            </Link>
          ))}
        </div>
      </main>
    </div>
  );
}

export default function DashboardPage() {
  return (
    <AuthGuard>
      <Dashboard />
    </AuthGuard>
  );
}
