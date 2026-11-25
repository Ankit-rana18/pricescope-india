import { apiFetch, type DataMode, type MarketplaceCode } from "@/lib/api";
import type { Money } from "@/lib/comparison";

/** Mirrors backend/app/schemas/products.py. */
export interface PricePoint {
  observed_at: string;
  pincode: string | null;
  item_price: Money | null;
  final_price: Money | null;
  final_price_complete: boolean;
  final_price_estimated?: boolean;
}

export interface ProductView {
  slug: string;
  title: string;
  brand: string | null;
  model: string | null;
  category: string | null;
  category_slug: string | null;
  data_mode: DataMode;
  indexable: boolean;
  variant: {
    size: string | null;
    pack_count: number;
    colour: string | null;
    storage_gb: number | null;
    ram_gb: number | null;
  };
  identifiers: { type: string; value: string }[];
  listings: {
    marketplace: MarketplaceCode;
    marketplace_name: string;
    title: string;
    url: string | null;
    latest: PricePoint | null;
  }[];
}

export interface PriceHistoryView {
  product_slug: string;
  pincode: string | null;
  days: number;
  data_mode: DataMode;
  series: { marketplace: MarketplaceCode; marketplace_name: string; points: PricePoint[] }[];
}

export interface CategoryView {
  slug: string;
  name: string;
  product_count: number;
  indexable: boolean;
}

export interface CategoryProductsView {
  category: CategoryView;
  products: { slug: string; title: string; brand: string | null; indexable: boolean }[];
  next_cursor: string | null;
}

/** Fixed colour per marketplace: colour follows the entity, never its rank. */
export const SERIES_COLOR: Record<MarketplaceCode, string> = {
  AMAZON_IN: "var(--series-amazon)",
  FLIPKART: "var(--series-flipkart)",
  BLINKIT: "var(--series-blinkit)",
  ZEPTO: "var(--series-zepto)",
  BIGBASKET: "var(--series-bigbasket)",
};

const enc = encodeURIComponent;

export function getProduct(slug: string, init?: RequestInit): Promise<ProductView> {
  return apiFetch<ProductView>(`/api/v1/products/${enc(slug)}`, { cache: "no-store", ...init });
}

export function getPriceHistory(
  slug: string,
  opts: { pincode?: string | null; days?: number } = {},
): Promise<PriceHistoryView> {
  const q = new URLSearchParams({ days: String(opts.days ?? 90) });
  if (opts.pincode) q.set("pincode", opts.pincode);
  return apiFetch<PriceHistoryView>(`/api/v1/products/${enc(slug)}/price-history?${q}`, {
    cache: "no-store",
  });
}

export function getCategoryProducts(
  slug: string,
  cursor?: string | null,
): Promise<CategoryProductsView> {
  const q = cursor ? `?cursor=${enc(cursor)}` : "";
  return apiFetch<CategoryProductsView>(`/api/v1/categories/${enc(slug)}/products${q}`, {
    cache: "no-store",
  });
}

export function getSitemapEntries(): Promise<{
  entries: { path: string; lastmod: string | null }[];
}> {
  return apiFetch("/api/v1/seo/sitemap", { next: { revalidate: 3600 } });
}
