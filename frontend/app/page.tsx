import { BadgeCheck, Link2, MapPin, Scale } from "lucide-react";

import { LookupForm } from "@/components/compare/lookup-form";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardTitle } from "@/components/ui/card";

const STEPS = [
  {
    icon: Link2,
    title: "Paste a product link",
    body: "Start from a product page on Amazon, Flipkart, Blinkit, Zepto or BigBasket.",
  },
  {
    icon: MapPin,
    title: "Enter your PIN code",
    body: "Availability, delivery fees and prices are checked for your location where the marketplace allows it.",
  },
  {
    icon: Scale,
    title: "Compare the exact variant",
    body: "Same brand, model, size, quantity and pack count — mismatches are rejected, not ranked.",
  },
] as const;

export default function HomePage() {
  return (
    <div className="mx-auto max-w-6xl px-4 sm:px-6">
      <section className="animate-in fade-in slide-in-from-bottom-2 py-12 duration-300 sm:py-20">
        <Badge tone="accent" className="mb-5">
          <BadgeCheck aria-hidden /> Exact-match comparisons only
        </Badge>
        <h1 className="max-w-3xl text-4xl font-semibold tracking-tight text-balance sm:text-5xl">
          The real final price of the exact product, across India&apos;s marketplaces.
        </h1>
        <p className="text-muted-foreground mt-5 max-w-2xl text-lg text-pretty">
          PriceScope compares the same item — down to size, quantity and pack count — and shows
          delivery, handling and platform fees openly. Anything we can&apos;t verify is labelled as
          unverified, never guessed.
        </p>
        <div className="mt-8 max-w-4xl">
          <LookupForm />
        </div>
      </section>

      <section aria-labelledby="how-it-works" className="pb-20">
        <h2 id="how-it-works" className="sr-only">
          How it works
        </h2>
        <ol className="grid gap-4 md:grid-cols-3">
          {STEPS.map(({ icon: Icon, title, body }, i) => (
            <li key={title}>
              <Card className="h-full">
                <CardContent className="flex flex-col gap-3">
                  <div className="flex items-center gap-3">
                    <span className="bg-accent text-accent-foreground grid size-9 place-items-center rounded-xl">
                      <Icon className="size-4" aria-hidden />
                    </span>
                    <span className="tabular text-muted-foreground text-xs font-medium">
                      Step {i + 1}
                    </span>
                  </div>
                  <CardTitle>{title}</CardTitle>
                  <CardDescription className="leading-relaxed">{body}</CardDescription>
                </CardContent>
              </Card>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
