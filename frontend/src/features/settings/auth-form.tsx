"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/primitives";
import { ME_KEY } from "@/hooks/use-auth";
import { api } from "@/services/api";

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const isRegister = mode === "register";
  const config = useQuery({ queryKey: ["auth-config"], queryFn: api.auth.config, staleTime: 300_000 });
  const [demoPending, setDemoPending] = useState(false);

  async function startDemo() {
    setError(null);
    setDemoPending(true);
    try {
      qc.setQueryData(ME_KEY, await api.auth.demo());
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start the demo");
    } finally {
      setDemoPending(false);
    }
  }

  const passwordHint =
    isRegister && password && (password.length < 10 || !/[a-z]/i.test(password) || !/\d/.test(password))
      ? "At least 10 characters, with letters and numbers."
      : null;

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setPending(true);
    try {
      const user = isRegister ? await api.auth.register(email, password, name) : await api.auth.login(email, password);
      qc.setQueryData(ME_KEY, user);
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setPending(false);
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">{isRegister ? "Create your account" : "Welcome back"}</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        {isRegister ? "Start with a $100,000 virtual portfolio." : "Sign in to your research workspace."}
      </p>
      <form onSubmit={onSubmit} className="mt-8 grid gap-4" noValidate>
        {isRegister && (
          <Field label="Full name" htmlFor="name">
            <Input id="name" autoComplete="name" required value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
        )}
        <Field label="Email" htmlFor="email">
          <Input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Password" htmlFor="password" hint={isRegister ? "At least 10 characters, with letters and numbers." : undefined} error={passwordHint}>
          <Input
            id="password"
            type="password"
            autoComplete={isRegister ? "new-password" : "current-password"}
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
        {!isRegister && (
          <Link href="/forgot-password" className="-mt-2 justify-self-end text-xs font-medium text-primary hover:underline">
            Forgot password?
          </Link>
        )}
        {error && <p className="rounded-md bg-loss-soft px-3 py-2 text-xs text-loss" role="alert">{error}</p>}
        <Button type="submit" loading={pending} disabled={!email || !password || (isRegister && (!name || !!passwordHint))}>
          {isRegister ? "Create account" : "Sign in"}
        </Button>
      </form>
      {config.data?.demo_enabled && (
        <div className="mt-6">
          <div className="mb-4 flex items-center gap-3 text-xs text-muted-foreground">
            <span className="h-px flex-1 bg-border" /> or <span className="h-px flex-1 bg-border" />
          </div>
          <Button type="button" variant="outline" className="w-full" loading={demoPending} onClick={startDemo}>
            Try the demo
          </Button>
          <p className="mt-2 text-center text-xs text-muted-foreground">
            No sign-up: a private sandbox with sample strategies, deleted after a day.
          </p>
        </div>
      )}
      <p className="mt-6 text-center text-sm text-muted-foreground">
        {isRegister ? "Already have an account? " : "New here? "}
        <Link href={isRegister ? "/login" : "/register"} className="font-medium text-primary hover:underline">
          {isRegister ? "Sign in" : "Create an account"}
        </Link>
      </p>
    </div>
  );
}
