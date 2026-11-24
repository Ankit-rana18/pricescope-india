import { render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ComparisonView } from "@/components/compare/comparison-view";
import {
  formatINR,
  type ChargeStatus,
  type ComparisonView as Comparison,
  type ResultView,
} from "@/lib/comparison";

const charge = (
  amount: string | null,
  status: ChargeStatus = amount === null ? "UNKNOWN" : "KNOWN",
) => ({ status, amount, note: null });

const listing = (marketplace: ResultView["marketplace"], name: string) => ({
  marketplace,
  marketplace_name: name,
  external_id: "X",
  title: "Nimbus X2 5G (Midnight Black, 128 GB)",
  brand: "Nimbus",
  model: null,
  gtin: null,
  url: null,
  image_url: null,
  normalized: {
    size: null,
    pack_count: 1,
    total: null,
    colour: "midnight black",
    storage_gb: 128,
    ram_gb: 8,
    variant_key: "k",
    warnings: [],
  },
});

const base: Omit<ResultView, "marketplace" | "marketplace_name"> = {
  status: "OK",
  status_reason: null,
  listing: null,
  match_class: "EXACT",
  match_score: "1.000",
  match_reasons: ["barcode matches"],
  price: null,
  card_offers: [],
  best_card: null,
  price_after_best_card: null,
  availability: "IN_STOCK",
  location_verification: "VERIFIED",
  eta_text: "Tomorrow",
  other_candidates: [],
  is_source: false,
  ranked: true,
  rank: 1,
  delivery_verified: true,
  price_verified: true,
  is_cheapest: false,
  not_ranked_because: [],
  attempts: 1,
  latency_ms: 10,
  checked_at: "2026-11-24T07:00:00Z",
};

const bestCard = {
  bank: "Demo Bank A",
  card_type: "CREDIT",
  card_network: null,
  kind: "PERCENT" as const,
  value: "10",
  max_discount: "1500",
  min_order_value: "5000",
  emi_only: false,
  terms: null,
  discount: "1499.90",
  note: "Demo Bank A credit card",
};

const COMPARISON: Comparison = {
  id: "c1",
  status: "PARTIAL",
  data_mode: "DEMO",
  pincode: "560001",
  source_url: "https://www.amazon.in/dp/DEMO000003",
  created_at: "2026-11-24T07:00:00Z",
  completed_at: "2026-11-24T07:00:02Z",
  source: listing("AMAZON_IN", "Amazon India"),
  reused: false,
  storage_note: null,
  location: null,
  summary: {
    cheapest: {
      marketplace: "AMAZON_IN",
      marketplace_name: "Amazon India",
      final_price: "14999.00",
      caveats: [],
    },
    cheaper_unverified: {
      marketplace: "FLIPKART",
      marketplace_name: "Flipkart",
      final_price: "14008.00",
      caveats: ["delivery to your PIN code can't be verified"],
    },
    source_final_price: "14999.00",
    savings_vs_source: "0.00",
    best_with_card: {
      marketplace: "AMAZON_IN",
      marketplace_name: "Amazon India",
      price_after_card: "13499.10",
      final_price: "14999.00",
      discount: "1499.90",
      card: "Demo Bank A credit card",
      delivery_verified: true,
      price_verified: true,
    },
    exact_matches: 2,
    probable_matches: 0,
    marketplaces_checked: 4,
    marketplaces_failed: 1,
  },
  results: [
    {
      ...base,
      marketplace: "AMAZON_IN",
      marketplace_name: "Amazon India",
      listing: listing("AMAZON_IN", "Amazon India"),
      is_source: true,
      is_cheapest: true,
      price: {
        item_price: "14999.00",
        mrp: "17999.00",
        verified_discount: "0.00",
        delivery_fee: charge("0.00"),
        handling_fee: charge(null, "NOT_APPLICABLE"),
        platform_fee: charge(null, "NOT_APPLICABLE"),
        other_fees: charge(null, "NOT_APPLICABLE"),
        coupons: [],
        final_price: "14999.00",
        final_price_complete: true,
        final_price_estimated: false,
        assumptions: ["Card offers depend on your card and are not included in the price"],
      },
      card_offers: [bestCard],
      best_card: bestCard,
      price_after_best_card: "13499.10",
    },
    {
      ...base,
      marketplace: "BIGBASKET",
      marketplace_name: "BigBasket",
      listing: listing("BIGBASKET", "BigBasket"),
      ranked: false,
      rank: null,
      not_ranked_because: ["some fees are unknown"],
      price: {
        item_price: "14100.00",
        mrp: null,
        verified_discount: "0.00",
        delivery_fee: charge(null),
        handling_fee: charge("0.00"),
        platform_fee: charge("0.00"),
        other_fees: charge("0.00"),
        coupons: [],
        final_price: "14100.00",
        final_price_complete: false,
        final_price_estimated: false,
        assumptions: [],
      },
    },
    {
      ...base,
      marketplace: "ZEPTO",
      marketplace_name: "Zepto",
      status: "FAILED",
      status_reason: "Took too long to respond",
      match_class: null,
      ranked: false,
      rank: null,
    },
  ],
};

function mockComparison(c: Comparison) {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify(c), { headers: { "Content-Type": "application/json" } }),
  );
}

describe("formatINR", () => {
  it("shows paise only when present", () => {
    expect(formatINR("14999.00")).toBe("₹14,999");
    expect(formatINR("1499.9")).toBe("₹1,499.90");
    expect(formatINR(null)).toBe("—");
  });
});

describe("ComparisonView", () => {
  it("shows the cheapest verified option, the card option and honest caveats", async () => {
    mockComparison(COMPARISON);
    render(<ComparisonView id="c1" />);

    expect((await screen.findAllByText("Cheapest verified")).length).toBe(2); // summary + badge
    expect(
      screen.getByText(/Flipkart shows ₹14,008, but delivery to your PIN code can't be verified/),
    ).toBeInTheDocument();
    expect(screen.getAllByText("₹13,499.10").length).toBe(2); // summary + card
    expect(screen.getByText(/Only if you pay with that card/)).toBeInTheDocument();
    expect(screen.getByText(/1 marketplace couldn't be checked/)).toBeInTheDocument();
    expect(screen.getByText("Demo data")).toBeInTheDocument();
  });

  it("marks unknown fees and never links demo listings", async () => {
    mockComparison(COMPARISON);
    render(<ComparisonView id="c1" />);
    const bigbasket = (await screen.findByRole("heading", { name: "BigBasket" })).closest(
      "[data-slot=card]",
    ) as HTMLElement;
    expect(within(bigbasket).getByText("+ unknown fees")).toBeInTheDocument();
    expect(within(bigbasket).getByText(/some fees are unknown/)).toBeInTheDocument();
    expect(within(bigbasket).getByText("Unknown")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /view product/i })).not.toBeInTheDocument();
    expect(screen.getAllByText(/Demo listing · no real page/).length).toBeGreaterThan(0);
  });

  it("shows failed marketplaces with the reason", async () => {
    mockComparison(COMPARISON);
    render(<ComparisonView id="c1" />);
    expect(await screen.findByText("Check failed")).toBeInTheDocument();
    expect(screen.getByText("Took too long to respond")).toBeInTheDocument();
  });

  it("keeps polling while marketplaces are still answering", async () => {
    const running: Comparison = {
      ...COMPARISON,
      status: "RUNNING",
      completed_at: null,
      results: COMPARISON.results.map((r) =>
        r.marketplace === "ZEPTO" ? { ...r, status: "PENDING" as const } : r,
      ),
    };
    const spy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify(running)))
      .mockResolvedValue(new Response(JSON.stringify(COMPARISON)));
    render(<ComparisonView id="c1" />);
    expect(await screen.findByText(/Checking marketplaces… 4 of 5 answered/)).toBeInTheDocument();
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2), { timeout: 3000 });
    expect(await screen.findByText(/1 marketplace couldn't be checked/)).toBeInTheDocument();
  });

  it("shows a not-found message", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ error: { code: "not_found", message: "Comparison not found." } }),
        {
          status: 404,
        },
      ),
    );
    render(<ComparisonView id="nope" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Comparison not found.");
  });

  it("shows estimated fees as estimates and the PIN area", async () => {
    const amazon = COMPARISON.results[0]!;
    const estimated: Comparison = {
      ...COMPARISON,
      location: {
        postal_region: "Southern",
        directory_status: "VERIFIED",
        district: "Bengaluru Urban",
        state: "Karnataka",
        division: null,
        circle: "Karnataka Circle",
      },
      results: [
        {
          ...amazon,
          price_verified: false,
          price: {
            ...amazon.price!,
            delivery_fee: {
              status: "ESTIMATED",
              amount: "40.00",
              note: "Estimated delivery ₹40 per published policy; not confirmed for your cart",
            },
            final_price_estimated: true,
            assumptions: [
              "Estimated delivery ₹40 per published policy; not confirmed for your cart",
            ],
          },
        },
      ],
    };
    mockComparison(estimated);
    render(<ComparisonView id="c1" />);
    expect(await screen.findByText("estimated final price")).toBeInTheDocument();
    expect(screen.getByText("≈ ₹40")).toBeInTheDocument();
    expect(
      screen.getByText(/per published policy; not confirmed for your cart/),
    ).toBeInTheDocument();
    expect(screen.getByText("· Bengaluru Urban, Karnataka")).toBeInTheDocument();
  });

  it("falls back to the postal circle when the directory has no district", async () => {
    mockComparison({
      ...COMPARISON,
      location: {
        postal_region: "Southern",
        directory_status: "VERIFIED",
        district: null,
        state: null,
        division: "Bangalore GPO Division",
        circle: "Karnataka Circle",
      },
    });
    render(<ComparisonView id="c1" />);
    expect(await screen.findByText("· Karnataka Circle")).toBeInTheDocument();
  });
});
