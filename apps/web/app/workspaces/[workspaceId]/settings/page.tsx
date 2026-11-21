"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, KeyRound, Trash2, XCircle } from "lucide-react";
import { toast } from "sonner";
import { Button } from "../../../../components/ui/button";
import { Input } from "../../../../components/ui/input";
import { Badge } from "../../../../components/ui/badge";
import { RowSkeleton } from "../../../../components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../../../components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../../../../components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "../../../../components/ui/dialog";
import { api } from "../../../../lib/api/client";
import { useAuth } from "../../../../lib/auth/auth-provider";

const PROVIDER_TYPES = ["openai", "openai-compatible", "anthropic", "ollama"] as const;

export default function SettingsPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const router = useRouter();
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [fullName, setFullName] = useState(user?.full_name ?? "");
  const [providerType, setProviderType] = useState<(typeof PROVIDER_TYPES)[number]>("openai");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [testResults, setTestResults] = useState<Record<string, boolean>>({});

  const configs = useQuery({ queryKey: ["provider-configs"], queryFn: api.providerConfigs });
  const cli = useQuery({ queryKey: ["cli-status"], queryFn: api.cliStatus });

  const saveProfile = useMutation({
    mutationFn: () => api.updateMe(fullName || null),
    onSuccess: () => {
      toast.success("Profile saved");
      queryClient.invalidateQueries({ queryKey: ["me"] });
    },
    onError: () => toast.error("Could not save the profile"),
  });
  const addConfig = useMutation({
    mutationFn: () =>
      api.addProviderConfig({
        provider_type: providerType,
        base_url: baseUrl || null,
        model: model || null,
        api_key: apiKey,
      }),
    onSuccess: () => {
      setApiKey("");
      toast.success("Provider saved");
      queryClient.invalidateQueries({ queryKey: ["provider-configs"] });
    },
    onError: () => toast.error("Could not save the provider"),
  });
  const testConfig = useMutation({
    mutationFn: (id: string) => api.testProviderConfig(id),
    onSuccess: (result, id) => {
      setTestResults((current) => ({ ...current, [id]: result.ok }));
      toast[result.ok ? "success" : "error"](
        result.ok ? "Connection successful" : "Connection failed",
      );
    },
    onError: (_error, id) => {
      setTestResults((current) => ({ ...current, [id]: false }));
      toast.error("Connection test failed");
    },
  });
  const deleteConfig = useMutation({
    mutationFn: (id: string) => api.deleteProviderConfig(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["provider-configs"] }),
  });
  const exportWorkspace = useMutation({
    mutationFn: () => api.exportWorkspace(workspaceId),
    onSuccess: (data) => {
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
      );
      const link = document.createElement("a");
      link.href = url;
      link.download = `workspace-${workspaceId}.json`;
      link.click();
      URL.revokeObjectURL(url);
      toast.success("Export downloaded");
    },
    onError: () => toast.error("Could not export the workspace"),
  });
  const deleteAccount = useMutation({
    mutationFn: () => api.deleteAccount(),
    onSuccess: async () => {
      setDeleteOpen(false);
      queryClient.clear();
      router.replace("/register");
      toast.success("Account deleted");
    },
    onError: () => toast.error("Could not delete the account"),
  });

  return (
    <Tabs defaultValue="profile">
      <TabsList className="mb-6">
        <TabsTrigger value="profile">Profile</TabsTrigger>
        <TabsTrigger value="providers">AI providers</TabsTrigger>
        <TabsTrigger value="cli">Local CLI</TabsTrigger>
        <TabsTrigger value="data">Data</TabsTrigger>
      </TabsList>

      <TabsContent value="profile">
        <section className="max-w-xl">
          <h2 className="text-[14px] font-semibold">Your profile</h2>
          <p className="mt-1 text-[12px] text-muted-foreground">{user?.email}</p>
          <form
            className="mt-5 flex flex-col gap-2 sm:flex-row"
            onSubmit={(event) => {
              event.preventDefault();
              saveProfile.mutate();
            }}
          >
            <Input
              aria-label="Full name"
              placeholder="Full name"
              value={fullName}
              onChange={(event) => setFullName(event.target.value)}
            />
            <Button type="submit">Save</Button>
          </form>
        </section>
      </TabsContent>

      <TabsContent value="providers">
        <section>
          <div className="flex items-center gap-2">
            <KeyRound size={15} className="text-muted-foreground" />
            <h2 className="text-[14px] font-semibold">Bring your own key</h2>
          </div>
          <p className="mt-1 text-[12px] text-muted-foreground">
            Keys are encrypted at rest and never shown again after saving.
          </p>
          <form
            className="mt-5 flex flex-col gap-2 lg:flex-row"
            onSubmit={(event) => {
              event.preventDefault();
              addConfig.mutate();
            }}
          >
            <Select
              value={providerType}
              onValueChange={(value) => setProviderType(value as (typeof PROVIDER_TYPES)[number])}
            >
              <SelectTrigger aria-label="Provider type" className="lg:w-48">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PROVIDER_TYPES.map((type) => (
                  <SelectItem key={type} value={type}>
                    {type}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              aria-label="Base URL"
              placeholder="Base URL (optional)"
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
            />
            <Input
              aria-label="Model"
              placeholder="Model (optional)"
              value={model}
              onChange={(event) => setModel(event.target.value)}
            />
            <Input
              aria-label="API key"
              type="password"
              placeholder="API key"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              required
            />
            <Button type="submit">Add</Button>
          </form>

          <div className="mt-6 border-t border-border">
            {configs.isLoading ? <RowSkeleton lines={1} /> : null}
            {!configs.isLoading && !configs.data?.length ? (
              <p className="py-10 text-[13px] text-muted-foreground">
                No provider configured yet. Chat uses the server default until you add one.
              </p>
            ) : null}
            {configs.data?.map((config) => (
              <div
                key={config.id}
                className="flex flex-wrap items-center gap-3 border-b border-border px-2 py-3 text-[12px]"
              >
                <span className="font-medium">{config.provider_type}</span>
                <span className="font-mono text-[11px] text-muted-foreground">
                  {config.model ?? "default"} · ••••{config.key_last4}
                </span>
                {config.id in testResults ? (
                  testResults[config.id] ? (
                    <CheckCircle2 size={14} className="text-foreground" />
                  ) : (
                    <XCircle size={14} className="text-muted-foreground" />
                  )
                ) : null}
                <div className="ml-auto flex items-center gap-1">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={testConfig.isPending}
                    onClick={() => testConfig.mutate(config.id)}
                  >
                    Test
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label="Delete provider"
                    onClick={() => deleteConfig.mutate(config.id)}
                  >
                    <Trash2 size={14} className="text-destructive" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </section>
      </TabsContent>

      <TabsContent value="cli">
        <section className="max-w-xl">
          <h2 className="text-[14px] font-semibold">Local CLI providers</h2>
          <p className="mt-1 text-[12px] leading-relaxed text-muted-foreground">
            Off by default. Enable with <code className="font-mono">ENABLE_CLI_PROVIDERS=true</code>{" "}
            and run the backend on the host — the CLI binaries and logins are not available in Docker.
          </p>
          {cli.isLoading ? <RowSkeleton lines={1} /> : null}
          {cli.data ? (
            <div className="mt-5 flex flex-wrap items-center gap-2">
              <Badge tone="neutral">{cli.data.enabled ? "enabled" : "disabled"}</Badge>
              {cli.data.in_container ? <Badge tone="neutral">in container</Badge> : null}
            </div>
          ) : null}
          <div className="mt-4 border-t border-border">
            {Object.entries(cli.data?.tools ?? {}).map(([name, status]) => (
              <div
                key={name}
                className="flex items-center gap-3 border-b border-border px-2 py-3 text-[12px]"
              >
                <span className="font-mono">{name}</span>
                <span className="ml-auto text-muted-foreground">
                  {status.installed
                    ? status.logged_in
                      ? "installed · logged in"
                      : "installed · not logged in"
                    : "not installed"}
                </span>
              </div>
            ))}
          </div>
        </section>
      </TabsContent>

      <TabsContent value="data">
        <section className="max-w-xl">
          <h2 className="text-[14px] font-semibold">Export</h2>
          <p className="mt-1 text-[12px] leading-relaxed text-muted-foreground">
            Download this workspace&apos;s documents, conversations, messages and
            members as JSON. File contents are not included.
          </p>
          <Button
            className="mt-4"
            variant="outline"
            size="sm"
            disabled={exportWorkspace.isPending}
            onClick={() => exportWorkspace.mutate()}
          >
            <Download size={13} /> Export workspace
          </Button>
        </section>

        <section className="mt-10 border-t border-border pt-6">
          <h2 className="text-[14px] font-semibold text-destructive">Danger zone</h2>
          <p className="mt-1 text-[12px] leading-relaxed text-muted-foreground">
            Permanently delete your account, workspaces, documents and chat history.
            A redacted audit record is kept. This cannot be undone.
          </p>
          <Button
            className="mt-4"
            variant="outline"
            size="sm"
            data-destructive
            onClick={() => setDeleteOpen(true)}
          >
            <Trash2 size={13} /> Delete account
          </Button>
        </section>

        <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
          <DialogContent className="p-5">
            <DialogTitle className="text-[14px] font-semibold">Delete your account?</DialogTitle>
            <DialogDescription className="mt-2 text-[12px] leading-relaxed text-muted-foreground">
              Every workspace you own and all of their data will be removed. This
              action is permanent.
            </DialogDescription>
            <div className="mt-5 flex justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={() => setDeleteOpen(false)}>
                Cancel
              </Button>
              <Button
                variant="outline"
                size="sm"
                data-destructive
                disabled={deleteAccount.isPending}
                onClick={() => deleteAccount.mutate()}
              >
                Delete permanently
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </TabsContent>
    </Tabs>
  );
}
