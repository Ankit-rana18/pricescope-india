"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { RefreshCw } from "lucide-react";

import { RequireSignIn } from "@/components/account/require-sign-in";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { admin, type AdminOverview, type AdminUser, type IntegrationRow } from "@/lib/account";
import { ApiError } from "@/lib/api";
import type { Me } from "@/lib/auth";

type Awaited2<T> = T extends Promise<infer U> ? U : never;
type Activity = Awaited2<ReturnType<typeof admin.activity>>;
type Errors = Awaited2<ReturnType<typeof admin.errors>>;
type Audit = Awaited2<ReturnType<typeof admin.audit>>;
type RequestInfo = Awaited2<ReturnType<typeof admin.requestInfo>>;

const DATE = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});
const when = (iso: string | null) => (iso ? DATE.format(new Date(iso)) : "—");

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function Stat({ label, value, tone }: { label: string; value: React.ReactNode; tone?: string }) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-1">
        <span className="text-muted-foreground text-xs">{label}</span>
        <span className={`text-2xl font-semibold tabular-nums ${tone ?? ""}`}>{value}</span>
      </CardContent>
    </Card>
  );
}

function Table({ head, children }: { head: string[]; children: React.ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-2xl border">
      <table className="w-full text-left text-sm">
        <thead className="bg-muted/50 text-muted-foreground text-xs">
          <tr>
            {head.map((h) => (
              <th key={h} scope="col" className="px-3 py-2 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y">{children}</tbody>
      </table>
    </div>
  );
}

const STATE_TONE: Record<string, "success" | "warning" | "neutral" | "danger"> = {
  LIVE: "success",
  DEMO: "warning",
  DEGRADED: "warning",
  DOWN: "danger",
};

interface Data {
  overview: AdminOverview;
  integrations: IntegrationRow[];
  users: AdminUser[];
  activity: Activity;
  errors: Errors;
  audit: Audit;
  connection: RequestInfo;
}

function Dashboard({ me }: { me: Me }) {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const [overview, integrations, users, activity, errors, audit, connection] =
        await Promise.all([
          admin.overview(),
          admin.integrations(),
          admin.users(),
          admin.activity(),
          admin.errors(),
          admin.audit(),
          admin.requestInfo(),
        ]);
      setData({
        overview,
        integrations,
        users: users.items,
        activity,
        errors,
        audit,
        connection,
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.body.message : "Couldn't load the dashboard.");
    } finally {
      setBusy(false);
    }
  }, []);
  useEffect(() => void load(), [load]);

  async function setRole(u: AdminUser) {
    try {
      const updated = await admin.setRole(u.id, u.role === "admin" ? "user" : "admin");
      setData((d) => d && { ...d, users: d.users.map((x) => (x.id === u.id ? updated : x)) });
      void admin.audit().then((audit) => setData((d) => d && { ...d, audit }));
    } catch (err) {
      setError(err instanceof ApiError ? err.body.message : "Couldn't change the role.");
    }
  }

  if (!data) {
    return error ? (
      <p className="text-destructive text-sm">{error}</p>
    ) : (
      <Skeleton className="h-64 w-full" />
    );
  }
  const o = data.overview;

  return (
    <div className="flex flex-col gap-8">
      <div className="flex items-center justify-between gap-3">
        <p className="text-muted-foreground text-sm">
          Storage: {o.storage_backend}{" "}
          <Badge tone={o.storage === "ok" ? "success" : "danger"}>{o.storage}</Badge>
        </p>
        <Button variant="outline" size="sm" onClick={() => void load()} disabled={busy}>
          <RefreshCw aria-hidden className={busy ? "animate-spin" : undefined} /> Refresh
        </Button>
      </div>
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      )}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Users" value={`${o.users}`} />
        <Stat label="Comparisons (24 h)" value={o.comparisons_24h} />
        <Stat label="Comparisons (7 d)" value={o.comparisons_7d} />
        <Stat
          label="Marketplace failures (24 h)"
          value={`${o.marketplace_failures_24h} / ${o.marketplace_checks_24h}`}
          tone={o.marketplace_failures_24h ? "text-destructive" : undefined}
        />
        <Stat label="Admins" value={o.admins} />
        <Stat label="Active alerts" value={o.active_alerts} />
        <Stat label="Alerts triggered (7 d)" value={o.alerts_triggered_7d} />
        <Stat
          label="By status (7 d)"
          value={
            <span className="flex flex-wrap gap-1 text-xs font-normal">
              {Object.entries(o.comparisons_by_status_7d).map(([k, v]) => (
                <Badge key={k} tone="neutral">
                  {k.toLowerCase()} {v}
                </Badge>
              ))}
              {!Object.keys(o.comparisons_by_status_7d).length && "—"}
            </span>
          }
        />
      </div>

      <Section title="Integrations">
        <Table
          head={["Marketplace", "State", "Checks 24 h", "Failures", "Avg latency", "Last error"]}
        >
          {data.integrations.map((i) => (
            <tr key={i.marketplace}>
              <td className="px-3 py-2 font-medium">{i.marketplace_name}</td>
              <td className="px-3 py-2">
                <Badge tone={STATE_TONE[i.state] ?? "neutral"}>
                  {i.state.toLowerCase().replace("_", " ")}
                </Badge>
                <span className="text-muted-foreground block text-xs">{i.reason}</span>
              </td>
              <td className="px-3 py-2 tabular-nums">{i.checks_24h}</td>
              <td className="px-3 py-2 tabular-nums">{i.failures_24h}</td>
              <td className="px-3 py-2 tabular-nums">
                {i.avg_latency_ms == null ? "—" : `${Math.round(i.avg_latency_ms)} ms`}
              </td>
              <td className="text-muted-foreground px-3 py-2 text-xs">{i.last_error ?? "—"}</td>
            </tr>
          ))}
        </Table>
      </Section>

      <Section title="Users">
        <Table head={["Email", "Role", "Joined", "Last seen", ""]}>
          {data.users.map((u) => (
            <tr key={u.id}>
              <td className="px-3 py-2">{u.email}</td>
              <td className="px-3 py-2">
                <Badge tone={u.role === "admin" ? "accent" : "neutral"}>{u.role}</Badge>
              </td>
              <td className="px-3 py-2 text-xs">{when(u.created_at)}</td>
              <td className="px-3 py-2 text-xs">{when(u.last_seen_at)}</td>
              <td className="px-3 py-2 text-right">
                {u.id !== me.id && (
                  <Button variant="outline" size="sm" onClick={() => void setRole(u)}>
                    {u.role === "admin" ? "Remove admin" : "Make admin"}
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </Table>
      </Section>

      <Section title="Recent comparisons">
        {data.activity.length ? (
          <Table head={["When", "Product", "PIN", "Status", "Mode", "User"]}>
            {data.activity.map((a) => (
              <tr key={a.comparison_id}>
                <td className="px-3 py-2 text-xs">{when(a.created_at)}</td>
                <td className="px-3 py-2">
                  <Link href={`/compare/${a.comparison_id}`} className="hover:underline">
                    {a.title ?? "Comparison"}
                  </Link>
                </td>
                <td className="px-3 py-2 tabular-nums">{a.pincode}</td>
                <td className="px-3 py-2">{a.status.toLowerCase()}</td>
                <td className="px-3 py-2">{a.data_mode.toLowerCase()}</td>
                <td className="px-3 py-2 text-xs">{a.signed_in ? "signed in" : "anonymous"}</td>
              </tr>
            ))}
          </Table>
        ) : (
          <p className="text-muted-foreground text-sm">No comparisons yet.</p>
        )}
      </Section>

      <Section title="Your connection (rate-limit check)">
        <div className="bg-card flex flex-col gap-1 rounded-2xl border p-4 text-sm">
          <p>
            Rate limits key anonymous visitors on{" "}
            <span className="font-mono">{data.connection.client_ip_used}</span>{" "}
            <span className="text-muted-foreground">
              (proxy hops trusted: {data.connection.trusted_proxy_hops}; X-Forwarded-For:{" "}
              {data.connection.forwarded_for.join(", ") || "none"})
            </span>
          </p>
          <p className="text-muted-foreground text-xs">{data.connection.note}</p>
        </div>
      </Section>

      <Section title="Recent marketplace errors">
        {data.errors.length ? (
          <Table head={["When", "Marketplace", "Status", "Code", "Message"]}>
            {data.errors.map((e, idx) => (
              <tr key={`${e.occurred_at}-${idx}`}>
                <td className="px-3 py-2 text-xs">{when(e.occurred_at)}</td>
                <td className="px-3 py-2">{e.marketplace_name}</td>
                <td className="px-3 py-2">{e.status.toLowerCase()}</td>
                <td className="px-3 py-2 font-mono text-xs">{e.error_code ?? "—"}</td>
                <td className="text-muted-foreground px-3 py-2 text-xs">{e.message ?? "—"}</td>
              </tr>
            ))}
          </Table>
        ) : (
          <p className="text-muted-foreground text-sm">No errors recorded.</p>
        )}
      </Section>

      <Section title="Audit log">
        {data.audit.length ? (
          <Table head={["When", "Action", "Target", "Details"]}>
            {data.audit.map((a, idx) => (
              <tr key={`${a.occurred_at}-${idx}`}>
                <td className="px-3 py-2 text-xs">{when(a.occurred_at)}</td>
                <td className="px-3 py-2 font-mono text-xs">{a.action}</td>
                <td className="px-3 py-2 text-xs">{a.target ?? "—"}</td>
                <td className="text-muted-foreground px-3 py-2 font-mono text-xs break-all">
                  {JSON.stringify(a.metadata)}
                </td>
              </tr>
            ))}
          </Table>
        ) : (
          <p className="text-muted-foreground text-sm">No audit entries yet.</p>
        )}
      </Section>
    </div>
  );
}

export function AdminDashboard() {
  return <RequireSignIn admin>{(me) => <Dashboard me={me} />}</RequireSignIn>;
}
