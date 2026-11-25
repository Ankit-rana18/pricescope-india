"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { BellRing, Trash2, X } from "lucide-react";

import { RequireSignIn } from "@/components/account/require-sign-in";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { account, type HistoryItem, type PriceAlert, type SavedProduct } from "@/lib/account";
import { ApiError } from "@/lib/api";
import { useAuth, type Me } from "@/lib/auth";
import { formatINR } from "@/lib/comparison";

const DATE = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

function message(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.body.message : fallback;
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-muted-foreground rounded-2xl border border-dashed p-6 text-sm">{children}</p>
  );
}

// ------------------------------------------------------------------ history

function HistoryInner() {
  const [items, setItems] = useState<HistoryItem[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (from?: string | null) => {
    try {
      const page = await account.history(from);
      setItems((prev) => [...(from ? (prev ?? []) : []), ...page.items]);
      setCursor(page.next_cursor);
    } catch (err) {
      setError(message(err, "Couldn't load your history."));
    }
  }, []);
  useEffect(() => void load(), [load]);

  if (error) return <p className="text-destructive text-sm">{error}</p>;
  if (!items) return <Skeleton className="h-40 w-full" />;
  if (!items.length) {
    return (
      <Empty>
        No comparisons yet.{" "}
        <Link href="/" className="text-primary underline">
          Compare a product
        </Link>{" "}
        while signed in and it will appear here.
      </Empty>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <ul className="divide-y rounded-2xl border">
        {items.map((i) => (
          <li key={i.comparison_id}>
            <Link
              href={`/compare/${i.comparison_id}`}
              className="hover:bg-muted/50 flex flex-wrap items-center justify-between gap-2 px-4 py-3"
            >
              <span className="flex flex-col">
                <span className="font-medium">{i.title ?? "Comparison"}</span>
                <span className="text-muted-foreground text-xs">
                  {i.marketplace} · PIN {i.pincode} · {DATE.format(new Date(i.created_at))}
                </span>
              </span>
              <Badge
                tone={
                  i.status === "COMPLETE"
                    ? "success"
                    : i.status === "PARTIAL"
                      ? "warning"
                      : "neutral"
                }
              >
                {i.status.toLowerCase()}
              </Badge>
            </Link>
          </li>
        ))}
      </ul>
      {cursor && (
        <Button variant="outline" size="sm" className="w-fit" onClick={() => void load(cursor)}>
          Load more
        </Button>
      )}
    </div>
  );
}

export function HistoryView() {
  return <RequireSignIn>{() => <HistoryInner />}</RequireSignIn>;
}

// ------------------------------------------------------------------ saved products

function SavedInner() {
  const [items, setItems] = useState<SavedProduct[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    account
      .saved()
      .then(setItems, (err) => setError(message(err, "Couldn't load saved products.")));
  }, []);

  async function remove(id: string) {
    try {
      await account.unsave(id);
      setItems((prev) => prev?.filter((s) => s.id !== id) ?? null);
    } catch (err) {
      setError(message(err, "Couldn't remove it."));
    }
  }

  if (error) return <p className="text-destructive text-sm">{error}</p>;
  if (!items) return <Skeleton className="h-40 w-full" />;
  if (!items.length) {
    return <Empty>Nothing saved yet. Use “Save product” on a comparison or product page.</Empty>;
  }
  return (
    <ul className="grid gap-3 sm:grid-cols-2">
      {items.map((s) => (
        <li key={s.id}>
          <Card className="h-full">
            <CardContent className="flex items-start justify-between gap-3">
              <Link href={`/products/${s.product_slug}`} className="font-medium hover:underline">
                {s.title}
              </Link>
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Remove ${s.title}`}
                onClick={() => void remove(s.id)}
              >
                <Trash2 aria-hidden />
              </Button>
            </CardContent>
          </Card>
        </li>
      ))}
    </ul>
  );
}

export function SavedView() {
  return <RequireSignIn>{() => <SavedInner />}</RequireSignIn>;
}

// ------------------------------------------------------------------ alerts

function AlertsInner() {
  const [items, setItems] = useState<PriceAlert[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    account.alerts().then(setItems, (err) => setError(message(err, "Couldn't load alerts.")));
  }, []);

  async function toggle(a: PriceAlert) {
    try {
      const updated = await account.updateAlert(a.id, { is_active: !a.is_active });
      setItems((prev) => prev?.map((x) => (x.id === a.id ? updated : x)) ?? null);
    } catch (err) {
      setError(message(err, "Couldn't update the alert."));
    }
  }
  async function remove(id: string) {
    try {
      await account.deleteAlert(id);
      setItems((prev) => prev?.filter((x) => x.id !== id) ?? null);
    } catch (err) {
      setError(message(err, "Couldn't delete the alert."));
    }
  }

  if (error) return <p className="text-destructive text-sm">{error}</p>;
  if (!items) return <Skeleton className="h-40 w-full" />;
  return (
    <div className="flex flex-col gap-4">
      <p className="text-muted-foreground text-sm">
        An alert triggers when a comparison finds the cheapest <em>fully verified</em> price at or
        below your target for that PIN code. Email notifications aren&apos;t set up yet, so
        triggered alerts show here.
      </p>
      {!items.length ? (
        <Empty>No alerts yet. Use “Alert me” on a comparison or product page.</Empty>
      ) : (
        <ul className="divide-y rounded-2xl border">
          {items.map((a) => (
            <li key={a.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
              <span className="flex flex-col gap-0.5">
                <Link href={`/products/${a.product_slug}`} className="font-medium hover:underline">
                  {a.title}
                </Link>
                <span className="text-muted-foreground text-xs">
                  At or below {formatINR(a.target_price)} · PIN {a.pincode}
                </span>
                {a.last_triggered_at && a.last_triggered_price && (
                  <span className="text-success inline-flex items-center gap-1 text-xs">
                    <BellRing className="size-3.5" aria-hidden />{" "}
                    {formatINR(a.last_triggered_price)} on {a.last_triggered_marketplace} ·{" "}
                    {DATE.format(new Date(a.last_triggered_at))}
                  </span>
                )}
              </span>
              <span className="flex gap-2">
                <Button variant="outline" size="sm" onClick={() => void toggle(a)}>
                  {a.is_active ? "Pause" : "Resume"}
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label="Delete alert"
                  onClick={() => void remove(a.id)}
                >
                  <Trash2 aria-hidden />
                </Button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function AlertsView() {
  return <RequireSignIn>{() => <AlertsInner />}</RequireSignIn>;
}

// ------------------------------------------------------------------ account & cards

function AccountInner({ me }: { me: Me }) {
  const { refresh } = useAuth();
  const [name, setName] = useState(me.display_name ?? "");
  const [pin, setPin] = useState(me.default_pincode ?? "");
  const [banks, setBanks] = useState<string[]>(me.preferences.card_banks);
  const [types, setTypes] = useState(me.preferences.card_types);
  const [bank, setBank] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function addBank() {
    const b = bank.trim();
    if (b && !banks.some((x) => x.toLowerCase() === b.toLowerCase())) setBanks([...banks, b]);
    setBank("");
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setStatus(null);
    try {
      await account.updateMe({
        display_name: name,
        default_pincode: pin,
        preferences: { card_banks: banks, card_types: types },
      });
      await refresh();
      setStatus("Saved.");
    } catch (err) {
      setError(message(err, "Couldn't save."));
    }
  }

  const toggleType = (t: "CREDIT" | "DEBIT") =>
    setTypes(types.includes(t) ? types.filter((x) => x !== t) : [...types, t]);

  return (
    <form onSubmit={save} className="flex flex-col gap-6">
      <Card>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-2">
            <Label htmlFor="name">Name</Label>
            <Input
              id="name"
              value={name}
              maxLength={120}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="pin">Default PIN code</Label>
            <Input
              id="pin"
              inputMode="numeric"
              maxLength={8}
              value={pin}
              onChange={(e) => setPin(e.target.value)}
            />
          </div>
          <p className="text-muted-foreground text-xs sm:col-span-2">Signed in as {me.email}.</p>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="flex flex-col gap-4">
          <div>
            <h2 className="font-semibold">Your cards</h2>
            <p className="text-muted-foreground text-sm">
              Add the banks whose cards you hold. “Best card offer” then only uses offers you can
              actually use. Only bank names are stored, never card numbers.
            </p>
          </div>
          <div className="flex flex-wrap gap-2" aria-label="Saved banks">
            {banks.map((b) => (
              <Badge key={b} tone="accent" className="py-1 pr-1">
                {b}
                <button
                  type="button"
                  aria-label={`Remove ${b}`}
                  onClick={() => setBanks(banks.filter((x) => x !== b))}
                  className="hover:bg-background/50 rounded-full p-0.5"
                >
                  <X aria-hidden />
                </button>
              </Badge>
            ))}
            {!banks.length && (
              <span className="text-muted-foreground text-sm">No banks added.</span>
            )}
          </div>
          <div className="flex gap-2">
            <Input
              aria-label="Bank name"
              placeholder="e.g. HDFC Bank"
              value={bank}
              maxLength={60}
              onChange={(e) => setBank(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addBank();
                }
              }}
            />
            <Button type="button" variant="outline" onClick={addBank}>
              Add
            </Button>
          </div>
          <fieldset className="flex gap-4 text-sm">
            <legend className="text-muted-foreground mb-2 text-xs">
              Card types (leave both off for any)
            </legend>
            {(["CREDIT", "DEBIT"] as const).map((t) => (
              <label key={t} className="inline-flex items-center gap-2">
                <input type="checkbox" checked={types.includes(t)} onChange={() => toggleType(t)} />
                {t === "CREDIT" ? "Credit cards" : "Debit cards"}
              </label>
            ))}
          </fieldset>
        </CardContent>
      </Card>

      <div className="flex items-center gap-3">
        <Button type="submit">Save changes</Button>
        {status && (
          <span role="status" className="text-success text-sm">
            {status}
          </span>
        )}
        {error && (
          <span role="alert" className="text-destructive text-sm">
            {error}
          </span>
        )}
      </div>
    </form>
  );
}

export function AccountView() {
  return <RequireSignIn>{(me) => <AccountInner me={me} />}</RequireSignIn>;
}
