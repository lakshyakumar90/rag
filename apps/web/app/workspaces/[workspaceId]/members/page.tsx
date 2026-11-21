"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, MoreHorizontal, UserMinus } from "lucide-react";
import { toast } from "sonner";
import { Button } from "../../../../components/ui/button";
import { Input } from "../../../../components/ui/input";
import { Badge } from "../../../../components/ui/badge";
import { RowSkeleton } from "../../../../components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../../../../components/ui/select";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "../../../../components/ui/dropdown-menu";
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
    onError: () => toast.error("Could not create the invitation"),
  });
  const changeRole = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: string }) =>
      api.changeRole(workspaceId, userId, role),
    onSuccess: () => {
      toast.success("Role updated");
      invalidate();
    },
    onError: () => toast.error("Could not change the role"),
  });
  const remove = useMutation({
    mutationFn: (userId: string) => api.removeMember(workspaceId, userId),
    onSuccess: () => {
      toast.success("Member removed");
      invalidate();
    },
    onError: () => toast.error("Could not remove the member"),
  });

  return (
    <div className="flex flex-col gap-8">
      <section>
        <h2 className="text-[14px] font-semibold">Invite a teammate</h2>
        <p className="mt-1 text-[12px] text-muted-foreground">
          Invitations are links you can share; no mail server is required.
        </p>
        <form
          className="mt-4 flex flex-col gap-2 sm:flex-row"
          onSubmit={(event) => {
            event.preventDefault();
            invite.mutate();
          }}
        >
          <Input
            type="email"
            aria-label="Invitee email"
            placeholder="teammate@company.com"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
          <Select value={role} onValueChange={(value) => setRole(value as "admin" | "member")}>
            <SelectTrigger aria-label="Role">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="member">member</SelectItem>
              <SelectItem value="admin">admin</SelectItem>
            </SelectContent>
          </Select>
          <Button type="submit" disabled={invite.isPending}>
            Create invite
          </Button>
        </form>
        {inviteUrl ? (
          <div className="result-in mt-4 flex flex-wrap items-center gap-2 rounded-[8px] border border-border bg-muted px-3 py-2">
            <code className="min-w-0 flex-1 break-all font-mono text-[11px]">{inviteUrl}</code>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                void navigator.clipboard.writeText(inviteUrl);
                toast.success("Link copied");
              }}
            >
              <Copy size={13} /> Copy
            </Button>
          </div>
        ) : null}
        {invitations.data?.length ? (
          <div className="mt-5">
            <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">
              Pending
            </p>
            {invitations.data.map((item) => (
              <div
                key={item.id}
                className="flex items-center gap-3 border-b border-border px-2 py-2 text-[12px]"
              >
                <span className="flex-1 truncate">{item.email}</span>
                <Badge tone="neutral">{item.status}</Badge>
              </div>
            ))}
          </div>
        ) : null}
      </section>

      <section>
        <div className="flex items-center justify-between border-b border-border pb-2">
          <h2 className="text-[14px] font-semibold">Members</h2>
          <span data-numeric className="text-[11px] text-muted-foreground">
            {members?.length ?? 0}
          </span>
        </div>
        {isLoading ? <RowSkeleton lines={1} /> : null}
        {!isLoading && !members?.length ? (
          <p className="py-10 text-[13px] text-muted-foreground">No members yet.</p>
        ) : null}
        {members?.map((member) => (
          <div
            key={member.id}
            className="flex flex-wrap items-center gap-3 border-b border-border px-2 py-3"
          >
            <div className="min-w-0 flex-1">
              <p className="truncate text-[13px] font-medium">{member.email}</p>
              <p className="text-[11px] text-muted-foreground">{member.full_name ?? ""}</p>
            </div>
            <Select
              value={member.role}
              onValueChange={(value) =>
                changeRole.mutate({ userId: member.user_id, role: value })
              }
            >
              <SelectTrigger className="h-8 w-28" aria-label={`Role for ${member.email}`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="owner">owner</SelectItem>
                <SelectItem value="admin">admin</SelectItem>
                <SelectItem value="member">member</SelectItem>
              </SelectContent>
            </Select>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" aria-label={`Actions for ${member.email}`}>
                  <MoreHorizontal size={16} />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem
                  data-destructive
                  onSelect={() => remove.mutate(member.user_id)}
                >
                  <UserMinus size={14} /> Remove member
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        ))}
      </section>
    </div>
  );
}
