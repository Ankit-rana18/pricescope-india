"use client";

import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from "recharts";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { formatINR } from "@/lib/comparison";
import type { MarketplaceCode } from "@/lib/api";
import { getPriceHistory, SERIES_COLOR, type PriceHistoryView } from "@/lib/products";

type Row = { t: number } & Partial<Record<MarketplaceCode, number>>;

const DATE = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short" });
const DATETIME = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

/**
 * Merge series into rows by minute (one comparison = one moment). Incomplete prices and
 * prices with estimated fees are gaps: the chart only plots confirmed final prices.
 */
function toRows(h: PriceHistoryView): Row[] {
  const rows = new Map<number, Row>();
  for (const s of h.series) {
    for (const p of s.points) {
      if (p.final_price === null || !p.final_price_complete || p.final_price_estimated) continue;
      const t = Math.floor(new Date(p.observed_at).getTime() / 60000) * 60000;
      const row = rows.get(t) ?? { t };
      row[s.marketplace] = Number(p.final_price);
      rows.set(t, row);
    }
  }
  return [...rows.values()].sort((a, b) => a.t - b.t);
}

function ChartTooltip({
  active,
  payload,
  label,
  names,
}: TooltipContentProps<number, string> & { names: Record<string, string> }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-popover text-popover-foreground rounded-lg border px-3 py-2 text-xs shadow-md">
      <div className="text-muted-foreground mb-1">{DATETIME.format(Number(label))}</div>
      {[...payload]
        .sort((a, b) => Number(a.value) - Number(b.value))
        .map((item) => (
          <div key={String(item.dataKey)} className="flex items-center gap-2">
            <span
              className="inline-block h-0.5 w-3 rounded"
              style={{ background: item.color }}
              aria-hidden
            />
            <span className="tabular font-semibold">{formatINR(String(item.value))}</span>
            <span className="text-muted-foreground">{names[String(item.dataKey)]}</span>
          </div>
        ))}
    </div>
  );
}

export function PriceHistoryChart({
  slug,
  pincode,
  refreshKey,
}: {
  slug: string;
  pincode?: string | null;
  refreshKey?: unknown;
}) {
  const [data, setData] = useState<PriceHistoryView | null>(null);
  const [error, setError] = useState(false);
  const [asTable, setAsTable] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getPriceHistory(slug, { pincode, days: 90 })
      .then((h) => !cancelled && setData(h))
      .catch(() => !cancelled && setError(true));
    return () => {
      cancelled = true;
    };
  }, [slug, pincode, refreshKey]);

  const rows = useMemo(() => (data ? toRows(data) : []), [data]);
  const names = useMemo(
    () => Object.fromEntries((data?.series ?? []).map((s) => [s.marketplace, s.marketplace_name])),
    [data],
  );

  if (error) return <p className="text-muted-foreground text-sm">Price history is unavailable.</p>;
  if (!data) return <Skeleton className="h-48 w-full" />;
  if (rows.length === 0) {
    return (
      <p className="text-muted-foreground text-sm">No complete prices have been recorded yet.</p>
    );
  }

  const series = data.series.filter((s) => rows.some((r) => r[s.marketplace] !== undefined));

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {/* Legend: line keys, text in text tokens (never the series colour). */}
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs" aria-label="Marketplaces">
          {series.map((s) => (
            <li key={s.marketplace} className="inline-flex items-center gap-1.5">
              <span
                className="inline-block h-0.5 w-4 rounded"
                style={{ background: SERIES_COLOR[s.marketplace] }}
                aria-hidden
              />
              {s.marketplace_name}
            </li>
          ))}
        </ul>
        <Button variant="ghost" size="sm" onClick={() => setAsTable((v) => !v)}>
          {asTable ? "Show as chart" : "Show as table"}
        </Button>
      </div>

      {rows.length < 2 && !asTable && (
        <p className="text-muted-foreground text-xs">
          Only one check so far. The history builds up each time this product is compared.
        </p>
      )}

      {asTable ? (
        <div className="overflow-x-auto">
          <table className="tabular w-full text-sm">
            <caption className="sr-only">Final price by marketplace over time</caption>
            <thead>
              <tr className="text-muted-foreground border-b text-left text-xs">
                <th className="py-1.5 pr-4 font-medium">Checked</th>
                {series.map((s) => (
                  <th key={s.marketplace} className="py-1.5 pr-4 text-right font-medium">
                    {s.marketplace_name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[...rows].reverse().map((r) => (
                <tr key={r.t} className="border-b last:border-0">
                  <td className="py-1.5 pr-4">{DATETIME.format(r.t)}</td>
                  {series.map((s) => (
                    <td key={s.marketplace} className="py-1.5 pr-4 text-right">
                      {r[s.marketplace] !== undefined ? formatINR(String(r[s.marketplace])) : "—"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="h-56 w-full" role="img" aria-label="Final price over time by marketplace">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
              <XAxis
                dataKey="t"
                type="number"
                scale="time"
                domain={["dataMin", "dataMax"]}
                tickFormatter={(t: number) => DATE.format(t)}
                tick={{ fill: "var(--muted-foreground)", fontSize: 11 }}
                tickLine={false}
                axisLine={{ stroke: "var(--chart-grid)" }}
                minTickGap={24}
              />
              <YAxis
                tickFormatter={(v: number) => formatINR(String(v))}
                tick={{ fill: "var(--muted-foreground)", fontSize: 11 }}
                tickLine={false}
                axisLine={false}
                width={72}
                domain={["auto", "auto"]}
              />
              <Tooltip
                cursor={{ stroke: "var(--muted-foreground)", strokeWidth: 1 }}
                content={(props) => (
                  <ChartTooltip {...(props as TooltipContentProps<number, string>)} names={names} />
                )}
              />
              {series.map((s) => (
                <Line
                  key={s.marketplace}
                  dataKey={s.marketplace}
                  stroke={SERIES_COLOR[s.marketplace]}
                  strokeWidth={2}
                  dot={rows.length < 2 ? { r: 4, strokeWidth: 2, fill: "var(--card)" } : false}
                  activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--card)" }}
                  connectNulls
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      {data.data_mode === "DEMO" && (
        <p className="text-muted-foreground text-xs">Demo data: these are not real prices.</p>
      )}
    </div>
  );
}
