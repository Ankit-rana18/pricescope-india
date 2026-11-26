"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

import { ApiError, apiFetch, setAuthTokenProvider } from "@/lib/api";
import { publicEnv } from "@/lib/env";

export interface Me {
  id: string;
  email: string;
  display_name: string | null;
  role: "user" | "admin";
  default_pincode: string | null;
  preferences: { card_banks: string[]; card_types: ("CREDIT" | "DEBIT")[] };
}

export type AuthMode = "supabase" | "dev";

interface AuthState {
  mode: AuthMode;
  user: Me | null;
  loading: boolean;
  /** Supabase: emails a sign-in link. Dev: signs in immediately. */
  signIn: (email: string) => Promise<"signed_in" | "link_sent">;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
}

const DEV_TOKEN_KEY = "pricescope:dev-token";
const AuthContext = createContext<AuthState | null>(null);

let supabase: SupabaseClient | null = null;
function getSupabase(): SupabaseClient | null {
  if (!publicEnv.supabaseUrl || !publicEnv.supabaseAnonKey) return null;
  supabase ??= createClient(publicEnv.supabaseUrl, publicEnv.supabaseAnonKey, {
    auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
  });
  return supabase;
}

export const authMode: AuthMode =
  publicEnv.supabaseUrl && publicEnv.supabaseAnonKey ? "supabase" : "dev";

function readDevToken(): string | null {
  try {
    return window.localStorage.getItem(DEV_TOKEN_KEY);
  } catch {
    return null;
  }
}

async function currentToken(): Promise<string | null> {
  const client = getSupabase();
  if (client) {
    const { data } = await client.auth.getSession();
    return data.session?.access_token ?? null;
  }
  return readDevToken();
}

// Register at module load, not in an effect: React runs child effects before parent
// ones, so a page fetching on mount would otherwise send its first request without the
// token (and a private comparison would come back as "not found").
if (typeof window !== "undefined") setAuthTokenProvider(currentToken);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!(await currentToken())) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      setUser(await apiFetch<Me>("/api/v1/me", { cache: "no-store" }));
    } catch (err) {
      // An expired/invalid token means signed out; other errors keep the last state.
      if (err instanceof ApiError && err.status === 401) {
        try {
          window.localStorage.removeItem(DEV_TOKEN_KEY);
        } catch {
          /* storage blocked */
        }
        setUser(null);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const client = getSupabase();
    if (!client) return;
    const { data } = client.auth.onAuthStateChange(() => void refresh());
    return () => data.subscription.unsubscribe();
  }, [refresh]);

  const signIn = useCallback(
    async (email: string): Promise<"signed_in" | "link_sent"> => {
      const client = getSupabase();
      if (client) {
        const { error } = await client.auth.signInWithOtp({
          email,
          options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
        });
        if (error) throw new Error(error.message);
        return "link_sent";
      }
      window.localStorage.setItem(DEV_TOKEN_KEY, `dev:${email.trim().toLowerCase()}`);
      await refresh();
      return "signed_in";
    },
    [refresh],
  );

  const signOut = useCallback(async () => {
    const client = getSupabase();
    if (client) await client.auth.signOut();
    try {
      window.localStorage.removeItem(DEV_TOKEN_KEY);
    } catch {
      /* storage blocked */
    }
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ mode: authMode, user, loading, signIn, signOut, refresh }),
    [user, loading, signIn, signOut, refresh],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
