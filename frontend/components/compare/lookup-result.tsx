import { CheckCircle2, ExternalLink, Info, MapPin, PackageSearch } from "lucide-react";

import type { LookupResult as LookupResultData } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";

const ID_LABELS: Record<string, string> = {
  ASIN: "ASIN",
  FSN: "Flipkart FSN",
  FLIPKART_ITEM: "Flipkart item ID",
  BIGBASKET_ID: "BigBasket product ID",
  BLINKIT_PRID: "Blinkit product ID",
  ZEPTO_PVID: "Zepto product ID",
};

export function LookupResult({ result }: { result: LookupResultData }) {
  const { product, location } = result;
  const verified = location.directory_status === "VERIFIED";

  return (
    <section
      aria-live="polite"
      aria-label="Check result"
      className="animate-in fade-in slide-in-from-bottom-1 grid gap-4 duration-200"
    >
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardContent className="flex flex-col gap-3">
            <div className="text-muted-foreground flex items-center gap-2 text-xs font-medium tracking-wide uppercase">
              <PackageSearch className="size-4" aria-hidden /> Product link
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-lg font-semibold">{product.marketplace_name}</span>
              <Badge tone="success">
                <CheckCircle2 aria-hidden /> Recognised
              </Badge>
            </div>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
              <dt className="text-muted-foreground">{ID_LABELS[product.id_type] ?? "ID"}</dt>
              <dd className="tabular font-mono break-all">{product.external_id}</dd>
              {product.resolved_from && (
                <>
                  <dt className="text-muted-foreground">Short link</dt>
                  <dd className="text-muted-foreground break-all">{product.resolved_from}</dd>
                </>
              )}
            </dl>
            <a
              href={product.canonical_url}
              target="_blank"
              rel="noopener noreferrer nofollow"
              className="text-primary inline-flex w-fit items-center gap-1 text-sm font-medium underline-offset-4 hover:underline"
            >
              Open on {product.marketplace_name} <ExternalLink className="size-3.5" aria-hidden />
            </a>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="flex flex-col gap-3">
            <div className="text-muted-foreground flex items-center gap-2 text-xs font-medium tracking-wide uppercase">
              <MapPin className="size-4" aria-hidden /> Delivery location
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="tabular text-lg font-semibold">{location.pincode}</span>
              {verified ? (
                <Badge tone="success">
                  <CheckCircle2 aria-hidden /> Found in India Post directory
                </Badge>
              ) : (
                <Badge tone="warning">Format checked only</Badge>
              )}
            </div>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
              {verified && (
                <>
                  <dt className="text-muted-foreground">Area</dt>
                  <dd>
                    {location.district}, {location.state}
                  </dd>
                </>
              )}
              <dt className="text-muted-foreground">Postal region</dt>
              <dd>{location.postal_region}</dd>
            </dl>
            {!verified && (
              <p className="text-muted-foreground text-sm">
                The India Post directory isn&apos;t loaded yet, so we haven&apos;t confirmed this
                PIN code exists.
              </p>
            )}
            <p className="text-muted-foreground text-xs">{location.delivery_note}</p>
          </CardContent>
        </Card>
      </div>

      <div className="bg-info-soft flex gap-3 rounded-xl border p-4 text-sm">
        <Info className="text-primary mt-0.5 size-4 shrink-0" aria-hidden />
        <p>
          <span className="font-medium">Price comparison isn&apos;t available yet.</span>{" "}
          <span className="text-muted-foreground">
            {product.resolved_from
              ? "We only followed your short link's redirect to find the product page. No product page was opened and no prices were looked up."
              : "This check only read your link and PIN code. No marketplace was contacted and no prices were looked up."}
          </span>
        </p>
      </div>
    </section>
  );
}
