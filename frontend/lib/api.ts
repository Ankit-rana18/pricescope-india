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

export interface ReadinessResponse {
  status: "ok" | "error";
  data_mode: DataMode;
  checks: Record<string, "ok" | "error">;
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

/** Server-side readiness lookup; returns null when the API is unreachable. */
export async function getReadiness(): Promise<ReadinessResponse | null> {
  try {
    return await apiFetch<ReadinessResponse>("/api/v1/health/ready", {
      next: { revalidate: 30 },
      timeoutMs: 3000,
    });
  } catch (err) {
    // 503 still carries a readiness body worth showing.
    if (err instanceof ApiError && err.status === 503) {
      return { status: "error", data_mode: "DEMO", checks: {} };
    }
    return null;
  }
}
