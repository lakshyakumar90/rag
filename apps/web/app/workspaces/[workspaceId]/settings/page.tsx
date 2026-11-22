"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, KeyRound, Loader2, Trash2, XCircle } from "lucide-react";
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
import { api, type AIProviderOption } from "../../../../lib/api/client";
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
  const [defaultProvider, setDefaultProvider] = useState("");
  const [defaultModel, setDefaultModel] = useState("");

  const configs = useQuery({ queryKey: ["provider-configs"], queryFn: api.providerConfigs });
  const cli = useQuery({ queryKey: ["cli-status"], queryFn: api.cliStatus });
  const ai = useQuery({ queryKey: ["ai-providers"], queryFn: api.aiProviders });

  useEffect(() => {
    const saved = ai.data?.defaults;
    if (saved) {
      setDefaultProvider(saved.provider);
      setDefaultModel(saved.model ?? "");
    }
  }, [ai.data?.defaults]);

  const saveDefaults = useMutation({
    mutationFn: () => api.saveAIDefaults(defaultProvider, defaultModel.trim() || null),
    onSuccess: () => {
      toast.success("Default provider and model saved");
      void queryClient.invalidateQueries({ queryKey: ["ai-providers"] });
    },
    onError: () => toast.error("Could not save the defaults"),
  });

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
        <TabsTrigger value="embeddings">Embeddings</TabsTrigger>
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
        <section className="max-w-3xl">
          <h2 className="text-[14px] font-semibold">Defaults for new chats</h2>
          <p className="mt-1 text-[12px] text-muted-foreground">
            New conversations start with these settings. You can still override them
            inside the Chat composer.
          </p>
          {ai.isLoading ? <RowSkeleton lines={1} /> : null}
          <div className="mt-4 flex flex-col gap-2 sm:flex-row">
            <Select value={defaultProvider} onValueChange={setDefaultProvider}>
              <SelectTrigger aria-label="Default provider" className="sm:w-56">
                <SelectValue placeholder="Provider" />
              </SelectTrigger>
              <SelectContent>
                {(ai.data?.options ?? []).map((option) => (
                  <SelectItem key={option.id} value={option.id}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              aria-label="Default model"
              list="default-model-options"
              placeholder="Model (optional)"
              value={defaultModel}
              maxLength={160}
              onChange={(event) => setDefaultModel(event.target.value)}
            />
            <datalist id="default-model-options">
              {(ai.data?.options ?? [])
                .find((option) => option.id === defaultProvider)?.default_model
                ? [
                    ai.data?.options.find((option) => option.id === defaultProvider)
                      ?.default_model ?? "",
                  ]
                : []}
            </datalist>
            <Button
              disabled={!defaultProvider || saveDefaults.isPending}
              onClick={() => saveDefaults.mutate()}
            >
              Save defaults
            </Button>
          </div>

          <div className="mt-10 border-t border-border pt-6">
            <h2 className="text-[14px] font-semibold">Test a connection</h2>
            <p className="mt-1 text-[12px] text-muted-foreground">
              Each test sends a one-token request with the selected model. Keys are
              never returned to the browser or written to logs.
            </p>
            <div className="mt-4 border-t border-border">
              {(ai.data?.options ?? []).map((option) => (
                <ProviderTestRow key={option.id} option={option} />
              ))}
              {!ai.isLoading && !ai.data?.options.length ? (
                <p className="py-8 text-[13px] text-muted-foreground">
                  No providers available.
                </p>
              ) : null}
            </div>
          </div>

          <div className="mt-10 border-t border-border pt-6">
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
                onValueChange={(value) =>
                  setProviderType(value as (typeof PROVIDER_TYPES)[number])
                }
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
            <div className="mt-6">
              {configs.data?.map((config) => (
                <div
                  key={config.id}
                  className="flex flex-wrap items-center gap-3 border-b border-border px-2 py-3 text-[12px]"
                >
                  <span className="font-medium">{config.provider_type}</span>
                  <span className="font-mono text-[11px] text-muted-foreground">
                    {config.model ?? "default"} · ••••{config.key_last4}
                  </span>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Delete ${config.provider_type} key`}
                    className="ml-auto"
                    onClick={() => deleteConfig.mutate(config.id)}
                  >
                    <Trash2 size={14} className="text-destructive" />
                  </Button>
                </div>
              ))}
            </div>
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

      <TabsContent value="embeddings">
        <EmbeddingProfilesPanel workspaceId={workspaceId} />
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

function EmbeddingProfilesPanel({ workspaceId }: { workspaceId: string }) {
  const queryClient = useQueryClient();
  const profiles = useQuery({
    queryKey: ["embedding-profiles"],
    queryFn: api.embeddingProfiles,
  });
  const [name, setName] = useState("");
  const [provider, setProvider] = useState("ollama");
  const [model, setModel] = useState("");
  const [dimension, setDimension] = useState("768");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["embedding-profiles"] });

  const create = useMutation({
    mutationFn: () =>
      api.createEmbeddingProfile({
        name: name.trim(),
        provider,
        model: model.trim(),
        dimension: Number(dimension),
        distance: "Cosine",
        version: 1,
        base_url: baseUrl.trim() || undefined,
        api_key: apiKey || undefined,
      }),
    onSuccess: () => {
      setApiKey("");
      toast.success("Profile created — validate it before switching");
      invalidate();
    },
    onError: () => toast.error("Could not create the profile"),
  });
  const validate = useMutation({
    mutationFn: (profileName: string) =>
      api.validateEmbeddingProfile(profileName),
    onSuccess: (result) => {
      toast[result.ok ? "success" : "error"](result.detail);
      invalidate();
    },
  });
  const switchProfile = useMutation({
    mutationFn: (profileName: string) =>
      api.switchWorkspaceProfile(workspaceId, profileName),
    onSuccess: () => toast.success("Replacement index is being built"),
    onError: () => toast.error("Could not start the profile switch"),
  });

  return (
    <section className="max-w-3xl">
      <h2 className="text-[14px] font-semibold">Embedding profiles</h2>
      <p className="mt-1 text-[12px] text-muted-foreground">
        Incompatible profiles use separate vector collections. A workspace switch
        builds the replacement index first, then flips once it is ready.
      </p>
      <div className="mt-4 border-t border-border">
        {(profiles.data ?? []).map((profile) => (
          <div
            key={profile.id}
            className="flex flex-wrap items-center gap-2 border-b border-border px-2 py-3 text-[12px]"
          >
            <span className="font-medium">{profile.name}</span>
            <span className="font-mono text-[10px] text-muted-foreground">
              {profile.provider} · {profile.model} · {profile.dimension}d
            </span>
            <Badge tone={profile.enabled ? "accent" : "neutral"}>
              {profile.enabled ? "validated" : "unvalidated"}
            </Badge>
            <div className="ml-auto flex gap-1">
              {!profile.enabled ? (
                <Button size="sm" variant="outline" onClick={() => validate.mutate(profile.name)}>
                  Validate
                </Button>
              ) : (
                <Button size="sm" variant="outline" onClick={() => switchProfile.mutate(profile.name)}>
                  Use in this workspace
                </Button>
              )}
            </div>
          </div>
        ))}
      </div>
      <form
        className="mt-6 grid gap-2 sm:grid-cols-2"
        onSubmit={(event) => {
          event.preventDefault();
          create.mutate();
        }}
      >
        <Input aria-label="Profile name" placeholder="multilingual-v2" value={name} onChange={(e) => setName(e.target.value)} required />
        <Input aria-label="Embedding model" placeholder="Model ID" value={model} onChange={(e) => setModel(e.target.value)} required />
        <Select value={provider} onValueChange={setProvider}>
          <SelectTrigger aria-label="Embedding provider">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="ollama">Ollama</SelectItem>
            <SelectItem value="openai-compatible">OpenAI-compatible</SelectItem>
          </SelectContent>
        </Select>
        <Input aria-label="Dimension" type="number" min={1} value={dimension} onChange={(e) => setDimension(e.target.value)} required />
        <Input aria-label="Embedding base URL" placeholder="Base URL (optional)" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
        <Input aria-label="Embedding API key" type="password" placeholder="API key (optional)" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
        <Button type="submit" disabled={create.isPending}>Add profile</Button>
      </form>
    </section>
  );
}

function ProviderTestRow({ option }: { option: AIProviderOption }) {
  const [model, setModel] = useState(option.default_model ?? "");
  const models = useQuery({
    queryKey: ["ai-models", option.id],
    queryFn: () => api.aiModels(option.id, option.config_id ?? undefined),
    enabled: option.discovery,
    staleTime: 300_000,
    retry: false,
  });
  const test = useMutation({
    mutationFn: () =>
      api.testAIProvider(option.id, model.trim() || null, option.config_id ?? null),
  });

  return (
    <div className="grid gap-2 border-b border-border px-2 py-3 text-[12px] sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-center">
      <div className="min-w-0">
        <p className="truncate font-medium">{option.label}</p>
        <p className="text-[10px] text-muted-foreground">
          {option.available ? "available" : "not installed on this host"}
        </p>
      </div>
      <div className="flex min-w-0 items-center gap-2">
        <Input
          aria-label={`Model for ${option.label}`}
          list={`models-${option.id}`}
          placeholder={option.manual_model ? "Model ID (type or choose)" : "Model"}
          value={model}
          maxLength={160}
          onChange={(event) => setModel(event.target.value)}
        />
        <datalist id={`models-${option.id}`}>
          {(models.data?.models ?? []).map((id) => (
            <option key={id} value={id} />
          ))}
        </datalist>
      </div>
      <div className="flex flex-col items-start gap-1 sm:items-end">
        <Button
          variant="outline"
          size="sm"
          disabled={!option.available || test.isPending}
          onClick={() => test.mutate()}
        >
          {test.isPending ? <Loader2 size={13} className="animate-spin" /> : null}
          {test.isPending ? "Testing…" : "Test connection"}
        </Button>
        {test.isSuccess ? (
          <span role="status" className="text-[11px] text-muted-foreground">
            <CheckCircle2 size={12} className="mr-1 inline" />
            {test.data.detail}
          </span>
        ) : null}
        {test.isError || (test.isSuccess && !test.data.ok) ? (
          <span role="alert" className="text-[11px] text-foreground">
            <XCircle size={12} className="mr-1 inline" />
            {test.isSuccess
              ? test.data.detail
              : test.error instanceof Error
                ? test.error.message
                : "Connection test failed"}
          </span>
        ) : null}
      </div>
    </div>
  );
}
