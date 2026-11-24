"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { zodResolver } from "@hookform/resolvers/zod";
import { AlertCircle, ArrowRight, FlaskConical, Link2, Loader2, MapPin } from "lucide-react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, fieldErrorsOf } from "@/lib/api";
import { getDemoProducts, startComparison, type DemoProduct } from "@/lib/comparison";
import { lookupSchema, type LookupFormInput, type LookupFormValues } from "@/lib/validators";

const PIN_STORAGE_KEY = "pricescope:last-pincode";

function readSavedPin(): string {
  try {
    return window.localStorage.getItem(PIN_STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

function savePin(pin: string): void {
  try {
    window.localStorage.setItem(PIN_STORAGE_KEY, pin);
  } catch {
    // Private mode or blocked storage: remembering the PIN is only a convenience.
  }
}

export function LookupForm() {
  const router = useRouter();
  const [formError, setFormError] = useState<string | null>(null);
  const [demoProducts, setDemoProducts] = useState<DemoProduct[]>([]);

  const {
    register,
    handleSubmit,
    setError,
    setValue,
    clearErrors,
    formState: { errors, isSubmitting },
  } = useForm<LookupFormInput, unknown, LookupFormValues>({
    resolver: zodResolver(lookupSchema),
    defaultValues: { url: "", pincode: "" },
  });

  useEffect(() => {
    const saved = readSavedPin();
    if (saved) setValue("pincode", saved);
    // Only present in demo mode (the endpoint 404s otherwise).
    getDemoProducts()
      .then(setDemoProducts)
      .catch(() => setDemoProducts([]));
  }, [setValue]);

  async function onSubmit(values: LookupFormValues) {
    setFormError(null);
    try {
      const comparison = await startComparison(values.url, values.pincode);
      savePin(comparison.pincode);
      router.push(`/compare/${comparison.id}`);
    } catch (err) {
      const fields = fieldErrorsOf(err);
      if (fields.length > 0) {
        for (const f of fields) setError(f.field, { type: "server", message: f.message });
        return;
      }
      if (err instanceof ApiError && err.status < 500) {
        setFormError(err.body.message);
        return;
      }
      if (err instanceof ApiError && err.status === 503) {
        setFormError(err.body.message);
        return;
      }
      setFormError(
        "We couldn't reach the PriceScope service. Check that it's running and try again.",
      );
    }
  }

  function fillDemo(product: DemoProduct) {
    setValue("url", product.url, { shouldDirty: true });
    clearErrors("url");
    setFormError(null);
  }

  return (
    <div className="flex flex-col gap-4">
      <form
        onSubmit={handleSubmit(onSubmit)}
        noValidate
        aria-label="Compare prices for a product"
        className="bg-card rounded-2xl border p-4 shadow-[var(--shadow-card)] sm:p-5"
      >
        <div className="grid gap-4 md:grid-cols-[1fr_11rem_auto] md:items-start">
          <div className="flex flex-col gap-2">
            <Label htmlFor="url">Product link</Label>
            <div className="relative">
              <Link2
                className="text-muted-foreground pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2"
                aria-hidden
              />
              <Input
                id="url"
                type="text"
                inputMode="url"
                autoComplete="off"
                spellCheck={false}
                placeholder="https://www.amazon.in/dp/…"
                className="pl-10"
                aria-invalid={errors.url ? true : undefined}
                aria-describedby={errors.url ? "url-error" : undefined}
                {...register("url")}
              />
            </div>
            {errors.url && (
              <p id="url-error" role="alert" className="text-destructive text-sm">
                {errors.url.message}
              </p>
            )}
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="pincode">PIN code</Label>
            <div className="relative">
              <MapPin
                className="text-muted-foreground pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2"
                aria-hidden
              />
              <Input
                id="pincode"
                type="text"
                inputMode="numeric"
                autoComplete="postal-code"
                maxLength={8}
                placeholder="560001"
                className="tabular pl-10"
                aria-invalid={errors.pincode ? true : undefined}
                aria-describedby={errors.pincode ? "pincode-error" : undefined}
                {...register("pincode")}
              />
            </div>
            {errors.pincode && (
              <p id="pincode-error" role="alert" className="text-destructive text-sm">
                {errors.pincode.message}
              </p>
            )}
          </div>

          <div className="flex flex-col gap-2">
            <span className="hidden text-sm leading-none md:block" aria-hidden>
              &nbsp;
            </span>
            <Button
              type="submit"
              size="lg"
              className="h-11 w-full md:w-auto"
              disabled={isSubmitting}
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="animate-spin" aria-hidden /> Starting…
                </>
              ) : (
                <>
                  Compare prices <ArrowRight aria-hidden />
                </>
              )}
            </Button>
          </div>
        </div>
        <p className="text-muted-foreground mt-3 text-xs">
          Supported: Amazon India, Flipkart, Blinkit, Zepto and BigBasket product pages. Short share
          links (amzn.in, dl.flipkart.com) work too.
        </p>
      </form>

      {demoProducts.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted-foreground inline-flex items-center gap-1.5">
            <FlaskConical className="size-4" aria-hidden /> Try a demo product:
          </span>
          {demoProducts.map((p) => (
            <Button
              key={p.key}
              type="button"
              variant="outline"
              size="sm"
              onClick={() => fillDemo(p)}
              aria-label={`Use demo product ${p.title}`}
            >
              {p.title.replace(/\s*\(.*\)\s*$/, "").replace(/,.*$/, "")}
            </Button>
          ))}
        </div>
      )}

      {formError && (
        <div
          role="alert"
          className="border-destructive/30 bg-destructive/5 text-destructive flex gap-3 rounded-xl border p-4 text-sm"
        >
          <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
          <p>{formError}</p>
        </div>
      )}
    </div>
  );
}
