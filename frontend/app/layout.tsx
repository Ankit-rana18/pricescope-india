import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";

import { DemoModeBanner } from "@/components/layout/demo-mode-banner";
import { SiteFooter } from "@/components/layout/site-footer";
import { SiteHeader } from "@/components/layout/site-header";
import { getReadiness } from "@/lib/api";

import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000"),
  title: {
    default: "PriceScope India — compare the exact product across marketplaces",
    template: "%s · PriceScope India",
  },
  description:
    "Paste a product link and your PIN code to compare the exact same product across Amazon, Flipkart, Blinkit, Zepto and BigBasket, with transparent final prices.",
};

export const viewport: Viewport = {
  themeColor: "#fafafb",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const readiness = await getReadiness();
  // If the API is unreachable we cannot know the mode, so stay on the safe side.
  const showDemo = !readiness || readiness.data_mode === "DEMO";

  return (
    <html lang="en-IN" className={inter.variable}>
      <body className="flex min-h-dvh flex-col font-sans">
        {showDemo && <DemoModeBanner />}
        <SiteHeader />
        <main className="flex-1">{children}</main>
        <SiteFooter readiness={readiness} />
      </body>
    </html>
  );
}
