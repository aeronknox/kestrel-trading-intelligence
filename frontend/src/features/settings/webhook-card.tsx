"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, RefreshCw, Send, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge, Field, Input } from "@/components/ui/primitives";
import { timeAgo } from "@/lib/format";
import { api } from "@/services/api";
import type { Webhook } from "@/types/api";

export const WEBHOOK_KEY = ["webhook"] as const;
const FORMAT_LABEL = { slack: "Slack", discord: "Discord", json: "Signed JSON" } as const;

/** Where strategy alerts are posted when an alert has "Webhook" switched on. */
export function WebhookCard({ isDemo }: { isDemo: boolean }) {
  const qc = useQueryClient();
  const hook = useQuery({ queryKey: WEBHOOK_KEY, queryFn: api.users.webhook, enabled: !isDemo });
  const [draft, setDraft] = useState<string | null>(null);
  const [showSecret, setShowSecret] = useState(false);
  const url = draft ?? hook.data?.url ?? "";
  const saved = (w: Webhook) => qc.setQueryData(WEBHOOK_KEY, w);

  const save = useMutation({
    mutationFn: () => api.users.setWebhook(url.trim()),
    onSuccess: (w) => {
      saved(w);
      setDraft(null);
      toast.success("Webhook saved. Send a test to check it.");
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const test = useMutation({
    mutationFn: api.users.testWebhook,
    onSuccess: (r) => {
      saved(r.webhook);
      if (r.ok) toast.success(`Test delivered (${r.webhook.last_status})`);
      else toast.error(r.webhook.last_status ?? "Test failed");
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const remove = useMutation({
    mutationFn: api.users.removeWebhook,
    onSuccess: (w) => {
      saved(w);
      setDraft(null);
      toast.success("Webhook removed");
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const rotate = useMutation({
    mutationFn: api.users.rotateWebhookSecret,
    onSuccess: (w) => {
      saved(w);
      setShowSecret(true);
      toast.success("New signing secret. Update your receiver.");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const w = hook.data;
  const failed = w?.last_status?.startsWith("Failed");
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Alert webhook</CardTitle>
          <CardDescription>
            Post strategy alerts to Slack, Discord or your own HTTPS endpoint. Switch it on per alert on a strategy&apos;s page.
          </CardDescription>
        </div>
        {w?.format && <Badge variant="secondary">{FORMAT_LABEL[w.format]}</Badge>}
      </CardHeader>
      <CardContent className="space-y-4">
        {isDemo ? (
          <p className="text-sm text-muted-foreground">Webhooks are not available in the demo. Create a free account to use them.</p>
        ) : (
          <>
            <form
              className="flex flex-col gap-2 sm:flex-row sm:items-end"
              onSubmit={(e) => {
                e.preventDefault();
                save.mutate();
              }}
            >
              <Field label="Webhook URL" className="min-w-0 flex-1">
                <Input
                  type="url"
                  inputMode="url"
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="https://hooks.slack.com/services/…"
                  value={url}
                  maxLength={500}
                  onChange={(e) => setDraft(e.target.value)}
                />
              </Field>
              <Button type="submit" size="sm" loading={save.isPending} disabled={!url.trim() || url.trim() === w?.url}>
                Save webhook
              </Button>
            </form>
            <p className="-mt-2 text-xs text-muted-foreground">https:// only. Requests go to public internet addresses only.</p>

            {w?.url && (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <Button size="sm" variant="outline" onClick={() => test.mutate()} loading={test.isPending}>
                    <Send aria-hidden /> Send test
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => window.confirm("Remove the webhook? Alerts stop posting to it.") && remove.mutate()} loading={remove.isPending}>
                    <Trash2 aria-hidden /> Remove
                  </Button>
                  <p className="text-xs text-muted-foreground" role="status">
                    {w.last_status ? (
                      <>
                        Last delivery: <span className={failed ? "text-warn" : "text-gain"}>{w.last_status}</span>
                        {w.last_at && <> · {timeAgo(w.last_at)}</>}
                      </>
                    ) : (
                      "Not delivered yet"
                    )}
                  </p>
                </div>

                {w.format === "json" && w.secret && (
                  <div className="space-y-2 rounded-md border border-dashed border-border p-3">
                    <p className="text-sm font-medium">Signing secret</p>
                    <p className="text-xs text-muted-foreground">
                      Each request carries <code>X-Kestrel-Timestamp</code> and <code>X-Kestrel-Signature: sha256=…</code>, the
                      HMAC-SHA256 of <code>timestamp.body</code> with this secret. Verify it, and reject old timestamps, before trusting a request.
                    </p>
                    <div className="flex flex-wrap items-center gap-2">
                      <code className="min-w-0 max-w-full truncate rounded bg-muted px-2 py-1 text-xs">
                        {showSecret ? w.secret : "•".repeat(24)}
                      </code>
                      <Button size="sm" variant="ghost" onClick={() => setShowSecret((s) => !s)}>{showSecret ? "Hide" : "Show"}</Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => navigator.clipboard.writeText(w.secret ?? "").then(() => toast.success("Secret copied"), () => toast.error("Copy failed"))}
                      >
                        <Copy aria-hidden /> Copy
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => window.confirm("Replace the signing secret? Requests signed with the old one will fail verification.") && rotate.mutate()} loading={rotate.isPending}>
                        <RefreshCw aria-hidden /> Rotate
                      </Button>
                    </div>
                  </div>
                )}
              </>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
