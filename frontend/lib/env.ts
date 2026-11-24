/**
 * Browser-visible configuration only. Never put secrets in NEXT_PUBLIC_* variables.
 */
export const publicEnv = {
  apiUrl: (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/+$/, ""),
} as const;
