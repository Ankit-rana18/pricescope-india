"use client";

import { Button } from "@/components/ui/button";
import type { MarketplaceCode } from "@/lib/api";
import type { ResultView } from "@/lib/comparison";
import { cn } from "@/lib/utils";

export type MatchFilter = "all" | "exact" | "probable";
export type SortKey = "rank" | "price" | "card";

export interface Filters {
  match: MatchFilter;
  inStockOnly: boolean;
  hidden: MarketplaceCode[];
  sort: SortKey;
}

export const DEFAULT_FILTERS: Filters = {
  match: "all",
  inStockOnly: false,
  hidden: [],
  sort: "rank",
};

const MAX = Number.MAX_SAFE_INTEGER;

function price(r: ResultView): number {
  return r.price?.final_price != null ? Number(r.price.final_price) : MAX;
}

export function applyFilters(results: ResultView[], f: Filters): ResultView[] {
  const kept = results.filter((r) => {
    if (f.hidden.includes(r.marketplace)) return false;
    if (f.inStockOnly && r.availability !== "IN_STOCK") return false;
    if (f.match === "exact" && r.match_class !== "EXACT") return false;
    if (
      f.match === "probable" &&
      r.match_class !== "PROBABLE" &&
      !r.other_candidates.some((c) => c.match_class === "PROBABLE")
    )
      return false;
    return true;
  });
  if (f.sort === "rank") return kept; // server order: verified ranking first
  const key =
    f.sort === "price"
      ? price
      : (r: ResultView) =>
          r.price_after_best_card != null ? Number(r.price_after_best_card) : price(r);
  return [...kept].sort((a, b) => key(a) - key(b));
}

function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
        "focus-visible:ring-ring/40 outline-none focus-visible:ring-[3px]",
        active ? "border-primary bg-accent text-accent-foreground" : "bg-card hover:bg-muted",
      )}
    >
      {children}
    </button>
  );
}

export function DashboardControls({
  results,
  filters,
  onChange,
}: {
  results: ResultView[];
  filters: Filters;
  onChange: (f: Filters) => void;
}) {
  const set = (patch: Partial<Filters>) => onChange({ ...filters, ...patch });
  const toggleMarketplace = (m: MarketplaceCode) =>
    set({
      hidden: filters.hidden.includes(m)
        ? filters.hidden.filter((x) => x !== m)
        : [...filters.hidden, m],
    });
  const changed = JSON.stringify(filters) !== JSON.stringify(DEFAULT_FILTERS);

  return (
    <div className="flex flex-col gap-3" role="group" aria-label="Filter and sort results">
      <div className="flex flex-wrap items-center gap-2">
        <Chip active={filters.match === "all"} onClick={() => set({ match: "all" })}>
          All matches
        </Chip>
        <Chip active={filters.match === "exact"} onClick={() => set({ match: "exact" })}>
          Exact only
        </Chip>
        <Chip active={filters.match === "probable"} onClick={() => set({ match: "probable" })}>
          Probable
        </Chip>
        <span className="bg-border mx-1 h-4 w-px" aria-hidden />
        <Chip
          active={filters.inStockOnly}
          onClick={() => set({ inStockOnly: !filters.inStockOnly })}
        >
          In stock
        </Chip>
        <span className="bg-border mx-1 h-4 w-px" aria-hidden />
        {results.map((r) => (
          <Chip
            key={r.marketplace}
            active={!filters.hidden.includes(r.marketplace)}
            onClick={() => toggleMarketplace(r.marketplace)}
          >
            {r.marketplace_name}
          </Chip>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <label className="text-muted-foreground inline-flex items-center gap-2">
          Sort by
          <select
            value={filters.sort}
            onChange={(e) => set({ sort: e.target.value as SortKey })}
            className="bg-card text-foreground focus-visible:ring-ring/40 rounded-md border px-2 py-1 text-sm outline-none focus-visible:ring-[3px]"
          >
            <option value="rank">Verified ranking</option>
            <option value="price">Final price</option>
            <option value="card">Price with best card</option>
          </select>
        </label>
        {changed && (
          <Button
            variant="link"
            size="sm"
            className="h-auto px-0"
            onClick={() => onChange(DEFAULT_FILTERS)}
          >
            Reset filters
          </Button>
        )}
      </div>
    </div>
  );
}
