"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AuthGuard } from "../../components/auth-guard";
import { ThemeToggle } from "../../components/theme-toggle";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { api } from "../../lib/api/client";
import { useAuth } from "../../lib/auth/auth-provider";

function Dashboard() {
  const { user, logout } = useAuth();
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
    <main className="mx-auto max-w-3xl p-6">
      <header className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Workspaces</h1>
          <p className="text-sm text-muted-foreground">{user?.email}</p>
        </div>
        <div className="flex gap-2">
          <ThemeToggle />
          <Button variant="outline" onClick={() => logout()}>Sign out</Button>
        </div>
      </header>

      <Card className="mb-6">
        <CardHeader><CardTitle>New workspace</CardTitle></CardHeader>
        <CardContent>
          <form
            className="flex flex-col gap-3 sm:flex-row"
            onSubmit={(event) => {
              event.preventDefault();
              create.mutate();
            }}
          >
            <Input placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} required />
            <Input placeholder="slug" value={slug} onChange={(e) => setSlug(e.target.value)} required />
            <Button type="submit" disabled={create.isPending}>Create</Button>
          </form>
          {create.isError ? <p className="mt-2 text-sm text-destructive">Could not create workspace.</p> : null}
        </CardContent>
      </Card>

      {isLoading ? <p className="text-muted-foreground">Loading workspaces…</p> : null}
      <div className="flex flex-col gap-3">
        {workspaces?.map((workspace) => (
          <Card key={workspace.id}>
            <CardHeader>
              <CardTitle>{workspace.name}</CardTitle>
              <p className="text-sm text-muted-foreground">/{workspace.slug}</p>
            </CardHeader>
          </Card>
        ))}
      </div>
    </main>
  );
}

export default function DashboardPage() {
  return (
    <AuthGuard>
      <Dashboard />
    </AuthGuard>
  );
}
