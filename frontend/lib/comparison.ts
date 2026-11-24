import { apiFetch, type DataMode, type MarketplaceCode } from "@/lib/api";

/** Mirrors backend/app/schemas/comparison.py. Money arrives as decimal strings. */
export type Money = string;
export type MatchClass = "EXACT" | "PROBABLE" | "MISMATCH" | "UNVERIFIED";
export type ComparisonStatus = "PENDING" | "RUNNING" | "COMPLETE" | "PARTIAL" | "FAILED";
export type ResultState =
  "PENDING" | "OK" | "NOT_FOUND" | "FAILED" | "UNSUPPORTED" | "NOT_CONFIGURED";
export type ChargeStatus = "KNOWN" | "ESTIMATED" | "UNKNOWN" | "NOT_APPLICABLE";
export type LocationVerification =
  "VERIFIED" | "UNVERIFIABLE" | "UNAVAILABLE" | "NEEDS_PRECISE_LOCATION";

export interface ListingView {
  marketplace: MarketplaceCode;
  marketplace_name: string;
  external_id: string;
  title: string;
  brand: string | null;
  model: string | null;
  gtin: string | null;
  url: string | null;
  image_url: string | null;
  normalized: {
    size: string | null;
    pack_count: number;
    total: string | null;
    colour: string | null;
    storage_gb: number | null;
    ram_gb: number | null;
    variant_key: string;
    warnings: string[];
  };
}

export interface ChargeView {
  status: ChargeStatus;
  amount: Money | null;
  note: string | null;
}

export interface PriceView {
  item_price: Money | null;
  mrp: Money | null;
  verified_discount: Money;
  delivery_fee: ChargeView;
  handling_fee: ChargeView;
  platform_fee: ChargeView;
  other_fees: ChargeView;
  coupons: { description: string; amount: Money; eligibility: "VERIFIED" | "UNVERIFIED" }[];
  final_price: Money | null;
  final_price_complete: boolean;
  final_price_estimated: boolean;
  assumptions: string[];
}

export interface CardOfferView {
  bank: string;
  card_type: string;
  card_network: string | null;
  kind: "PERCENT" | "FLAT";
  value: Money;
  max_discount: Money | null;
  min_order_value: Money | null;
  emi_only: boolean;
  terms: string | null;
  discount: Money | null;
  note: string;
}

export interface CandidateView {
  external_id: string;
  title: string;
  match_class: MatchClass;
  match_reasons: string[];
  final_price: Money | null;
  final_price_complete: boolean;
}

export interface ResultView {
  marketplace: MarketplaceCode;
  marketplace_name: string;
  status: ResultState;
  status_reason: string | null;
  listing: ListingView | null;
  match_class: MatchClass | null;
  match_score: Money | null;
  match_reasons: string[];
  price: PriceView | null;
  card_offers: CardOfferView[];
  best_card: CardOfferView | null;
  price_after_best_card: Money | null;
  availability: "IN_STOCK" | "OUT_OF_STOCK" | "UNKNOWN";
  location_verification: LocationVerification | null;
  eta_text: string | null;
  other_candidates: CandidateView[];
  is_source: boolean;
  ranked: boolean;
  rank: number | null;
  delivery_verified: boolean;
  price_verified: boolean;
  is_cheapest: boolean;
  not_ranked_because: string[];
  attempts: number | null;
  latency_ms: number | null;
  checked_at: string | null;
}

interface PlaceView {
  marketplace: MarketplaceCode;
  marketplace_name: string;
  final_price: Money;
  caveats: string[];
}

export interface LocationView {
  postal_region: string;
  directory_status: "VERIFIED" | "NOT_FOUND" | "UNAVAILABLE";
  district: string | null;
  state: string | null;
  division: string | null;
  circle: string | null;
}

export interface ComparisonView {
  id: string;
  status: ComparisonStatus;
  data_mode: DataMode;
  pincode: string;
  location: LocationView | null;
  source_url: string;
  created_at: string;
  completed_at: string | null;
  source: ListingView;
  results: ResultView[];
  summary: {
    cheapest: PlaceView | null;
    cheaper_unverified: PlaceView | null;
    source_final_price: Money | null;
    savings_vs_source: Money | null;
    best_with_card: {
      marketplace: MarketplaceCode;
      marketplace_name: string;
      price_after_card: Money;
      final_price: Money;
      discount: Money;
      card: string;
      delivery_verified: boolean;
      price_verified: boolean;
    } | null;
    exact_matches: number;
    probable_matches: number;
    marketplaces_checked: number;
    marketplaces_failed: number;
  };
  reused: boolean;
  storage_note: string | null;
}

export interface DemoProduct {
  key: string;
  title: string;
  marketplace: MarketplaceCode;
  url: string;
}

export const FINAL_STATUSES: ComparisonStatus[] = ["COMPLETE", "PARTIAL", "FAILED"];

export function startComparison(url: string, pincode: string): Promise<ComparisonView> {
  return apiFetch<ComparisonView>("/api/v1/comparisons", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, pincode }),
    cache: "no-store",
    timeoutMs: 20000,
  });
}

export function getComparison(id: string, signal?: AbortSignal): Promise<ComparisonView> {
  return apiFetch<ComparisonView>(`/api/v1/comparisons/${encodeURIComponent(id)}`, {
    cache: "no-store",
    signal,
  });
}

export function getDemoProducts(): Promise<DemoProduct[]> {
  return apiFetch<DemoProduct[]>("/api/v1/demo/products", { cache: "no-store" });
}

const WHOLE = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});
const PAISE = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** ₹14,999 for whole rupees, ₹1,499.90 when there are paise. */
export function formatINR(value: Money | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  return Number.isInteger(n) ? WHOLE.format(n) : PAISE.format(n);
}
