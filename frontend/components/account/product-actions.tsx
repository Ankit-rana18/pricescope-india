"use client";

import { useState } from "react";
import Link from "next/link";
import { Bell, Bookmark, BookmarkCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { account } from "@/lib/account";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

/** Save + price-alert controls. Signed-out visitors get a real sign-in link instead. */
export function ProductActions({ slug, pincode }: { slug: string; pincode?: string }) {
  const { user, loading } = useAuth();
  const [saved, setSaved] = useState(false);
  const [alertOpen, setAlertOpen] = useState(false);
  const [pin, setPin] = useState(pincode ?? user?.default_pincode ?? "");
  const [target, setTarget] = useState("");
  const [note, setNote] = useState<{ tone: "ok" | "err"; text: React.ReactNode } | null>(null);

  if (loading) return null;
  if (!user) {
    return (
      <p className="text-muted-foreground text-sm">
        <Link href="/auth/login" className="text-primary font-medium hover:underline">
          Sign in
        </Link>{" "}
        to save this product or get a price alert.
      </p>
    );
  }

  const fail = (err: unknown, fallback: string) =>
    setNote({ tone: "err", text: err instanceof ApiError ? err.body.message : fallback });

  async function save() {
    setNote(null);
    try {
      await account.save(slug);
      setSaved(true);
    } catch (err) {
      fail(err, "Couldn't save the product.");
    }
  }

  async function createAlert(e: React.FormEvent) {
    e.preventDefault();
    setNote(null);
    if (!/^[1-9]\d{5}$/.test(pin))
      return setNote({ tone: "err", text: "Enter a 6-digit PIN code." });
    if (!/^\d+(\.\d{1,2})?$/.test(target) || Number(target) <= 0)
      return setNote({
        tone: "err",
        text: "Enter a target price in rupees, e.g. 1299 or 1299.50.",
      });
    try {
      await account.createAlert(slug, pin, target);
      setAlertOpen(false);
      setNote({
        tone: "ok",
        text: (
          <>
            Alert set. See it on{" "}
            <Link href="/alerts" className="underline">
              Price alerts
            </Link>
            .
          </>
        ),
      });
    } catch (err) {
      fail(err, "Couldn't create the alert.");
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" onClick={() => void save()} disabled={saved}>
          {saved ? <BookmarkCheck aria-hidden /> : <Bookmark aria-hidden />}
          {saved ? "Saved" : "Save product"}
        </Button>
        <Button
          variant="outline"
          size="sm"
          aria-expanded={alertOpen}
          onClick={() => {
            if (!pin && user.default_pincode) setPin(user.default_pincode);
            setAlertOpen((o) => !o);
          }}
        >
          <Bell aria-hidden /> Alert me
        </Button>
      </div>
      {alertOpen && (
        <form onSubmit={createAlert} noValidate className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1">
            <Label htmlFor="alert-pin">PIN code</Label>
            <Input
              id="alert-pin"
              inputMode="numeric"
              maxLength={6}
              className="w-28"
              value={pin}
              onChange={(e) => setPin(e.target.value.trim())}
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="alert-target">Alert at or below (₹)</Label>
            <Input
              id="alert-target"
              inputMode="decimal"
              className="w-36"
              value={target}
              onChange={(e) => setTarget(e.target.value.trim())}
            />
          </div>
          <Button type="submit" size="sm">
            Create alert
          </Button>
        </form>
      )}
      {note && (
        <p
          role={note.tone === "err" ? "alert" : "status"}
          className={`text-sm ${note.tone === "err" ? "text-destructive" : "text-success"}`}
        >
          {note.text}
        </p>
      )}
    </div>
  );
}
