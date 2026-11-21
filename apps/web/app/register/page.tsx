"use client";

import { useState } from "react";
import Link from "next/link";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { ThemeToggle } from "../../components/theme-toggle";
import { useAuth } from "../../lib/auth/auth-provider";

export default function RegisterPage() {
  const { register } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setPending(true);
    try {
      await register(email, password, fullName || undefined);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Registration failed");
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="flex min-h-dvh flex-col">
      <header className="flex h-14 items-center justify-between border-b border-border px-6">
        <span className="text-[13px] font-semibold tracking-[-0.02em]">RAG</span>
        <ThemeToggle />
      </header>
      <div className="flex flex-1 items-center justify-center px-5 py-12">
        <div className="w-full max-w-[380px]">
          <h1 className="text-[24px] font-semibold tracking-[-0.03em]">Create your account</h1>
          <p className="mt-1.5 text-[13px] text-muted-foreground">
            Uppercase, lowercase, a digit and a symbol — at least eight characters.
          </p>
          <form className="mt-8 flex flex-col gap-3" onSubmit={submit}>
            <label className="flex flex-col gap-1.5 text-[12px] font-medium">
              Full name <span className="font-normal text-muted-foreground">(optional)</span>
              <Input
                placeholder="Ada Lovelace"
                autoComplete="name"
                value={fullName}
                onChange={(event) => setFullName(event.target.value)}
              />
            </label>
            <label className="flex flex-col gap-1.5 text-[12px] font-medium">
              Email
              <Input
                type="email"
                autoComplete="email"
                placeholder="you@company.com"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
            </label>
            <label className="flex flex-col gap-1.5 text-[12px] font-medium">
              Password
              <Input
                type="password"
                autoComplete="new-password"
                placeholder="••••••••"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </label>
            {error ? (
              <p role="alert" className="mt-1 text-[12px] text-destructive">
                {error}
              </p>
            ) : null}
            <Button type="submit" size="lg" className="mt-3 w-full" disabled={pending}>
              {pending ? "Creating…" : "Create account"}
            </Button>
          </form>
          <p className="mt-6 text-[13px] text-muted-foreground">
            Already have an account?{" "}
            <Link href="/login" className="text-foreground underline underline-offset-4">
              Sign in
            </Link>
          </p>
        </div>
      </div>
    </main>
  );
}
