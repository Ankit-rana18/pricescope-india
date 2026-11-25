"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { useAuth } from "@/lib/auth";

/** Landing page for Supabase sign-in links: the client reads the session from the URL. */
export function AuthCallback() {
  const { user, loading } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (!loading && user) router.replace("/history");
  }, [loading, user, router]);
  return (
    <div className="mx-auto max-w-md px-4 py-16 text-sm">
      {loading || user ? (
        <p role="status">Signing you in…</p>
      ) : (
        <p>
          That sign-in link didn&apos;t work (it may have expired).{" "}
          <Link href="/auth/login" className="text-primary underline">
            Request a new one
          </Link>
          .
        </p>
      )}
    </div>
  );
}
