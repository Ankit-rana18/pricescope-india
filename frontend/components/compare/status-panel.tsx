"use client";

import { useEffect, useState } from "react";
import { Database } from "lucide-react";

import { StatusBadge } from "@/components/compare/badges";
import { Badge } from "@/components/ui/badge";
import { apiFetch, type DataMode, type MarketplaceCode } from "@/lib/api";
import type { ResultView } from "@/lib/comparison";

interface MarketplaceStatus {
  marketplace: MarketplaceCode;
  marketplace_name: string;
  state: "LIVE" | "DEGRADED" | "NOT_CONFIGURED" | "UNSUPPORTED" | "DEMO";
  reason: string;
}

const STATE_LABEL: Record<
  MarketplaceStatus["state"],
  { text: string; tone: "success" | "warning" | "neutral" | "danger" }
> = {
  LIVE: { text: "Live", tone: "success" },
  DEGRADED: { text: "Degraded", tone: "warning" },
  NOT_CONFIGURED: { text: "Not connected", tone: "warning" },
  UNSUPPORTED: { text: "No data access", tone: "neutral" },
  DEMO: { text: "Demo data", tone: "warning" },
};

/** Where each marketplace's data comes from, and how this comparison's check went. */
export function StatusPanel({ results }: { results: ResultView[] }) {
  const [statuses, setStatuses] = useState<MarketplaceStatus[] | null>(null);

  useEffect(() => {
    apiFetch<{ data_mode: DataMode; marketplaces: MarketplaceStatus[] }>("/api/v1/marketplaces", {
      cache: "no-store",
    })
      .then((r) => setStatuses(r.marketplaces))
      .catch(() => setStatuses([]));
  }, []);

  const byCode = new Map(statuses?.map((s) => [s.marketplace, s]));

  return (
    <details className="bg-card rounded-2xl border">
      <summary className="hover:bg-muted/50 flex cursor-pointer list-none items-center gap-2 rounded-2xl px-5 py-3 text-sm font-medium select-none">
        <Database className="size-4" aria-hidden /> Data sources
      </summary>
      <div className="overflow-x-auto border-t px-5 py-3">
        <table className="w-full text-sm">
          <caption className="sr-only">Data source and check status per marketplace</caption>
          <thead>
            <tr className="text-muted-foreground text-left text-xs">
              <th className="py-1.5 pr-4 font-medium">Marketplace</th>
              <th className="py-1.5 pr-4 font-medium">Integration</th>
              <th className="py-1.5 pr-4 font-medium">This check</th>
              <th className="py-1.5 font-medium">Details</th>
            </tr>
          </thead>
          <tbody>
            {results.map((r) => {
              const s = byCode.get(r.marketplace);
              const label = s ? STATE_LABEL[s.state] : null;
              return (
                <tr key={r.marketplace} className="border-t align-top">
                  <td className="py-2 pr-4 font-medium">{r.marketplace_name}</td>
                  <td className="py-2 pr-4">
                    {label ? <Badge tone={label.tone}>{label.text}</Badge> : "…"}
                  </td>
                  <td className="py-2 pr-4">
                    {r.status === "OK" ? (
                      <Badge tone="success">Checked</Badge>
                    ) : (
                      <StatusBadge status={r.status} />
                    )}
                  </td>
                  <td className="text-muted-foreground py-2 text-xs">
                    {[
                      r.attempts ? `${r.attempts} attempt${r.attempts > 1 ? "s" : ""}` : null,
                      r.latency_ms != null ? `${(r.latency_ms / 1000).toFixed(1)} s` : null,
                      r.status !== "OK" ? r.status_reason : null,
                      s && s.state !== "DEMO" && s.state !== "LIVE" ? s.reason : null,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </details>
  );
}
