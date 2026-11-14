"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useState } from "react";

import { DownloadButton } from "@/components/common/download-button";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/overlays";
import { Field, Input } from "@/components/ui/primitives";
import { api } from "@/services/api";

/** Download everything the app holds about you, or delete the account and all of it. */
export function AccountDataCard({ isDemo }: { isDemo: boolean }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const remove = useMutation({
    mutationFn: () => api.auth.deleteAccount(isDemo ? null : password, confirm),
    onSuccess: () => {
      qc.clear();
      // A full load, so nothing of the deleted account survives in memory.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign("/login");
    },
  });
  const ready = confirm.trim() === "DELETE" && (isDemo || password.length > 0);

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Your data</CardTitle>
          <CardDescription>Everything stored about you is yours: take a copy, or delete it.</CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="max-w-prose text-sm text-muted-foreground">
            One JSON file with your profile, settings, strategies, backtests, paper trades, journal, alerts and assistant chats. Passwords and
            sign-in tokens are never included.
          </p>
          <DownloadButton href="/users/me/export" label="Download all your data as a JSON file">My data (JSON)</DownloadButton>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-loss/40 bg-loss-soft px-3 py-3">
          <div className="min-w-0">
            <p className="text-sm font-medium">Delete account</p>
            <p className="text-xs text-muted-foreground">
              Permanently removes your account and all of its data. This can&apos;t be undone; download a copy first if you want one.
            </p>
          </div>
          <Dialog
            open={open}
            onOpenChange={(o) => {
              setOpen(o);
              if (!o) {
                setPassword("");
                setConfirm("");
                remove.reset();
              }
            }}
          >
            <DialogTrigger asChild>
              <Button variant="loss" size="sm"><Trash2 aria-hidden /> Delete account</Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Delete your account?</DialogTitle>
                <DialogDescription>
                  Your strategies, backtests, paper portfolio and trades, journal, alerts and assistant chats are deleted for good, and you are
                  signed out everywhere. You can sign up again with the same email later, starting from scratch.
                </DialogDescription>
              </DialogHeader>
              <form
                className="grid gap-4"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (ready) remove.mutate();
                }}
              >
                {!isDemo && (
                  <Field label="Your password" htmlFor="delete-password">
                    <Input id="delete-password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
                  </Field>
                )}
                <Field label="Type DELETE to confirm" htmlFor="delete-confirm">
                  <Input id="delete-confirm" autoComplete="off" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
                </Field>
                {remove.error && <p className="rounded-md bg-loss-soft px-3 py-2 text-xs text-loss" role="alert">{remove.error.message}</p>}
                <DialogFooter>
                  <Button type="button" variant="outline" onClick={() => setOpen(false)}>Keep my account</Button>
                  <Button type="submit" variant="loss" loading={remove.isPending} disabled={!ready}>Delete everything</Button>
                </DialogFooter>
              </form>
            </DialogContent>
          </Dialog>
        </div>
      </CardContent>
    </Card>
  );
}
