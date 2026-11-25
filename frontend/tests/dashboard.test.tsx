import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { PriceHistoryChart } from "@/components/charts/price-history-chart";
import { applyFilters, DEFAULT_FILTERS } from "@/components/compare/dashboard-controls";
import { ComparisonView } from "@/components/compare/comparison-view";
import type { ComparisonView as Comparison, ResultView } from "@/lib/comparison";
import type { PriceHistoryView } from "@/lib/products";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

function result(over: Partial<ResultView>): ResultView {
  return {
    marketplace: "AMAZON_IN",
    marketplace_name: "Amazon India",
    status: "OK",
    status_reason: null,
    listing: null,
    match_class: "EXACT",
    match_score: "1.000",
    match_reasons: [],
    price: null,
    card_offers: [],
    best_card: null,
    price_after_best_card: null,
    availability: "IN_STOCK",
    location_verification: "VERIFIED",
    eta_text: null,
    other_candidates: [],
    is_source: false,
    ranked: true,
    rank: 1,
    delivery_verified: true,
    price_verified: true,
    is_cheapest: false,
    not_ranked_because: [],
    attempts: 1,
    latency_ms: 100,
    checked_at: null,
    ...over,
  };
}

const priced = (final: string) => ({
  item_price: final,
  mrp: null,
  verified_discount: "0.00",
  delivery_fee: { status: "KNOWN" as const, amount: "0.00", note: null },
  handling_fee: { status: "NOT_APPLICABLE" as const, amount: null, note: null },
  platform_fee: { status: "NOT_APPLICABLE" as const, amount: null, note: null },
  other_fees: { status: "NOT_APPLICABLE" as const, amount: null, note: null },
  coupons: [],
  final_price: final,
  final_price_complete: true,
  final_price_estimated: false,
  assumptions: [],
});

const RESULTS: ResultView[] = [
  result({ marketplace: "AMAZON_IN", marketplace_name: "Amazon India", price: priced("300.00") }),
  result({
    marketplace: "FLIPKART",
    marketplace_name: "Flipkart",
    price: priced("280.00"),
    price_after_best_card: "250.00",
    match_class: "PROBABLE",
  }),
  result({
    marketplace: "BIGBASKET",
    marketplace_name: "BigBasket",
    price: priced("260.00"),
    availability: "OUT_OF_STOCK",
  }),
  result({
    marketplace: "ZEPTO",
    marketplace_name: "Zepto",
    status: "FAILED",
    status_reason: "Took too long to respond",
    match_class: null,
    availability: "UNKNOWN",
    ranked: false,
    rank: null,
  }),
];

describe("applyFilters", () => {
  const names = (rs: ResultView[]) => rs.map((r) => r.marketplace);

  it("keeps server order by default", () => {
    expect(names(applyFilters(RESULTS, DEFAULT_FILTERS))).toEqual([
      "AMAZON_IN",
      "FLIPKART",
      "BIGBASKET",
      "ZEPTO",
    ]);
  });

  it("filters by match, stock and marketplace", () => {
    expect(names(applyFilters(RESULTS, { ...DEFAULT_FILTERS, match: "exact" }))).toEqual([
      "AMAZON_IN",
      "BIGBASKET",
    ]);
    expect(names(applyFilters(RESULTS, { ...DEFAULT_FILTERS, match: "probable" }))).toEqual([
      "FLIPKART",
    ]);
    expect(names(applyFilters(RESULTS, { ...DEFAULT_FILTERS, inStockOnly: true }))).toEqual([
      "AMAZON_IN",
      "FLIPKART",
    ]);
    expect(
      names(applyFilters(RESULTS, { ...DEFAULT_FILTERS, hidden: ["ZEPTO", "AMAZON_IN"] })),
    ).toEqual(["FLIPKART", "BIGBASKET"]);
  });

  it("sorts by final price or price with card, unpriced last", () => {
    expect(names(applyFilters(RESULTS, { ...DEFAULT_FILTERS, sort: "price" }))).toEqual([
      "BIGBASKET",
      "FLIPKART",
      "AMAZON_IN",
      "ZEPTO",
    ]);
    expect(names(applyFilters(RESULTS, { ...DEFAULT_FILTERS, sort: "card" }))[0]).toBe("FLIPKART");
  });
});

const VIEW: Comparison = {
  id: "c1",
  status: "PARTIAL",
  data_mode: "DEMO",
  pincode: "560001",
  location: null,
  source_url: "https://www.amazon.in/dp/DEMO000001",
  created_at: "2026-11-24T07:00:00Z",
  completed_at: "2026-11-24T07:00:02Z",
  source: {
    marketplace: "AMAZON_IN",
    marketplace_name: "Amazon India",
    external_id: "DEMO000001",
    title: "Saltwise Iodised Salt, 1 kg",
    brand: "Saltwise",
    model: null,
    gtin: null,
    url: null,
    image_url: null,
    normalized: {
      size: "1000g",
      pack_count: 1,
      total: "1000g",
      colour: null,
      storage_gb: null,
      ram_gb: null,
      variant_key: "1000g|x1|-|-|-",
      warnings: [],
    },
  },
  results: RESULTS,
  summary: {
    cheapest: null,
    cheaper_unverified: null,
    source_final_price: null,
    savings_vs_source: null,
    best_with_card: null,
    exact_matches: 2,
    probable_matches: 1,
    marketplaces_checked: 3,
    marketplaces_failed: 1,
  },
  reused: false,
  storage_note: null,
  product_slug: null,
};

function routeFetch(routes: Record<string, (init?: RequestInit) => unknown>) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const key = Object.keys(routes).find((k) => url.includes(k));
    const body = key ? routes[key]!(init) : { marketplaces: [] };
    return new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });
  });
}

describe("ComparisonView dashboard", () => {
  it("filters results and can reset", async () => {
    routeFetch({ "/comparisons/c1": () => VIEW });
    render(<ComparisonView id="c1" />);
    const user = userEvent.setup();
    await screen.findByRole("heading", { name: "Zepto" });

    await user.click(screen.getByRole("button", { name: "Exact only" }));
    expect(screen.queryByRole("heading", { name: "Flipkart" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Zepto" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Amazon India" }));
    await user.click(screen.getByRole("button", { name: "BigBasket" }));
    expect(screen.getByText("No results match these filters.")).toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "Reset filters" })[0]!);
    expect(await screen.findByRole("heading", { name: "Flipkart" })).toBeInTheDocument();
  });

  it("retries one failed marketplace and resumes polling", async () => {
    const running = {
      ...VIEW,
      status: "RUNNING",
      results: RESULTS.map((r) => (r.marketplace === "ZEPTO" ? { ...r, status: "PENDING" } : r)),
    };
    const recovered = {
      ...VIEW,
      status: "COMPLETE",
      results: RESULTS.map((r) =>
        r.marketplace === "ZEPTO" ? { ...r, status: "NOT_FOUND", status_reason: null } : r,
      ),
      summary: { ...VIEW.summary, marketplaces_failed: 0 },
    };
    let retried = false;
    const spy = routeFetch({
      "/retry": () => {
        retried = true;
        return running;
      },
      "/comparisons/c1": () => (retried ? recovered : VIEW),
    });
    render(<ComparisonView id="c1" />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Retry Zepto" }));

    const call = spy.mock.calls.find(([u]) => String(u).endsWith("/retry"));
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({ marketplaces: ["ZEPTO"] });
    expect(await screen.findByText("All marketplaces checked.")).toBeInTheDocument();
    const zepto = screen.getByRole("heading", { name: "Zepto" }).closest("[data-slot=card]");
    expect(within(zepto as HTMLElement).getByText("Not sold here")).toBeInTheDocument();
  });

  it("refresh opens the new comparison", async () => {
    routeFetch({ "/refresh": () => ({ ...VIEW, id: "c2" }), "/comparisons/c1": () => VIEW });
    render(<ComparisonView id="c1" />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /refresh prices/i }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/compare/c2"));
  });

  it("shows where each marketplace's data comes from", async () => {
    routeFetch({
      "/comparisons/c1": () => VIEW,
      "/marketplaces": () => ({
        data_mode: "DEMO",
        marketplaces: RESULTS.map((r) => ({
          marketplace: r.marketplace,
          marketplace_name: r.marketplace_name,
          state: "DEMO",
          reason: "Demo mode",
        })),
      }),
    });
    render(<ComparisonView id="c1" />);
    const user = userEvent.setup();
    await user.click(await screen.findByText("Data sources"));
    const table = screen.getByRole("table", { name: /data source and check status/i });
    expect((await within(table).findAllByText("Demo data")).length).toBe(4);
    expect(within(table).getByText(/Took too long to respond/)).toBeInTheDocument();
  });
});

describe("PriceHistoryChart", () => {
  const history: PriceHistoryView = {
    product_slug: "saltwise",
    pincode: "560001",
    days: 90,
    data_mode: "DEMO",
    series: [
      {
        marketplace: "AMAZON_IN",
        marketplace_name: "Amazon India",
        points: [
          {
            observed_at: "2026-11-20T10:00:00Z",
            pincode: "560001",
            item_price: "28.00",
            final_price: "28.00",
            final_price_complete: true,
          },
          {
            observed_at: "2026-11-24T10:00:00Z",
            pincode: "560001",
            item_price: "27.00",
            final_price: "27.00",
            final_price_complete: true,
          },
        ],
      },
      {
        marketplace: "FLIPKART",
        marketplace_name: "Flipkart",
        points: [
          {
            observed_at: "2026-11-24T10:00:10Z",
            pincode: "560001",
            item_price: "27.00",
            final_price: "30.00",
            final_price_complete: false, // incomplete prices are gaps, never plotted
          },
          {
            observed_at: "2026-11-24T11:00:00Z",
            pincode: "560001",
            item_price: "27.00",
            final_price: "70.00",
            final_price_complete: true,
            final_price_estimated: true, // estimated fees are gaps too
          },
        ],
      },
    ],
  };

  it("has a legend and an accessible table view; incomplete prices are left out", async () => {
    const spy = routeFetch({ "/price-history": () => history });
    render(<PriceHistoryChart slug="saltwise" pincode="560001" />);
    const user = userEvent.setup();
    expect(await screen.findByRole("list", { name: "Marketplaces" })).toHaveTextContent(
      "Amazon India",
    );
    expect(String(spy.mock.calls[0]![0])).toContain("pincode=560001");
    await user.click(screen.getByRole("button", { name: "Show as table" }));
    const table = screen.getByRole("table");
    expect(within(table).getByText("₹27")).toBeInTheDocument();
    expect(within(table).queryByText("₹30")).not.toBeInTheDocument();
    expect(within(table).queryByText("₹70")).not.toBeInTheDocument();
    expect(screen.getByText(/Demo data: these are not real prices/)).toBeInTheDocument();
  });
});
