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
  open,
  onOpenChange,
}: {
  workspaceId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(query.trim()), 200);
    return () => window.clearTimeout(timer);
  }, [query]);

  const results = useQuery({
    queryKey: ["workspace-search", workspaceId, debounced],
    queryFn: () => api.search(workspaceId, debounced),
    enabled: open && debounced.length >= 2,
    staleTime: 30_000,
    retry: false,
  });

  function go(path: string) {
    router.push(path);
    onOpenChange(false);
    setQuery("");
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent side="top" className="p-0">
        <DialogTitle className="sr-only">Workspace search</DialogTitle>
        <DialogDescription className="sr-only">
          Search documents or navigate the workspace
        </DialogDescription>
        <Command className="rounded-[10px]" loop>
          <div className="flex items-center gap-2 border-b border-border pl-4 pr-14">
            <Search size={15} className="text-muted-foreground" />
            <Command.Input
              autoFocus
              value={query}
              onValueChange={setQuery}
              placeholder="Search documents or go to…"
              aria-label="Search workspace documents and pages"
              className="h-12 min-w-0 flex-1 bg-transparent text-[13px] outline-none placeholder:text-muted-foreground"
            />
          </div>
          <Command.List className="max-h-[min(24rem,calc(100dvh-9rem))] overflow-y-auto overscroll-contain p-2">
            <Command.Empty className="px-3 py-6 text-center text-[13px] text-muted-foreground">
              No results
            </Command.Empty>
            <Command.Group heading="Pages">
              {NAV.map((item) => (
                <Command.Item
                  key={item.href}
                  value={`page ${item.label}`}
                  onSelect={() => go(`/workspaces/${workspaceId}/${item.href}`)}
                  className="flex cursor-default items-center gap-2 rounded-[6px] px-3 py-2 text-[13px] data-[selected=true]:bg-muted"
                >
                  <item.icon size={15} className="text-muted-foreground" />
                  {item.label}
                </Command.Item>
              ))}
              <Command.Item
                value="Dashboard"
                onSelect={() => go("/dashboard")}
                className="flex cursor-default items-center gap-2 rounded-[6px] px-3 py-2 text-[13px] data-[selected=true]:bg-muted"
              >
                <LayoutGrid size={15} className="text-muted-foreground" />
                Dashboard
              </Command.Item>
            </Command.Group>
            {debounced.length >= 2 ? (
              <Command.Group heading="Documents">
                {results.isFetching ? (
                  <p className="px-3 py-2 text-[11px] text-muted-foreground">Searching…</p>
                ) : null}
                {(results.data?.items ?? []).map((item) => (
                  <Command.Item
                    key={item.chunk_id}
                    value={`document ${item.filename} ${item.text}`}
                    onSelect={() =>
                      go(
                        `/workspaces/${workspaceId}/chat?q=${encodeURIComponent(debounced)}`,
                      )
                    }
                    className="flex cursor-default flex-col items-start gap-0.5 rounded-[6px] px-3 py-2 text-[13px] data-[selected=true]:bg-muted"
                  >
                    <span className="max-w-full truncate font-medium">{item.filename}</span>
                    <span className="max-w-full truncate text-[11px] text-muted-foreground">
                      {item.text}
                    </span>
                  </Command.Item>
                ))}
              </Command.Group>
            ) : null}
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
  fillViewport = false,
  children,
}: {
  workspaceId: string;
  title: string;
  description?: string;
  fillViewport?: boolean;
  children: React.ReactNode;
}) {
  const params = useParams<{ workspaceId: string }>();
  const pathname = usePathname();
  const active = params.workspaceId;
  const current = workspaceId || active;
  const isActive = (href: string) => pathname.startsWith(href);
  const [commandOpen, setCommandOpen] = useState(false);

  // One panel for both triggers and the keyboard shortcut.
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommandOpen((value) => !value);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

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
        <Button
          variant="ghost"
          size="icon"
          aria-label="Open workspace search"
          onClick={() => setCommandOpen(true)}
        >
          <Search size={16} />
        </Button>
      </header>

      <main className={cn(
        "md:ml-[220px]",
        fillViewport
          ? "flex h-[calc(100dvh-3.5rem)] min-h-0 flex-col pb-[4.25rem] md:h-dvh md:pb-3"
          : "px-4 pb-24 pt-6 md:px-8 md:pb-10 md:pt-8",
      )}>
        <div className={cn("flex shrink-0 items-center justify-between gap-3", fillViewport ? "min-h-14 border-b border-border bg-surface/70 px-4 md:px-6" : "mb-6")}>
          <div>
            <h1 className={cn("font-semibold leading-tight tracking-tight", fillViewport ? "text-lg" : "text-2xl md:text-[26px]")}>
              {title}
            </h1>
            {description ? (
              <p className="mt-1 text-[13px] text-muted-foreground">{description}</p>
            ) : null}
          </div>
          <Button
            variant="outline"
            size="sm"
            className="hidden gap-2 rounded-lg px-3 md:inline-flex"
            aria-label="Open workspace search"
            onClick={() => setCommandOpen(true)}
          >
            <Search size={13} /> Search
            <kbd className="ml-1 rounded border border-border px-1 font-mono text-[10px]">Ctrl / ⌘ K</kbd>
          </Button>
        </div>
        {fillViewport ? <div className="min-h-0 flex-1">{children}</div> : children}
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

      <CommandPalette
        workspaceId={current}
        open={commandOpen}
        onOpenChange={setCommandOpen}
      />
    </div>
  );
}
