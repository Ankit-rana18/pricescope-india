import { publicEnv } from "@/lib/env";

/** Mirrors the backend's structured error envelope. */
export interface ApiErrorBody {
  code: string;
  message: string;
  details?: unknown;
  request_id?: string | null;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: ApiErrorBody,
  ) {
    super(body.message);
    this.name = "ApiError";
  }
}

export type DataMode = "DEMO" | "LIVE";

export type CheckStatus = "ok" | "error" | "not_configured";

export interface ReadinessResponse {
  status: "ok" | "error";
  data_mode: DataMode;
  storage_backend: "sheets" | "postgres";
  checks: Record<string, CheckStatus>;
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit & { timeoutMs?: number } = {},
): Promise<T> {
  const { timeoutMs = 8000, ...rest } = init;
  const res = await fetch(`${publicEnv.apiUrl}${path}`, {
    ...rest,
    headers: { Accept: "application/json", ...rest.headers },
    signal: rest.signal ?? AbortSignal.timeout(timeoutMs),
  });
  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const err =
      body && typeof body === "object" && "error" in body
        ? (body as { error: ApiErrorBody }).error
        : { code: "http_error", message: `Request failed (${res.status})` };
    throw new ApiError(res.status, err);
  }
  return body as T;
}

export type MarketplaceCode = "AMAZON_IN" | "FLIPKART" | "BLINKIT" | "ZEPTO" | "BIGBASKET";
export interface FieldError {
  field: "url" | "pincode";
  code: string;
  message: string;
}

/** Field-level problems from a 422 `invalid_input` response, if that's what this is. */
export function fieldErrorsOf(err: unknown): FieldError[] {
  if (!(err instanceof ApiError) || err.body.code !== "invalid_input") return [];
  const details = err.body.details as { fields?: FieldError[] } | undefined;
  return Array.isArray(details?.fields) ? details.fields : [];
}

/** Server-side readiness lookup; returns null when the API is unreachable. */
export async function getReadiness(): Promise<ReadinessResponse | null> {
  try {
    const res = await fetch(`${publicEnv.apiUrl}/api/v1/health/ready`, {
      headers: { Accept: "application/json" },
      // Never cached: a status badge must not keep saying "online" after the API fails.
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });
    // 503 still carries a full readiness body describing what is wrong.
    if (!res.ok && res.status !== 503) return null;
    const body = (await res.json()) as Partial<ReadinessResponse>;
    return body && typeof body.status === "string" && body.checks
      ? (body as ReadinessResponse)
      : null;
  } catch {
    return null;
  }
}
