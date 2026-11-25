/**
 * Browser-visible configuration only. Never put secrets in NEXT_PUBLIC_* variables.
 */
export const publicEnv = {
  apiUrl: (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/+$/, ""),
  // Public values only: the anon key is designed to be shipped to browsers.
  supabaseUrl: process.env.NEXT_PUBLIC_SUPABASE_URL ?? "",
  supabaseAnonKey: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "",
} as const;
