import type { Metadata } from "next";
import { Cormorant_Garamond, Manrope } from "next/font/google";
import Link from "next/link";

import { Providers } from "@/components/providers";
import { SiteHeader } from "@/components/site-header";

import "./globals.css";

const display = Cormorant_Garamond({
  variable: "--font-cormorant",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  style: ["normal", "italic"],
});
const sans = Manrope({ variable: "--font-manrope", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: "Gabriella — your stylist, in stock", template: "%s · Gabriella" },
  description:
    "An inventory-aware fashion assistant for a simulated multi-brand retailer. Every recommendation is a real, in-stock product.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${display.variable} ${sans.variable}`}>
      <body className="flex min-h-dvh flex-col">
        <Providers>
          <SiteHeader />
          <main className="flex-1">{children}</main>
          <footer className="mt-24 border-t border-line">
            <div className="mx-auto grid max-w-7xl gap-8 px-4 py-12 text-sm text-muted sm:px-6 md:grid-cols-3">
              <div>
                <p className="font-display text-2xl text-ink">Gabriella</p>
                <p className="mt-2 max-w-xs">
                  A portfolio project: a fashion sales assistant grounded in a live catalogue and store inventory.
                </p>
              </div>
              <div className="space-y-2">
                <p className="eyebrow">Shop</p>
                <Link href="/shop?sort=newest" className="block hover:text-ink">New in</Link>
                <Link href="/shop?on_sale=true" className="block hover:text-ink">Sale</Link>
                <Link href="/shop?occasion=wedding" className="block hover:text-ink">Wedding edit</Link>
              </div>
              <div className="space-y-2">
                <p className="eyebrow">About this demo</p>
                <p>Brands, products, stores and stock are simulated. No real retailer is affiliated.</p>
              </div>
            </div>
          </footer>
        </Providers>
      </body>
    </html>
  );
}
