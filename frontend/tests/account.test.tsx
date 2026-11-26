import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LoginForm } from "@/components/account/login-form";
import { ProductActions } from "@/components/account/product-actions";
import { RequireSignIn } from "@/components/account/require-sign-in";
import { AuthProvider, type Me } from "@/lib/auth";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const ME: Me = {
  id: "u1",
  email: "asha@example.com",
  display_name: null,
  role: "user",
  default_pincode: "560001",
  preferences: { card_banks: [], card_types: [] },
};

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

type Call = { url: string; method: string; auth: string | null; body: unknown };
let calls: Call[];

function mockApi(me: Me | null, extra?: (c: Call) => Response | undefined) {
  calls = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const headers = new Headers(init?.headers);
    const call: Call = {
      url: String(input),
      method: init?.method ?? "GET",
      auth: headers.get("Authorization"),
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    };
    calls.push(call);
    const custom = extra?.(call);
    if (custom) return custom;
    if (call.url.endsWith("/api/v1/me")) {
      return me ? json(me) : json({ error: "unauthenticated", message: "Sign in" }, 401);
    }
    return json({ error: "not_found", message: "Not found" }, 404);
  });
}

const withAuth = (ui: React.ReactNode) => render(<AuthProvider>{ui}</AuthProvider>);

beforeEach(() => {
  window.localStorage.clear();
  push.mockReset();
});
afterEach(() => vi.restoreAllMocks());

describe("sign-in", () => {
  it("dev sign-in stores a labelled dev token and sends it as a bearer token", async () => {
    mockApi(ME);
    withAuth(<LoginForm />);
    expect(await screen.findByText(/Development sign-in/)).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Email"), "Asha@Example.com");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/history"));
    expect(window.localStorage.getItem("pricescope:dev-token")).toBe("dev:asha@example.com");
    expect(calls.find((c) => c.url.endsWith("/api/v1/me"))?.auth).toBe(
      "Bearer dev:asha@example.com",
    );
  });

  it("rejects an invalid email without calling the API", async () => {
    mockApi(null);
    withAuth(<LoginForm />);
    await userEvent.type(await screen.findByLabelText("Email"), "not-an-email");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(screen.getByRole("alert")).toHaveTextContent("valid email");
    expect(calls).toHaveLength(0);
  });

  it("drops an expired token when the API answers 401", async () => {
    window.localStorage.setItem("pricescope:dev-token", "dev:old@example.com");
    mockApi(null);
    withAuth(<RequireSignIn>{() => <p>secret</p>}</RequireSignIn>);
    expect(await screen.findByRole("link", { name: "Sign in" })).toHaveAttribute(
      "href",
      "/auth/login",
    );
    expect(window.localStorage.getItem("pricescope:dev-token")).toBeNull();
  });
});

describe("RequireSignIn", () => {
  it("keeps admin pages from non-admins", async () => {
    window.localStorage.setItem("pricescope:dev-token", "dev:asha@example.com");
    mockApi(ME);
    withAuth(<RequireSignIn admin>{() => <p>admin stuff</p>}</RequireSignIn>);
    expect(await screen.findByText("This page is for admins only.")).toBeInTheDocument();
    expect(screen.queryByText("admin stuff")).not.toBeInTheDocument();
  });
});

describe("ProductActions", () => {
  it("offers a real sign-in link when signed out", async () => {
    mockApi(null);
    withAuth(<ProductActions slug="nimbus-x2" />);
    expect(await screen.findByRole("link", { name: "Sign in" })).toHaveAttribute(
      "href",
      "/auth/login",
    );
    expect(screen.queryByRole("button", { name: /Save product/ })).not.toBeInTheDocument();
  });

  it("validates and creates a price alert using the default PIN", async () => {
    window.localStorage.setItem("pricescope:dev-token", "dev:asha@example.com");
    mockApi(ME, (c) =>
      c.url.endsWith("/api/v1/alerts") && c.method === "POST" ? json({ id: "a1" }, 201) : undefined,
    );
    withAuth(<ProductActions slug="nimbus-x2" />);
    await userEvent.click(await screen.findByRole("button", { name: /Alert me/ }));
    expect(screen.getByLabelText("PIN code")).toHaveValue("560001");

    await userEvent.type(screen.getByLabelText(/Alert at or below/), "12,000");
    await userEvent.click(screen.getByRole("button", { name: "Create alert" }));
    expect(screen.getByRole("alert")).toHaveTextContent("target price");
    expect(calls.some((c) => c.method === "POST")).toBe(false);

    await userEvent.clear(screen.getByLabelText(/Alert at or below/));
    await userEvent.type(screen.getByLabelText(/Alert at or below/), "12000.50");
    await userEvent.click(screen.getByRole("button", { name: "Create alert" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Alert set");
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      product_slug: "nimbus-x2",
      pincode: "560001",
      target_price: "12000.50",
    });
  });
});

describe("token on first load", () => {
  it("sends the token with the very first request a page makes on mount", async () => {
    window.localStorage.setItem("pricescope:dev-token", "dev:asha@example.com");
    mockApi(ME);
    const { ComparisonView } = await import("@/components/compare/comparison-view");
    withAuth(<ComparisonView id="c-1" />);
    await waitFor(() => expect(calls.some((c) => c.url.includes("/comparisons/c-1"))).toBe(true));
    const first = calls.find((c) => c.url.includes("/comparisons/c-1"));
    expect(first?.auth).toBe("Bearer dev:asha@example.com");
  });
});
