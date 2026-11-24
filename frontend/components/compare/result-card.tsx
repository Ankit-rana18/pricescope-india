import {
  Clock,
  CreditCard,
  ExternalLink,
  FlaskConical,
  MapPin,
  PackageX,
  Trophy,
} from "lucide-react";

import { LOCATION_TEXT, MatchBadge, StatusBadge } from "@/components/compare/badges";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { formatINR, type CardOfferView, type ChargeView, type ResultView } from "@/lib/comparison";
import { cn } from "@/lib/utils";

const CHARGE_ROWS: [keyof NonNullable<ResultView["price"]>, string][] = [
  ["delivery_fee", "Delivery"],
  ["handling_fee", "Handling"],
  ["platform_fee", "Platform fee"],
  ["other_fees", "Other charges"],
];

function chargeText(c: ChargeView): string {
  if (c.status === "UNKNOWN") return "Unknown";
  if (c.status === "NOT_APPLICABLE") return "—";
  const value = Number(c.amount) === 0 ? "Free" : formatINR(c.amount);
  return c.status === "ESTIMATED" ? `≈ ${value}` : value;
}

function cardLabel(c: CardOfferView): string {
  const what = c.kind === "PERCENT" ? `${Number(c.value)}% off` : `${formatINR(c.value)} off`;
  const cap = c.max_discount ? `, up to ${formatINR(c.max_discount)}` : "";
  const min = c.min_order_value ? ` · min order ${formatINR(c.min_order_value)}` : "";
  return `${what}${cap}${min}`;
}

export function ResultCard({ result, demo }: { result: ResultView; demo: boolean }) {
  const r = result;
  const p = r.price;
  return (
    <Card
      className={cn(
        "overflow-hidden",
        r.is_cheapest && "ring-primary/60 ring-2",
        !r.ranked && r.status === "OK" && "bg-muted/30",
      )}
    >
      <CardContent className="flex flex-col gap-4">
        {/* Header */}
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="font-semibold">{r.marketplace_name}</h3>
              {r.rank !== null && (
                <span className="text-muted-foreground tabular text-xs">#{r.rank}</span>
              )}
              {r.is_cheapest && (
                <Badge tone="accent">
                  <Trophy aria-hidden /> Cheapest verified
                </Badge>
              )}
              {r.is_source && <Badge tone="neutral">Your link</Badge>}
              <StatusBadge status={r.status} />
              {r.status === "OK" && <MatchBadge match={r.match_class} />}
            </div>
            {r.listing && <p className="text-muted-foreground text-sm">{r.listing.title}</p>}
            {r.status !== "OK" && r.status_reason && (
              <p className="text-muted-foreground text-sm">{r.status_reason}</p>
            )}
          </div>
          {p && p.final_price !== null && (
            <div className="text-right">
              <div className="tabular text-2xl font-semibold tracking-tight">
                {formatINR(p.final_price)}
              </div>
              <div className="text-muted-foreground text-xs">
                {!p.final_price_complete
                  ? "+ unknown fees"
                  : p.final_price_estimated
                    ? "estimated final price"
                    : "final price"}
              </div>
            </div>
          )}
        </div>

        {/* Facts */}
        {r.status === "OK" && (
          <div className="text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 text-sm">
            {r.location_verification && (
              <span
                className={cn(
                  "inline-flex items-center gap-1.5",
                  r.location_verification === "UNAVAILABLE" && "text-destructive",
                )}
              >
                <MapPin className="size-3.5" aria-hidden />
                {LOCATION_TEXT[r.location_verification]}
              </span>
            )}
            {r.eta_text && (
              <span className="inline-flex items-center gap-1.5">
                <Clock className="size-3.5" aria-hidden /> {r.eta_text}
              </span>
            )}
            {r.availability === "OUT_OF_STOCK" && (
              <span className="text-destructive inline-flex items-center gap-1.5">
                <PackageX className="size-3.5" aria-hidden /> Out of stock
              </span>
            )}
          </div>
        )}

        {/* Price breakdown */}
        {p && (
          <details className="group rounded-xl border">
            <summary className="hover:bg-muted/50 cursor-pointer list-none rounded-xl px-4 py-2.5 text-sm font-medium select-none">
              Price breakdown
              <span className="text-muted-foreground ml-1 font-normal group-open:hidden">
                — tap to view
              </span>
            </summary>
            <dl className="tabular grid grid-cols-[1fr_auto] gap-x-6 gap-y-1.5 border-t px-4 py-3 text-sm">
              <dt className="text-muted-foreground">Item price</dt>
              <dd className="text-right">
                {formatINR(p.item_price)}
                {p.mrp && p.item_price && Number(p.mrp) > Number(p.item_price) && (
                  <span className="text-muted-foreground ml-2 text-xs line-through">
                    {formatINR(p.mrp)}
                  </span>
                )}
              </dd>
              {Number(p.verified_discount) > 0 && (
                <>
                  <dt className="text-muted-foreground">Verified discount</dt>
                  <dd className="text-success text-right">−{formatINR(p.verified_discount)}</dd>
                </>
              )}
              {CHARGE_ROWS.map(([key, label]) => {
                const c = p[key] as ChargeView;
                return (
                  <div key={key} className="contents">
                    <dt className="text-muted-foreground">
                      {label}
                      {/* Estimate sources are listed in the notes below the breakdown. */}
                      {c.note && c.status !== "ESTIMATED" && (
                        <span className="text-xs"> · {c.note}</span>
                      )}
                    </dt>
                    <dd
                      className={cn(
                        "text-right",
                        (c.status === "UNKNOWN" || c.status === "ESTIMATED") && "text-warning",
                      )}
                    >
                      {chargeText(c)}
                    </dd>
                  </div>
                );
              })}
              <dt className="border-t pt-1.5 font-medium">
                {!p.final_price_complete
                  ? "Known subtotal"
                  : p.final_price_estimated
                    ? "Estimated final"
                    : "Final payable"}
              </dt>
              <dd className="border-t pt-1.5 text-right font-semibold">
                {formatINR(p.final_price)}
              </dd>
            </dl>
            {p.assumptions.length > 0 && (
              <ul className="text-muted-foreground list-disc space-y-0.5 border-t px-4 py-3 pl-8 text-xs">
                {p.assumptions.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            )}
          </details>
        )}

        {/* Card offers */}
        {r.card_offers.length > 0 && (
          <div className="flex flex-col gap-2 rounded-xl border p-4">
            <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span className="inline-flex items-center gap-1.5 font-medium">
                <CreditCard className="size-4" aria-hidden /> Card offers
              </span>
              {r.price_after_best_card && (
                <span className="tabular">
                  <span className="text-muted-foreground">With best card: </span>
                  <span className="font-semibold">{formatINR(r.price_after_best_card)}</span>
                </span>
              )}
            </div>
            <ul className="flex flex-col gap-1.5 text-sm">
              {r.card_offers.map((c, i) => (
                <li
                  key={`${c.bank}-${i}`}
                  className={cn(
                    "flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5",
                    c.discount === null && "text-muted-foreground",
                  )}
                >
                  <span>
                    {r.best_card && i === 0 && c.discount !== null && (
                      <Badge tone="success" className="mr-2">
                        Best
                      </Badge>
                    )}
                    {c.note}
                    <span className="text-muted-foreground text-xs"> · {cardLabel(c)}</span>
                  </span>
                  <span className="tabular">
                    {c.discount !== null ? `−${formatINR(c.discount)}` : "Not applicable"}
                  </span>
                </li>
              ))}
            </ul>
            <p className="text-muted-foreground text-xs">
              Depends on the card you pay with, so it isn&apos;t included in the final price.
            </p>
          </div>
        )}

        {/* Why not ranked / match reasons / other listings */}
        {r.status === "OK" && (
          <div className="flex flex-col gap-1 text-xs">
            {!r.ranked && r.not_ranked_because.length > 0 && (
              <p className="text-muted-foreground">
                <span className="font-medium">Not in the ranking:</span>{" "}
                {r.not_ranked_because.join(" · ")}
              </p>
            )}
            {r.match_reasons.length > 0 && (
              <p className="text-muted-foreground">
                <span className="font-medium">Match:</span> {r.match_reasons.join(" · ")}
              </p>
            )}
          </div>
        )}
        {r.other_candidates.length > 0 && (
          <details className="text-sm">
            <summary className="text-muted-foreground cursor-pointer select-none">
              {r.other_candidates.length} other listing
              {r.other_candidates.length > 1 ? "s" : ""} on {r.marketplace_name}
            </summary>
            <ul className="mt-2 flex flex-col gap-2">
              {r.other_candidates.map((c) => (
                <li key={c.external_id} className="bg-muted/40 rounded-lg p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span>{c.title}</span>
                    <MatchBadge match={c.match_class} />
                  </div>
                  <p className="text-muted-foreground mt-1 text-xs">
                    {c.match_reasons.join(" · ")}
                    {c.final_price && ` · ${formatINR(c.final_price)}`}
                  </p>
                </li>
              ))}
            </ul>
          </details>
        )}

        {/* Footer */}
        {r.listing && (
          <div className="text-muted-foreground flex flex-wrap items-center justify-between gap-2 border-t pt-3 text-xs">
            <span>
              {r.checked_at &&
                `Checked ${new Date(r.checked_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}`}
              {r.attempts && r.attempts > 2 ? ` · ${r.attempts} attempts` : ""}
            </span>
            {r.listing.url && !demo ? (
              <a
                href={r.listing.url}
                target="_blank"
                rel="noopener noreferrer nofollow sponsored"
                className="text-primary inline-flex items-center gap-1 font-medium hover:underline"
              >
                View product <ExternalLink className="size-3.5" aria-hidden />
              </a>
            ) : (
              <span className="inline-flex items-center gap-1">
                <FlaskConical className="size-3.5" aria-hidden /> Demo listing · no real page
              </span>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
