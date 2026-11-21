"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { api } from "../lib/api/client";

export function WorkspacePicker({ workspaceId }: { workspaceId: string }) {
  const router = useRouter();
  const { data: workspaces } = useQuery({
    queryKey: ["workspaces"],
    queryFn: api.listWorkspaces,
  });

  return (
    <select
      aria-label="Workspace"
      className="rounded-md border border-border bg-card px-3 py-2 text-sm"
      value={workspaceId}
      onChange={(event) => router.push(`/workspaces/${event.target.value}/documents`)}
    >
      {workspaces?.map((workspace) => (
        <option key={workspace.id} value={workspace.id}>
          {workspace.name}
        </option>
      ))}
    </select>
  );
}
