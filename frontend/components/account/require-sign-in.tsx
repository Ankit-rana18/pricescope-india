"use client";

import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth, type Me } from "@/lib/auth";

export function RequireSignIn({
  children,
  admin = false,
}: {
  children: (user: Me) => React.ReactNode;
  admin?: boolean;
}) {
  const { user, loading } = useAuth();
  if (loading) return <Skeleton className="h-40 w-full" />;
  if (!user) {
    return (
      <div className="flex flex-col items-start gap-3 rounded-2xl border border-dashed p-6">
        <p className="text-sm">Sign in to see this page.</p>
        <Button asChild size="sm">
          <Link href="/auth/login">Sign in</Link>
        </Button>
      </div>
    );
  }
  if (admin && user.role !== "admin") {
    return <p className="text-muted-foreground text-sm">This page is for admins only.</p>;
  }
  return <>{children(user)}</>;
}

export function PageShell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6 px-4 py-8 sm:px-6 sm:py-12">
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      {children}
    </div>
  );
}

export const PRIVATE_PAGE = { robots: { index: false, follow: false } } as const;
