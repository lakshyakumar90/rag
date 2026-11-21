"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Command } from "cmdk";
import {
  BarChart3,
  ChevronDown,
  FileText,
  LayoutGrid,
  MessageSquare,
  Moon,
  Search,
  Settings2,
  Sun,
  Users,
} from "lucide-react";
import { useTheme } from "next-themes";
import { api, type Workspace } from "../lib/api/client";
import { useAuth } from "../lib/auth/auth-provider";
import { cn } from "../lib/utils";
import { Button } from "./ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from "./ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./ui/select";

const NAV = [
  { href: "documents", label: "Documents", icon: FileText },
  { href: "chat", label: "Chat", icon: MessageSquare },
  { href: "members", label: "Members", icon: Users },
  { href: "usage", label: "Usage", icon: BarChart3 },
  { href: "settings", label: "Settings", icon: Settings2 },
] as const;

function WorkspaceSelect({ workspaceId }: { workspaceId: string }) {
  const router = useRouter();
  const { data } = useQuery({ queryKey: ["workspaces"], queryFn: api.listWorkspaces });
  return (
    <Select
      value={workspaceId}
      onValueChange={(value) => router.push(`/workspaces/${value}/documents`)}
    >
      <SelectTrigger className="h-8 min-w-0 w-full border-transparent bg-transparent px-2 text-[13px] hover:bg-muted">
        <SelectValue placeholder="Workspace" />
      </SelectTrigger>
      <SelectContent>
        {data?.map((workspace: Workspace) => (
          <SelectItem key={workspace.id} value={workspace.id}>
            {workspace.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function UserMenu() {
  const { user, logout } = useAuth();
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button className="flex w-full items-center gap-2 rounded-[8px] px-2 py-2 text-left text-[13px] hover:bg-muted">
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-foreground text-[10px] font-semibold text-background">
            {(user?.email ?? "?").slice(0, 1).toUpperCase()}
          </span>
          <span className="min-w-0 flex-1 truncate">{user?.email ?? "Account"}</span>
          <ChevronDown size={13} className="text-muted-foreground" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuItem onSelect={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}>
          {mounted && resolvedTheme === "dark" ? <Sun size={14} /> : <Moon size={14} />}
          {mounted && resolvedTheme === "dark" ? "Light theme" : "Dark theme"}
        </DropdownMenuItem>
        <DropdownMenuSeparator className="my-1 h-px bg-border" />
        <DropdownMenuItem data-destructive onSelect={() => void logout()}>
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function CommandPalette({
  workspaceId,
  trigger,
}: {
  workspaceId: string;
  trigger: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const router = useRouter();

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((value) => !value);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="top-[18%] p-0">
        <DialogTitle className="sr-only">Command menu</DialogTitle>
        <DialogDescription className="sr-only">Navigate the workspace</DialogDescription>
        <Command className="rounded-[10px]" loop>
          <div className="flex items-center gap-2 border-b border-border px-4">
            <Search size={15} className="text-muted-foreground" />
            <Command.Input
              autoFocus
              placeholder="Go to…"
              className="h-12 flex-1 bg-transparent text-[13px] outline-none placeholder:text-muted-foreground"
            />
          </div>
          <Command.List className="max-h-72 overflow-y-auto p-2">
            <Command.Empty className="px-3 py-6 text-center text-[13px] text-muted-foreground">
              No results
            </Command.Empty>
            <Command.Group>
              {NAV.map((item) => (
                <Command.Item
                  key={item.href}
                  value={item.label}
                  onSelect={() => {
                    router.push(`/workspaces/${workspaceId}/${item.href}`);
                    setOpen(false);
                  }}
                  className="flex cursor-default items-center gap-2 rounded-[6px] px-3 py-2 text-[13px] data-[selected=true]:bg-muted"
                >
                  <item.icon size={15} className="text-muted-foreground" />
                  {item.label}
                </Command.Item>
              ))}
              <Command.Item
                value="Dashboard"
                onSelect={() => {
                  router.push("/dashboard");
                  setOpen(false);
                }}
                className="flex cursor-default items-center gap-2 rounded-[6px] px-3 py-2 text-[13px] data-[selected=true]:bg-muted"
              >
                <LayoutGrid size={15} className="text-muted-foreground" />
                Dashboard
              </Command.Item>
            </Command.Group>
          </Command.List>
        </Command>
      </DialogContent>
    </Dialog>
  );
}

export function AppShell({
  workspaceId,
  title,
  description,
  children,
}: {
  workspaceId: string;
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  const params = useParams<{ workspaceId: string }>();
  const pathname = usePathname();
  const active = params.workspaceId;
  const current = workspaceId || active;
  const isActive = (href: string) => pathname.startsWith(href);

  return (
    <div className="min-h-dvh">
      {/* Desktop rail */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[220px] flex-col border-r border-border bg-surface md:flex">
        <div className="flex h-14 items-center gap-2 border-b border-border px-4">
          <span className="text-[13px] font-semibold tracking-[-0.02em]">RAG</span>
          <span className="ml-auto text-[10px] text-muted-foreground">workspace</span>
        </div>
        <div className="px-2 py-3">
          <WorkspaceSelect workspaceId={current} />
        </div>
        <nav className="flex flex-col gap-0.5 px-2">
          {NAV.map((item) => {
            const href = `/workspaces/${current}/${item.href}`;
            const active = isActive(href);
            return (
              <Link
                key={item.href}
                href={href}
                className={cn(
                  "flex h-9 items-center gap-2.5 rounded-[8px] px-3 text-[13px] text-muted-foreground hover:bg-muted hover:text-foreground",
                  active && "bg-muted font-medium text-foreground",
                )}
              >
                <item.icon size={15} />
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="mt-auto border-t border-border p-2">
          <UserMenu />
        </div>
      </aside>

      {/* Mobile bar */}
      <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-border bg-background/95 px-4 backdrop-blur md:hidden">
        <span className="text-[13px] font-semibold">RAG</span>
        <div className="ml-auto w-40">
          <WorkspaceSelect workspaceId={current} />
        </div>
        <CommandPalette
          workspaceId={current}
          trigger={
            <Button variant="ghost" size="icon" aria-label="Open command menu">
              <Search size={16} />
            </Button>
          }
        />
      </header>

      <main className="px-4 pb-24 pt-6 md:ml-[220px] md:px-8 md:pb-10 md:pt-8">
        <div className="mb-7 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-[22px] font-semibold leading-tight tracking-[-0.025em] md:text-[26px]">
              {title}
            </h1>
            {description ? (
              <p className="mt-1 text-[13px] text-muted-foreground">{description}</p>
            ) : null}
          </div>
          <CommandPalette
            workspaceId={current}
            trigger={
              <Button variant="outline" size="sm" className="hidden md:inline-flex">
                <Search size={13} /> Search
                <kbd className="ml-1 rounded border border-border px-1 font-mono text-[10px]">⌘K</kbd>
              </Button>
            }
          />
        </div>
        {children}
      </main>

      {/* Mobile bottom navigation */}
      <nav className="fixed inset-x-0 bottom-0 z-30 flex h-16 items-stretch border-t border-border bg-surface md:hidden">
        {NAV.map((item) => {
          const href = `/workspaces/${current}/${item.href}`;
          const active = isActive(href);
          return (
            <Link
              key={item.href}
              href={href}
              className={cn(
                "flex flex-1 flex-col items-center justify-center gap-1 text-[10px] text-muted-foreground",
                active && "text-foreground",
              )}
            >
              <item.icon size={17} strokeWidth={active ? 2.2 : 1.7} />
              {item.label}
            </Link>
          );
        })}
      </nav>

    </div>
  );
}
