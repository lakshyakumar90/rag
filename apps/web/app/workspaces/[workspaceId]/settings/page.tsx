"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "../../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../../../components/ui/card";
import { Input } from "../../../../components/ui/input";
import { Skeleton } from "../../../../components/ui/skeleton";
import { api } from "../../../../lib/api/client";
import { useAuth } from "../../../../lib/auth/auth-provider";

const PROVIDER_TYPES = ["openai", "openai-compatible", "anthropic", "ollama"] as const;

export default function SettingsPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [fullName, setFullName] = useState(user?.full_name ?? "");
  const [providerType, setProviderType] = useState<(typeof PROVIDER_TYPES)[number]>("openai");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");

  const configs = useQuery({ queryKey: ["provider-configs"], queryFn: api.providerConfigs });
  const cli = useQuery({ queryKey: ["cli-status"], queryFn: api.cliStatus });

  const saveProfile = useMutation({
    mutationFn: () => api.updateMe(fullName || null),
    onSuccess: () => { toast.success("Profile saved"); queryClient.invalidateQueries({ queryKey: ["me"] }); },
    onError: () => toast.error("Could not save profile"),
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
    onError: () => toast.error("Could not save provider"),
  });
  const testConfig = useMutation({
    mutationFn: (id: string) => api.testProviderConfig(id),
    onSuccess: (result) =>
      result.ok ? toast.success("Connection successful") : toast.error("Connection failed"),
    onError: () => toast.error("Connection test failed"),
  });
  const deleteConfig = useMutation({
    mutationFn: (id: string) => api.deleteProviderConfig(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["provider-configs"] }),
  });

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader><CardTitle>Profile</CardTitle></CardHeader>
        <CardContent>
          <form className="flex gap-2" onSubmit={(event) => { event.preventDefault(); saveProfile.mutate(); }}>
            <Input
              value={fullName}
              placeholder="Full name"
              onChange={(event) => setFullName(event.target.value)}
            />
            <Button type="submit">Save</Button>
          </form>
          <p className="mt-2 text-sm text-muted-foreground">{user?.email}</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>AI providers (bring your own key)</CardTitle></CardHeader>
        <CardContent>
          <form
            className="flex flex-wrap gap-2"
            onSubmit={(event) => { event.preventDefault(); addConfig.mutate(); }}
          >
            <select
              className="rounded-md border border-border bg-card px-3 text-sm"
              value={providerType}
              onChange={(event) => setProviderType(event.target.value as (typeof PROVIDER_TYPES)[number])}
            >
              {PROVIDER_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
            </select>
            <Input placeholder="Base URL (optional)" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
            <Input placeholder="Model (optional)" value={model} onChange={(e) => setModel(e.target.value)} />
            <Input type="password" placeholder="API key" value={apiKey} onChange={(e) => setApiKey(e.target.value)} required />
            <Button type="submit">Add provider</Button>
          </form>
          {configs.isLoading ? <Skeleton className="mt-4 h-16 w-full" /> : null}
          <div className="mt-4 flex flex-col gap-2">
            {configs.data?.map((config) => (
              <div key={config.id} className="flex flex-wrap items-center gap-3 rounded border border-border p-3 text-sm">
                <span className="font-medium">{config.provider_type}</span>
                <span className="text-muted-foreground">{config.model ?? "default model"} · ••••{config.key_last4}</span>
                <Button variant="outline" size="sm" onClick={() => testConfig.mutate(config.id)}>Test</Button>
                <Button variant="destructive" size="sm" onClick={() => deleteConfig.mutate(config.id)}>Delete</Button>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Local CLI providers</CardTitle></CardHeader>
        <CardContent>
          {cli.isLoading ? <Skeleton className="h-12 w-full" /> : null}
          {cli.data?.enabled === false ? (
            <p className="text-sm text-muted-foreground">
              Disabled by default. Set ENABLE_CLI_PROVIDERS=true and run the backend on the host.
              {cli.data.in_container ? " The backend is running in a container." : ""}
            </p>
          ) : null}
          <div className="flex flex-col gap-2">
            {Object.entries(cli.data?.tools ?? {}).map(([name, status]) => (
              <div key={name} className="flex justify-between text-sm">
                <span>{name}</span>
                <span className={status.logged_in ? "text-emerald-600" : "text-muted-foreground"}>
                  {status.installed ? (status.logged_in ? "installed · logged in" : "installed · not logged in") : "not installed"}
                </span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
