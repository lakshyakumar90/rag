"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "../../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../../../components/ui/card";
import { Input } from "../../../../components/ui/input";
import { Skeleton } from "../../../../components/ui/skeleton";
import { api } from "../../../../lib/api/client";

export default function MembersPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"admin" | "member">("member");
  const [inviteUrl, setInviteUrl] = useState<string | null>(null);

  const { data: members, isLoading } = useQuery({
    queryKey: ["members", workspaceId],
    queryFn: () => api.members(workspaceId),
  });
  const invitations = useQuery({
    queryKey: ["invitations", workspaceId],
    queryFn: () => api.invitations(workspaceId),
  });
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["members", workspaceId] });
    queryClient.invalidateQueries({ queryKey: ["invitations", workspaceId] });
  };

  const invite = useMutation({
    mutationFn: () => api.invite(workspaceId, email, role),
    onSuccess: (created) => {
      const base = process.env.NEXT_PUBLIC_WEB_URL ?? window.location.origin;
      setInviteUrl(`${base}/invitations/accept?token=${encodeURIComponent(created.token)}`);
      toast.success("Invitation created");
      invalidate();
    },
    onError: () => toast.error("Could not create invitation"),
  });
  const changeRole = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: string }) =>
      api.changeRole(workspaceId, userId, role),
    onSuccess: () => { toast.success("Role updated"); invalidate(); },
    onError: () => toast.error("Could not change role"),
  });
  const remove = useMutation({
    mutationFn: (userId: string) => api.removeMember(workspaceId, userId),
    onSuccess: () => { toast.success("Member removed"); invalidate(); },
    onError: () => toast.error("Could not remove member"),
  });

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader><CardTitle>Invite a member</CardTitle></CardHeader>
        <CardContent>
          <form
            className="flex flex-wrap gap-2"
            onSubmit={(event) => { event.preventDefault(); invite.mutate(); }}
          >
            <Input
              type="email"
              placeholder="Email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
            <select
              className="rounded-md border border-border bg-card px-3 text-sm"
              value={role}
              onChange={(event) => setRole(event.target.value as "admin" | "member")}
            >
              <option value="member">member</option>
              <option value="admin">admin</option>
            </select>
            <Button type="submit" disabled={invite.isPending}>Invite</Button>
          </form>
          {inviteUrl ? (
            <div className="mt-4 rounded bg-muted p-3 text-sm">
              <p className="mb-1 text-muted-foreground">Share this link:</p>
              <code className="break-all">{inviteUrl}</code>
              <Button
                variant="outline"
                size="sm"
                className="ml-2"
                onClick={() => { navigator.clipboard.writeText(inviteUrl); toast.success("Copied"); }}
              >
                Copy
              </Button>
            </div>
          ) : null}
          {invitations.data?.length ? (
            <div className="mt-4 text-sm">
              <p className="mb-1 text-muted-foreground">Pending invitations</p>
              {invitations.data.map((item) => (
                <p key={item.id}>{item.email} — {item.status}</p>
              ))}
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Members</CardTitle></CardHeader>
        <CardContent>
          {isLoading ? <Skeleton className="h-20 w-full" /> : null}
          {!isLoading && !members?.length ? (
            <p className="text-muted-foreground">No members yet.</p>
          ) : null}
          <div className="flex flex-col gap-3">
            {members?.map((member) => (
              <div key={member.id} className="flex flex-wrap items-center gap-3 border-b border-border pb-3">
                <div className="flex-1">
                  <p className="text-sm font-medium">{member.email}</p>
                  <p className="text-xs text-muted-foreground">{member.full_name ?? ""}</p>
                </div>
                <select
                  className="rounded-md border border-border bg-card px-2 py-1 text-sm"
                  value={member.role}
                  onChange={(event) => changeRole.mutate({ userId: member.user_id, role: event.target.value })}
                >
                  <option value="owner">owner</option>
                  <option value="admin">admin</option>
                  <option value="member">member</option>
                </select>
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() => remove.mutate(member.user_id)}
                >
                  Remove
                </Button>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
