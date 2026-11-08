"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ShieldAlert } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { PageHeader } from "@/components/layout/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/overlays";
import { Badge, Input, Switch } from "@/components/ui/primitives";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { useMe } from "@/hooks/use-auth";
import { formatDateTime } from "@/lib/format";
import { api } from "@/services/api";

function UsersTab() {
  const me = useMe();
  const qc = useQueryClient();
  const users = useQuery({ queryKey: ["admin", "users"], queryFn: api.admin.users });
  const update = useMutation({
    mutationFn: ({ id, body }: { id: number; body: { role?: string; is_active?: boolean } }) => api.admin.updateUser(id, body),
    onSuccess: () => {
      toast.success("User updated");
      qc.invalidateQueries({ queryKey: ["admin"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });
  if (users.isLoading) return <LoadingRows rows={5} className="p-3" />;
  if (users.error) return <ErrorState error={users.error} onRetry={() => users.refetch()} />;
  return (
    <Table>
      <THead>
        <TR className="hover:bg-transparent"><TH>User</TH><TH>Role</TH><TH>Active</TH><TH>Joined</TH><TH>Last login</TH></TR>
      </THead>
      <TBody>
        {users.data?.map((u) => {
          const self = u.id === me.data?.id;
          return (
            <TR key={u.id}>
              <TD>
                <p className="font-medium">{u.full_name} {self && <Badge variant="outline">you</Badge>}</p>
                <p className="text-xs text-muted-foreground">{u.email}</p>
              </TD>
              <TD>
                <Select value={u.role} disabled={self} onValueChange={(role) => update.mutate({ id: u.id, body: { role } })}>
                  <SelectTrigger className="h-8 w-28 text-xs" aria-label={`Role for ${u.email}`}><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="user">User</SelectItem>
                    <SelectItem value="admin">Admin</SelectItem>
                  </SelectContent>
                </Select>
              </TD>
              <TD>
                <Switch checked={u.is_active} disabled={self} onCheckedChange={(is_active) => update.mutate({ id: u.id, body: { is_active } })} aria-label={`Toggle ${u.email} active`} />
              </TD>
              <TD className="text-muted-foreground">{formatDateTime(u.created_at)}</TD>
              <TD className="text-muted-foreground">{formatDateTime(u.last_login_at)}</TD>
            </TR>
          );
        })}
      </TBody>
    </Table>
  );
}

function AuditTab() {
  const [action, setAction] = useState("");
  const logs = useQuery({ queryKey: ["admin", "audit", action], queryFn: () => api.admin.auditLogs(action ? { action } : undefined) });
  return (
    <div className="space-y-3">
      <Input value={action} onChange={(e) => setAction(e.target.value.trim())} placeholder="Filter by exact action, e.g. auth.login_failed" className="mx-3 h-8 max-w-sm text-xs" />
      {logs.isLoading ? (
        <LoadingRows rows={6} className="p-3" />
      ) : logs.error ? (
        <ErrorState error={logs.error} onRetry={() => logs.refetch()} />
      ) : !logs.data?.length ? (
        <EmptyState title="No audit entries" />
      ) : (
        <Table>
          <THead>
            <TR className="hover:bg-transparent"><TH>Time</TH><TH>Action</TH><TH>User</TH><TH>Entity</TH><TH>IP</TH><TH>Details</TH></TR>
          </THead>
          <TBody>
            {logs.data.map((l) => (
              <TR key={l.id}>
                <TD className="text-muted-foreground">{formatDateTime(l.created_at)}</TD>
                <TD><Badge variant={l.action.includes("failed") ? "loss" : l.action.startsWith("admin") ? "warn" : "secondary"}>{l.action}</Badge></TD>
                <TD>{l.user_id ?? "—"}</TD>
                <TD className="text-muted-foreground">{l.entity_type ? `${l.entity_type}#${l.entity_id}` : "—"}</TD>
                <TD className="text-muted-foreground">{l.ip_address ?? "—"}</TD>
                <TD className="max-w-80 truncate font-mono text-[11px] text-muted-foreground" title={JSON.stringify(l.details)}>{Object.keys(l.details).length ? JSON.stringify(l.details) : "—"}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      )}
    </div>
  );
}

export function AdminView() {
  const me = useMe();
  if (me.data && me.data.role !== "admin") {
    return <Card><EmptyState icon={ShieldAlert} title="Administrator access required" description="Your account does not have the admin role." /></Card>;
  }
  return (
    <>
      <PageHeader title="Administration" description="User management and the security audit trail." />
      <Card>
        <Tabs defaultValue="users">
          <CardHeader>
            <CardTitle className="sr-only">Admin</CardTitle>
            <TabsList>
              <TabsTrigger value="users">Users</TabsTrigger>
              <TabsTrigger value="audit">Audit log</TabsTrigger>
            </TabsList>
          </CardHeader>
          <CardContent className="px-2">
            <TabsContent value="users"><UsersTab /></TabsContent>
            <TabsContent value="audit"><AuditTab /></TabsContent>
          </CardContent>
        </Tabs>
      </Card>
    </>
  );
}
