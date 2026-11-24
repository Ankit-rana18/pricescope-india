import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LookupForm } from "@/components/compare/lookup-form";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const DEMO = [
  {
    key: "nimbus-x2-phone",
    title: "Nimbus X2 5G (Midnight Black, 8GB RAM, 128GB Storage)",
    marketplace: "AMAZON_IN",
    url: "https://www.amazon.in/dp/DEMO000003",
  },
];

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Route fetch by URL: the demo list, and whatever the comparison POST should return. */
function mockApi(post: Response | Error, demo: unknown = DEMO) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.endsWith("/api/v1/demo/products")) return json(demo ? 200 : 404, demo ?? {});
    if (post instanceof Error) throw post;
    return post;
  });
}

async function submit(url: string, pincode: string) {
  const user = userEvent.setup();
  if (url) await user.type(screen.getByLabelText("Product link"), url);
  if (pincode) {
    await user.clear(screen.getByLabelText("PIN code"));
    await user.type(screen.getByLabelText("PIN code"), pincode);
  }
  await user.click(screen.getByRole("button", { name: /compare prices/i }));
}

describe("LookupForm", () => {
  beforeEach(() => push.mockReset());

  it("shows inline errors without starting a comparison", async () => {
    const spy = mockApi(json(202, {}));
    render(<LookupForm />);
    await submit("", "");
    expect(await screen.findByText("Paste a product link.")).toBeInTheDocument();
    expect(screen.getByText("Enter your 6-digit PIN code.")).toBeInTheDocument();
    expect(spy.mock.calls.some(([u]) => String(u).endsWith("/comparisons"))).toBe(false);
  });

  it("starts a comparison and opens its page", async () => {
    const spy = mockApi(json(202, { id: "abc-123", pincode: "560001", status: "RUNNING" }));
    render(<LookupForm />);
    await submit("https://www.amazon.in/dp/DEMO000003", "560 001");

    await waitFor(() => expect(push).toHaveBeenCalledWith("/compare/abc-123"));
    const post = spy.mock.calls.find(([u]) => String(u).endsWith("/api/v1/comparisons"));
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({
      url: "https://www.amazon.in/dp/DEMO000003",
      pincode: "560001",
    });
    expect(window.localStorage.getItem("pricescope:last-pincode")).toBe("560001");
  });

  it("puts server field errors next to the right field", async () => {
    mockApi(
      json(422, {
        error: {
          code: "invalid_input",
          message: "x",
          details: {
            fields: [
              {
                field: "url",
                code: "unsupported_marketplace",
                message: "Paste a link from Amazon India…",
              },
            ],
          },
        },
      }),
    );
    render(<LookupForm />);
    await submit("https://example.com/p", "560001");
    expect(await screen.findByText("Paste a link from Amazon India…")).toHaveAttribute(
      "id",
      "url-error",
    );
    expect(push).not.toHaveBeenCalled();
  });

  it("explains when the source marketplace isn't connected", async () => {
    mockApi(
      json(503, {
        error: { code: "source_unavailable", message: "Amazon India isn't connected yet…" },
      }),
    );
    render(<LookupForm />);
    await submit("https://www.amazon.in/dp/B07JGFGW3V", "560001");
    expect(await screen.findByRole("alert")).toHaveTextContent("Amazon India isn't connected yet");
  });

  it("explains when the service can't be reached", async () => {
    mockApi(new TypeError("Failed to fetch"));
    render(<LookupForm />);
    await submit("https://www.amazon.in/dp/DEMO000003", "560001");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /couldn't reach the PriceScope service/,
    );
  });

  it("demo buttons fill the link (demo mode only)", async () => {
    mockApi(json(202, {}));
    render(<LookupForm />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /use demo product nimbus/i }));
    expect(screen.getByLabelText("Product link")).toHaveValue(
      "https://www.amazon.in/dp/DEMO000003",
    );
  });

  it("shows no demo buttons outside demo mode", async () => {
    const spy = mockApi(json(202, {}), null);
    render(<LookupForm />);
    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(screen.queryByText(/try a demo product/i)).not.toBeInTheDocument();
  });

  it("pre-fills the last PIN code used", async () => {
    mockApi(json(202, {}));
    window.localStorage.setItem("pricescope:last-pincode", "110001");
    render(<LookupForm />);
    await waitFor(() => expect(screen.getByLabelText("PIN code")).toHaveValue("110001"));
  });
});
