import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ExternalLink, FlaskConical, LineChart } from "lucide-react";

import { PriceHistoryChart } from "@/components/charts/price-history-chart";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { ApiError } from "@/lib/api";
import { formatINR } from "@/lib/comparison";
import { getProduct, type ProductView } from "@/lib/products";

async function load(slug: string): Promise<ProductView> {
  try {
    return await getProduct(slug);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
    throw err;
  }
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const p = await load(slug);
  const variant = [p.variant.size, p.variant.colour].filter(Boolean).join(", ");
  return {
    title: p.title,
    description: `Compare the exact ${p.title}${variant ? ` (${variant})` : ""} across Indian marketplaces, with delivery and platform fees shown openly.`,
    alternates: { canonical: `/products/${p.slug}` },
    // Demo-only products must never be indexed: their prices are fictional.
    robots: p.indexable ? undefined : { index: false, follow: false },
  };
}

const DATE = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric" });

export default async function ProductPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const p = await load(slug);
  const v = p.variant;
  const chips = [
    v.size && `${v.size}${v.pack_count > 1 ? ` × ${v.pack_count}` : ""}`,
    v.colour,
    v.ram_gb && `${v.ram_gb} GB RAM`,
    v.storage_gb && `${v.storage_gb} GB`,
  ].filter(Boolean) as string[];

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6 px-4 py-8 sm:px-6 sm:py-12">
      <nav aria-label="Breadcrumb" className="text-muted-foreground text-sm">
        <Link href="/" className="hover:text-foreground">
          Home
        </Link>
        {p.category && p.category_slug && (
          <>
            {" / "}
            <Link href={`/categories/${p.category_slug}`} className="hover:text-foreground">
              {p.category}
            </Link>
          </>
        )}
      </nav>

      <header className="flex flex-col gap-3">
        {p.brand && <p className="text-muted-foreground text-sm">{p.brand}</p>}
        <h1 className="text-2xl font-semibold tracking-tight text-balance sm:text-3xl">
          {p.title}
        </h1>
        <div className="flex flex-wrap gap-2">
          {chips.map((c) => (
            <Badge key={c} tone="neutral" className="capitalize">
              {c}
            </Badge>
          ))}
          {p.data_mode === "DEMO" && (
            <Badge tone="warning">
              <FlaskConical aria-hidden /> Demo data
            </Badge>
          )}
        </div>
      </header>

      <section aria-labelledby="listings-heading" className="flex flex-col gap-3">
        <h2 id="listings-heading" className="font-semibold">
          Last checked prices
        </h2>
        <div className="grid gap-3 sm:grid-cols-2">
          {p.listings.map((l) => (
            <Card key={l.marketplace}>
              <CardContent className="flex flex-col gap-1.5">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="font-medium">{l.marketplace_name}</span>
                  {l.latest?.final_price && (
                    <span className="tabular text-lg font-semibold">
                      {formatINR(l.latest.final_price)}
                    </span>
                  )}
                </div>
                <p className="text-muted-foreground text-sm">{l.title}</p>
                {l.latest ? (
                  <p className="text-muted-foreground text-xs">
                    {!l.latest.final_price_complete
                      ? "Known subtotal (some fees unknown)"
                      : l.latest.final_price_estimated
                        ? "Estimated final price (includes a published-policy fee)"
                        : "Final price"}
                    {l.latest.pincode && ` for PIN ${l.latest.pincode}`} ·{" "}
                    {DATE.format(new Date(l.latest.observed_at))}
                  </p>
                ) : (
                  <p className="text-muted-foreground text-xs">No price recorded yet.</p>
                )}
                {l.url && (
                  <a
                    href={l.url}
                    target="_blank"
                    rel="noopener noreferrer nofollow sponsored"
                    className="text-primary inline-flex w-fit items-center gap-1 text-sm font-medium hover:underline"
                  >
                    View product <ExternalLink className="size-3.5" aria-hidden />
                  </a>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
        <p className="text-muted-foreground text-xs">
          Prices are specific to the PIN code and time they were checked. Compare again for your own
          PIN code.
        </p>
      </section>

      <section
        aria-labelledby="history-heading"
        className="bg-card flex flex-col gap-3 rounded-2xl border p-5"
      >
        <h2 id="history-heading" className="inline-flex items-center gap-2 font-semibold">
          <LineChart className="size-4" aria-hidden /> Price history (all PIN codes, last 90 days)
        </h2>
        <PriceHistoryChart slug={p.slug} />
      </section>
    </div>
  );
}
