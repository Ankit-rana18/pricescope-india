"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  AlertCircle,
  ArrowLeft,
  CreditCard,
  FlaskConical,
  Info,
  Loader2,
  MapPin,
  TrendingDown,
} from "lucide-react";

import { ResultCard } from "@/components/compare/result-card";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";
import {
  FINAL_STATUSES,
  formatINR,
  getComparison,
  type ComparisonView as Comparison,
} from "@/lib/comparison";

function usePolledComparison(id: string) {
  const [data, setData] = useState<Comparison | null>(null);
  const [error, setError] = useState<string | null>(null);
  const delay = useRef(700);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();
    let cancelled = false;

    async function tick() {
      try {
        const next = await getComparison(id, controller.signal);
        if (cancelled) return;
        setData(next);
        setError(null);
        if (!FINAL_STATUSES.includes(next.status)) {
          delay.current = Math.min(delay.current * 1.4, 3000);
          timer = setTimeout(tick, delay.current);
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setError(err.body.message);
          return;
        }
        setError("Lost contact with the PriceScope service. Retrying…");
        timer = setTimeout(tick, 3000);
      }
    }
    void tick();
    return () => {
      cancelled = true;
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [id]);

  return { data, error };
}

function SourceChips({ c }: { c: Comparison }) {
  const n = c.source.normalized;
  const chips = [
    n.size && `${n.size}${n.pack_count > 1 ? ` × ${n.pack_count}` : ""}`,
    n.pack_count > 1 && !n.size && `Pack of ${n.pack_count}`,
    n.colour,
    n.ram_gb && `${n.ram_gb} GB RAM`,
    n.storage_gb && `${n.storage_gb} GB`,
  ].filter(Boolean) as string[];
  return (
    <div className="flex flex-wrap gap-2">
      {chips.map((chip) => (
        <Badge key={chip} tone="neutral" className="capitalize">
          {chip}
        </Badge>
      ))}
      <Badge tone="neutral">
        <MapPin aria-hidden /> {c.pincode}
      </Badge>
      {c.data_mode === "DEMO" && (
        <Badge tone="warning">
          <FlaskConical aria-hidden /> Demo data
        </Badge>
      )}
    </div>
  );
}

function Summary({ c }: { c: Comparison }) {
  const s = c.summary;
  const done = FINAL_STATUSES.includes(c.status);
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Card>
        <CardContent className="flex flex-col gap-1">
          <span className="text-muted-foreground inline-flex items-center gap-1.5 text-xs font-medium tracking-wide uppercase">
            <TrendingDown className="size-4" aria-hidden /> Cheapest verified
          </span>
          {s.cheapest ? (
            <>
              <span className="tabular text-3xl font-semibold tracking-tight">
                {formatINR(s.cheapest.final_price)}
              </span>
              <span className="text-sm">
                on <span className="font-medium">{s.cheapest.marketplace_name}</span>
                {s.savings_vs_source && Number(s.savings_vs_source) > 0 && (
                  <span className="text-success">
                    {" "}
                    · saves {formatINR(s.savings_vs_source)} vs your link
                  </span>
                )}
              </span>
            </>
          ) : (
            <span className="text-muted-foreground text-sm">
              {done
                ? "No exact match with a complete price and verified delivery to your PIN code."
                : "Waiting for marketplaces…"}
            </span>
          )}
          {s.cheaper_unverified && (
            <p className="text-muted-foreground mt-2 text-xs">
              {s.cheaper_unverified.marketplace_name} shows{" "}
              {formatINR(s.cheaper_unverified.final_price)}, but delivery to {c.pincode} can&apos;t
              be verified there.
            </p>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardContent className="flex flex-col gap-1">
          <span className="text-muted-foreground inline-flex items-center gap-1.5 text-xs font-medium tracking-wide uppercase">
            <CreditCard className="size-4" aria-hidden /> Best with a card offer
          </span>
          {s.best_with_card ? (
            <>
              <span className="tabular text-3xl font-semibold tracking-tight">
                {formatINR(s.best_with_card.price_after_card)}
              </span>
              <span className="text-sm">
                on <span className="font-medium">{s.best_with_card.marketplace_name}</span> with a{" "}
                {s.best_with_card.card} (−{formatINR(s.best_with_card.discount)})
              </span>
              <p className="text-muted-foreground mt-1 text-xs">
                Only if you pay with that card. Offer terms apply.
                {!s.best_with_card.delivery_verified &&
                  ` Delivery to ${c.pincode} can't be verified on ${s.best_with_card.marketplace_name}.`}
              </p>
            </>
          ) : (
            <span className="text-muted-foreground text-sm">
              {done ? "No card offers found for exact matches." : "Waiting for marketplaces…"}
            </span>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export function ComparisonView({ id }: { id: string }) {
  const { data, error } = usePolledComparison(id);

  if (!data) {
    return error ? (
      <div
        role="alert"
        className="border-destructive/30 bg-destructive/5 text-destructive flex gap-3 rounded-xl border p-4 text-sm"
      >
        <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
        <p>{error}</p>
      </div>
    ) : (
      <div className="flex flex-col gap-4" aria-busy>
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  const pending = data.results.filter((r) => r.status === "PENDING").length;
  const done = FINAL_STATUSES.includes(data.status);
  const demo = data.data_mode === "DEMO";

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3">
        <Link
          href="/"
          className="text-muted-foreground hover:text-foreground inline-flex w-fit items-center gap-1 text-sm"
        >
          <ArrowLeft className="size-4" aria-hidden /> New comparison
        </Link>
        <p className="text-muted-foreground text-sm">
          {data.source.marketplace_name}
          {data.source.brand && ` · ${data.source.brand}`}
        </p>
        <h1 className="text-2xl font-semibold tracking-tight text-balance sm:text-3xl">
          {data.source.title}
        </h1>
        <SourceChips c={data} />
      </div>

      <div
        role="status"
        aria-live="polite"
        className="text-muted-foreground flex items-center gap-2 text-sm"
      >
        {!done ? (
          <>
            <Loader2 className="size-4 animate-spin" aria-hidden />
            Checking marketplaces… {5 - pending} of 5 answered
          </>
        ) : data.status === "PARTIAL" ? (
          <>
            <Info className="size-4" aria-hidden /> {data.summary.marketplaces_failed} marketplace
            {data.summary.marketplaces_failed > 1 ? "s" : ""} couldn&apos;t be checked; the rest are
            shown.
          </>
        ) : data.status === "FAILED" ? (
          <>
            <AlertCircle className="size-4" aria-hidden /> No marketplace could be checked.
          </>
        ) : (
          <>
            <Info className="size-4" aria-hidden /> All marketplaces checked.
          </>
        )}
        {data.reused && <span>· Results from the last few minutes</span>}
      </div>

      {error && <p className="text-warning text-sm">{error}</p>}
      {data.storage_note && <p className="text-warning text-sm">{data.storage_note}</p>}

      <Summary c={data} />

      <section aria-label="Results by marketplace" className="flex flex-col gap-4">
        {data.results.map((r) => (
          <ResultCard key={r.marketplace} result={r} demo={demo} />
        ))}
      </section>

      <p className="text-muted-foreground text-xs">
        Ranked: exact matches that are in stock with a complete final price, cheapest first. Results
        whose delivery to your PIN code is verified come first. Probable and mismatched listings are
        shown but never ranked.
      </p>
    </div>
  );
}
