import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LookupForm } from "@/components/compare/lookup-form";
import type { LookupResult } from "@/lib/api";

const SUCCESS: LookupResult = {
  product: {
    marketplace: "AMAZON_IN",
    marketplace_name: "Amazon India",
    external_id: "B07JGFGW3V",
    id_type: "ASIN",
    canonical_url: "https://www.amazon.in/dp/B07JGFGW3V",
    resolved_from: null,
  },
  location: {
    pincode: "560001",
    postal_region: "Southern",
    directory_status: "UNAVAILABLE",
    district: null,
    state: null,
    post_offices: 0,
    delivery_note: "A valid PIN code does not guarantee delivery.",
  },
  comparison_available: false,
};

function mockFetch(status: number, body: unknown) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

async function fillAndSubmit(url: string, pincode: string) {
  const user = userEvent.setup();
  if (url) await user.type(screen.getByLabelText("Product link"), url);
  if (pincode) await user.type(screen.getByLabelText("PIN code"), pincode);
  await user.click(screen.getByRole("button", { name: /check link & pin/i }));
}

describe("LookupForm", () => {
  it("shows inline errors without calling the API when fields are empty", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    render(<LookupForm />);
    await fillAndSubmit("", "");

    expect(await screen.findByText("Paste a product link.")).toBeInTheDocument();
    expect(screen.getByText("Enter your 6-digit PIN code.")).toBeInTheDocument();
    expect(screen.getByLabelText("Product link")).toHaveAttribute("aria-invalid", "true");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("puts server field errors next to the right field", async () => {
    mockFetch(422, {
      error: {
        code: "invalid_input",
        message: "Paste a link from Amazon India, Flipkart, Blinkit, Zepto or BigBasket.",
        details: {
          fields: [
            {
              field: "url",
              code: "unsupported_marketplace",
              message: "Paste a link from Amazon India, Flipkart, Blinkit, Zepto or BigBasket.",
            },
          ],
        },
        request_id: "abc",
      },
    });
    render(<LookupForm />);
    await fillAndSubmit("https://www.amazon.com/dp/B07JGFGW3V", "560001");

    const message = await screen.findByText(/Paste a link from Amazon India/);
    expect(message).toHaveAttribute("id", "url-error");
    expect(screen.queryByText(/Price comparison isn't available yet/)).not.toBeInTheDocument();
  });

  it("shows what was recognised, and says honestly that nothing was compared", async () => {
    const fetchSpy = mockFetch(200, SUCCESS);
    render(<LookupForm />);
    await fillAndSubmit("https://www.amazon.in/dp/B07JGFGW3V", "560 001");

    expect(await screen.findByText("Amazon India")).toBeInTheDocument();
    expect(screen.getByText("B07JGFGW3V")).toBeInTheDocument();
    expect(screen.getByText("Format checked only")).toBeInTheDocument();
    expect(screen.getByText(/Price comparison isn't available yet/)).toBeInTheDocument();

    const link = screen.getByRole("link", { name: /open on amazon india/i });
    expect(link).toHaveAttribute("href", "https://www.amazon.in/dp/B07JGFGW3V");
    expect(link).toHaveAttribute("rel", "noopener noreferrer nofollow");

    const [, init] = fetchSpy.mock.calls[0]!;
    expect(JSON.parse(String(init?.body))).toEqual({
      url: "https://www.amazon.in/dp/B07JGFGW3V",
      pincode: "560001",
    });
    await waitFor(() =>
      expect(window.localStorage.getItem("pricescope:last-pincode")).toBe("560001"),
    );
  });

  it("explains when the service can't be reached", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    render(<LookupForm />);
    await fillAndSubmit("https://www.amazon.in/dp/B07JGFGW3V", "560001");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /couldn't reach the PriceScope service/,
    );
  });

  it("pre-fills the last PIN code used", async () => {
    window.localStorage.setItem("pricescope:last-pincode", "110001");
    render(<LookupForm />);
    await waitFor(() => expect(screen.getByLabelText("PIN code")).toHaveValue("110001"));
  });

  it("shows the short link a product was found through", async () => {
    mockFetch(200, {
      ...SUCCESS,
      product: { ...SUCCESS.product, resolved_from: "https://amzn.in/d/7xYz" },
    });
    render(<LookupForm />);
    await fillAndSubmit("amzn.in/d/7xYz", "560001");

    expect(await screen.findByText("Short link")).toBeInTheDocument();
    expect(screen.getByText("https://amzn.in/d/7xYz")).toBeInTheDocument();
    expect(screen.getByText(/only followed your short link/)).toBeInTheDocument();
    expect(screen.queryByText(/No marketplace was contacted/)).not.toBeInTheDocument();
  });
});
