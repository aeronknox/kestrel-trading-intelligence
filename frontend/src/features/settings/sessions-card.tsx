"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Monitor } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/primitives";
import { formatDateTime, timeAgo } from "@/lib/format";
import { api } from "@/services/api";

const SESSIONS_KEY = ["auth", "sessions"] as const;

/** Where the account is signed in; sign out a lost or shared device, or everywhere else at once. */
export function SessionsCard() {
  const qc = useQueryClient();
  const sessions = useQuery({ queryKey: SESSIONS_KEY, queryFn: api.auth.sessions });
  const done = (message: string) => {
    qc.invalidateQueries({ queryKey: SESSIONS_KEY });
    toast.success(message);
  };
  const revoke = useMutation({
    mutationFn: api.auth.revokeSession,
    onSuccess: (r) => done(r.message),
    onError: (e: Error) => toast.error(e.message),
  });
  const revokeOthers = useMutation({
    mutationFn: api.auth.revokeOtherSessions,
    onSuccess: (r) => done(r.message),
    onError: (e: Error) => toast.error(e.message),
  });
  const others = sessions.data?.filter((s) => !s.current).length ?? 0;

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Where you&apos;re signed in</CardTitle>
          <CardDescription>Sign out a device you no longer use, or one you don&apos;t recognise (then change your password).</CardDescription>
        </div>
        <Button size="sm" variant="outline" disabled={!others} loading={revokeOthers.isPending} onClick={() => revokeOthers.mutate()}>
          Sign out everywhere else
        </Button>
      </CardHeader>
      <CardContent className="px-2">
        {sessions.isLoading ? (
          <p className="px-3 py-2 text-sm text-muted-foreground">Loading…</p>
        ) : (
          <ul className="divide-y divide-border">
            {sessions.data?.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-3 py-2.5">
                <div className="flex min-w-0 items-center gap-3">
                  <Monitor className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                  <div className="min-w-0">
                    <p className="text-sm font-medium">
                      {s.device} {s.current && <Badge variant="info" className="ml-1">This device</Badge>}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {s.current ? "Active now" : <span title={formatDateTime(s.last_seen_at)}>Last active {timeAgo(s.last_seen_at)}</span>}
                      {s.ip_address ? ` · ${s.ip_address}` : ""} · signed in {formatDateTime(s.created_at)}
                    </p>
                  </div>
                </div>
                {!s.current && (
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={`Sign out ${s.device}, last active ${timeAgo(s.last_seen_at)}`}
                    loading={revoke.isPending && revoke.variables === s.id}
                    onClick={() => revoke.mutate(s.id)}
                  >
                    Sign out
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
