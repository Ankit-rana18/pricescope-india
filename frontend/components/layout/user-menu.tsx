"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ChevronDown, LogIn, Shield } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";

const LINKS = [
  { href: "/history", label: "History" },
  { href: "/saved", label: "Saved products" },
  { href: "/alerts", label: "Price alerts" },
  { href: "/account", label: "Account & cards" },
];

export function UserMenu() {
  const { user, loading, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (
        e instanceof KeyboardEvent ? e.key === "Escape" : !ref.current?.contains(e.target as Node)
      )
        setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  if (loading) return <span className="bg-muted h-9 w-20 animate-pulse rounded-lg" aria-hidden />;
  if (!user) {
    return (
      <Button asChild variant="outline" size="sm">
        <Link href="/auth/login">
          <LogIn aria-hidden /> Sign in
        </Link>
      </Button>
    );
  }

  return (
    <div ref={ref} className="relative">
      <Button
        variant="ghost"
        size="sm"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="bg-accent text-accent-foreground grid size-6 place-items-center rounded-full text-xs font-semibold">
          {(user.display_name || user.email).charAt(0).toUpperCase()}
        </span>
        <span className="hidden max-w-40 truncate sm:inline">
          {user.display_name || user.email}
        </span>
        <ChevronDown aria-hidden />
      </Button>
      {open && (
        <div
          role="menu"
          className="bg-popover text-popover-foreground absolute right-0 z-50 mt-2 w-56 rounded-xl border p-1 shadow-lg"
        >
          <p className="text-muted-foreground truncate px-3 py-2 text-xs">{user.email}</p>
          {LINKS.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              role="menuitem"
              onClick={() => setOpen(false)}
              className="hover:bg-muted block rounded-lg px-3 py-2 text-sm"
            >
              {l.label}
            </Link>
          ))}
          {user.role === "admin" && (
            <Link
              href="/admin"
              role="menuitem"
              onClick={() => setOpen(false)}
              className="hover:bg-muted flex items-center gap-2 rounded-lg px-3 py-2 text-sm"
            >
              <Shield className="size-4" aria-hidden /> Admin dashboard
            </Link>
          )}
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              void signOut();
            }}
            className="hover:bg-muted w-full rounded-lg border-t px-3 py-2 text-left text-sm"
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
