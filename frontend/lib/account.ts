import { apiFetch } from "@/lib/api";
import type { Me } from "@/lib/auth";
import type { Money } from "@/lib/comparison";

/** Mirrors backend/app/api/v1/account.py and admin.py. */
export interface HistoryItem {
  comparison_id: string;
  created_at: string;
  pincode: string;
  status: string;
  title: string | null;
  marketplace: string | null;
}

export interface SavedProduct {
  id: string;
  product_slug: string;
  title: string;
  note: string | null;
  created_at: string;
}

export interface PriceAlert {
  id: string;
  product_slug: string;
  title: string;
  pincode: string;
  target_price: Money;
  is_active: boolean;
  last_triggered_at: string | null;
  last_triggered_price: Money | null;
  last_triggered_marketplace: string | null;
  created_at: string;
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
  cache: "no-store",
});

export const account = {
  updateMe: (patch: Partial<Pick<Me, "display_name" | "default_pincode" | "preferences">>) =>
    apiFetch<Me>("/api/v1/me", json("PATCH", patch)),
  history: (cursor?: string | null) =>
    apiFetch<{ items: HistoryItem[]; next_cursor: string | null }>(
      `/api/v1/search/history${cursor ? `?cursor=${cursor}` : ""}`,
      { cache: "no-store" },
    ),
  saved: () => apiFetch<SavedProduct[]>("/api/v1/saved-products", { cache: "no-store" }),
  save: (product_slug: string) =>
    apiFetch<SavedProduct>("/api/v1/saved-products", json("POST", { product_slug })),
  unsave: (id: string) => apiFetch<void>(`/api/v1/saved-products/${id}`, json("DELETE")),
  alerts: () => apiFetch<PriceAlert[]>("/api/v1/alerts", { cache: "no-store" }),
  createAlert: (product_slug: string, pincode: string, target_price: string) =>
    apiFetch<PriceAlert>("/api/v1/alerts", json("POST", { product_slug, pincode, target_price })),
  updateAlert: (id: string, patch: { is_active?: boolean; target_price?: string }) =>
    apiFetch<PriceAlert>(`/api/v1/alerts/${id}`, json("PATCH", patch)),
  deleteAlert: (id: string) => apiFetch<void>(`/api/v1/alerts/${id}`, json("DELETE")),
};

export interface AdminOverview {
  storage: "ok" | "error";
  storage_backend: string;
  users: number;
  admins: number;
  comparisons_24h: number;
  comparisons_7d: number;
  comparisons_by_status_7d: Record<string, number>;
  marketplace_checks_24h: number;
  marketplace_failures_24h: number;
  active_alerts: number;
  alerts_triggered_7d: number;
}

export interface AdminUser {
  id: string;
  email: string;
  display_name: string | null;
  role: "user" | "admin";
  created_at: string;
  last_seen_at: string | null;
}

export interface IntegrationRow {
  marketplace: string;
  marketplace_name: string;
  state: string;
  reason: string;
  checks_24h: number;
  failures_24h: number;
  avg_latency_ms: number | null;
  last_error: string | null;
  last_checked_at: string | null;
}

export const admin = {
  overview: () => apiFetch<AdminOverview>("/api/v1/admin/overview", { cache: "no-store" }),
  users: () =>
    apiFetch<{ items: AdminUser[]; next_cursor: string | null }>("/api/v1/admin/users", {
      cache: "no-store",
    }),
  setRole: (id: string, role: "user" | "admin") =>
    apiFetch<AdminUser>(`/api/v1/admin/users/${id}`, json("PATCH", { role })),
  integrations: () =>
    apiFetch<IntegrationRow[]>("/api/v1/admin/integrations", { cache: "no-store" }),
  activity: () =>
    apiFetch<
      {
        comparison_id: string;
        created_at: string;
        pincode: string;
        status: string;
        data_mode: string;
        signed_in: boolean;
        title: string | null;
      }[]
    >("/api/v1/admin/activity", { cache: "no-store" }),
  errors: () =>
    apiFetch<
      {
        occurred_at: string;
        marketplace_name: string;
        status: string;
        error_code: string | null;
        message: string | null;
        latency_ms: number | null;
      }[]
    >("/api/v1/admin/errors", { cache: "no-store" }),
  audit: () =>
    apiFetch<
      {
        occurred_at: string;
        action: string;
        actor_id: string | null;
        target: string | null;
        metadata: Record<string, unknown>;
      }[]
    >("/api/v1/admin/audit", { cache: "no-store" }),
};
