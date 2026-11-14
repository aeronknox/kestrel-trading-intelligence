"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge, Field, Input, Switch } from "@/components/ui/primitives";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ME_KEY, useMe } from "@/hooks/use-auth";
import { useTheme } from "@/hooks/use-theme";
import { formatDate } from "@/lib/format";
import { api } from "@/services/api";
import { TIMEFRAMES, type Timeframe, type UserSettings } from "@/types/api";

import { AccountDataCard } from "./account-data-card";
import { WebhookCard } from "./webhook-card";

export function SettingsView() {
  const me = useMe();
  const qc = useQueryClient();
  const { theme, toggle } = useTheme();
  const assets = useQuery({ queryKey: ["assets"], queryFn: () => api.market.assets(), staleTime: 300_000 });
  // Drafts stay null until edited, so the fields show the saved profile without copying it into state.
  const [nameDraft, setName] = useState<string | null>(null);
  const [prefsDraft, setPrefs] = useState<Partial<UserSettings> | null>(null);
  const name = nameDraft ?? me.data?.full_name ?? "";
  const prefs: Partial<UserSettings> = prefsDraft ?? me.data?.settings ?? {};
  const [pw, setPw] = useState({ current: "", next: "", confirm: "" });

  const saveProfile = useMutation({
    mutationFn: () => api.users.updateProfile(name.trim()),
    onSuccess: (u) => {
      qc.setQueryData(ME_KEY, u);
      toast.success("Profile updated");
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const savePrefs = useMutation({
    mutationFn: () => api.users.updateSettings({ default_symbol: prefs.default_symbol, default_timeframe: prefs.default_timeframe, risk_tolerance: prefs.risk_tolerance }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ME_KEY });
      toast.success("Preferences saved");
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const changePw = useMutation({
    mutationFn: () => api.auth.changePassword(pw.current, pw.next),
    onSuccess: (r) => {
      setPw({ current: "", next: "", confirm: "" });
      toast.success(r.message);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  if (!me.data) return null;
  const pwError = pw.next && (pw.next.length < 10 || !/[a-z]/i.test(pw.next) || !/\d/.test(pw.next)) ? "At least 10 characters, with letters and numbers." : pw.confirm && pw.confirm !== pw.next ? "Passwords do not match." : null;

  return (
    <>
      <PageHeader title="Settings" description="Manage your profile, preferences and security." />
      <div className="grid max-w-4xl gap-4">
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Profile</CardTitle>
              <CardDescription>Member since {formatDate(me.data.created_at)}</CardDescription>
            </div>
            <Badge variant={me.data.role === "admin" ? "default" : "secondary"}>{me.data.role}</Badge>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <Field label="Full name">
              <Input value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label="Email">
              <Input value={me.data.email} disabled />
            </Field>
            <div className="sm:col-span-2">
              <Button size="sm" onClick={() => saveProfile.mutate()} loading={saveProfile.isPending} disabled={!name.trim() || name === me.data.full_name}>Save profile</Button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>Preferences</CardTitle>
              <CardDescription>Defaults used across charts and AI analysis</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-3">
            <Field label="Default asset">
              <Select value={prefs.default_symbol} onValueChange={(v) => setPrefs({ ...prefs, default_symbol: v })}>
                <SelectTrigger><SelectValue placeholder="Select" /></SelectTrigger>
                <SelectContent>
                  {(assets.data ?? []).map((a) => <SelectItem key={a.symbol} value={a.symbol}>{a.symbol}</SelectItem>)}
                </SelectContent>
              </Select>
            </Field>
            <Field label="Default timeframe">
              <Select value={prefs.default_timeframe} onValueChange={(v) => setPrefs({ ...prefs, default_timeframe: v as Timeframe })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {TIMEFRAMES.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}
                </SelectContent>
              </Select>
            </Field>
            <Field label="Risk tolerance">
              <Select value={prefs.risk_tolerance} onValueChange={(v) => setPrefs({ ...prefs, risk_tolerance: v as UserSettings["risk_tolerance"] })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="conservative">Conservative</SelectItem>
                  <SelectItem value="moderate">Moderate</SelectItem>
                  <SelectItem value="aggressive">Aggressive</SelectItem>
                </SelectContent>
              </Select>
            </Field>
            <div className="flex items-center justify-between rounded-lg border border-border px-3 py-2.5 sm:col-span-3">
              <div>
                <p className="text-sm font-medium">Dark theme</p>
                <p className="text-xs text-muted-foreground">Stored in this browser</p>
              </div>
              <Switch checked={theme === "dark"} onCheckedChange={toggle} aria-label="Dark theme" />
            </div>
            <div className="sm:col-span-3">
              <Button size="sm" onClick={() => savePrefs.mutate()} loading={savePrefs.isPending}>Save preferences</Button>
            </div>
          </CardContent>
        </Card>

        <WebhookCard isDemo={me.data.is_demo} />

        {!me.data.is_demo && (
          <Card>
            <CardHeader>
              <div>
                <CardTitle>Change password</CardTitle>
                <CardDescription>Other active sessions will be signed out.</CardDescription>
              </div>
            </CardHeader>
            <CardContent>
              <form className="grid gap-4 sm:grid-cols-3" onSubmit={(e) => { e.preventDefault(); changePw.mutate(); }}>
                <Field label="Current password">
                  <Input type="password" autoComplete="current-password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} />
                </Field>
                <Field label="New password">
                  <Input type="password" autoComplete="new-password" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} />
                </Field>
                <Field label="Confirm new password" error={pwError}>
                  <Input type="password" autoComplete="new-password" value={pw.confirm} onChange={(e) => setPw({ ...pw, confirm: e.target.value })} />
                </Field>
                <div className="sm:col-span-3">
                  <Button size="sm" type="submit" loading={changePw.isPending} disabled={!pw.current || !pw.next || pw.next !== pw.confirm || !!pwError}>Update password</Button>
                </div>
              </form>
            </CardContent>
          </Card>
        )}

        <AccountDataCard isDemo={me.data.is_demo} />
      </div>
    </>
  );
}
