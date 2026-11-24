"use client";

import { Check, MessageCircle, ShoppingBag } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui";
import { errorMessage, useAddToCart } from "@/lib/commerce";
import { cn, stockLabel } from "@/lib/format";
import type { Store, Variant } from "@/lib/types";

export function PurchasePanel({
  productSlug,
  variants,
  stores,
  selectedStoreId,
}: {
  variants: Variant[];
  stores: Store[];
  selectedStoreId: number | null;
  productSlug: string;
}) {
  const [variantId, setVariantId] = useState<number | null>(null);
  const variant = variants.find((v) => v.id === variantId) ?? null;
  const store = stores.find((s) => s.id === selectedStoreId) ?? null;
  const add = useAddToCart();
  // Buy from the selected store when it has the size, otherwise from the online store.
  const online = stores.find((s) => s.is_online) ?? null;
  const fulfilFrom = (v: Variant): Store | null => {
    const at = (id: number | undefined) => v.stock.find((x) => x.store_id === id)?.on_hand ?? 0;
    if (store && at(store.id) > 0) return store;
    if (online && at(online.id) > 0) return online;
    return null;
  };
  const source = variant ? fulfilFrom(variant) : null;
  const qtyHere = (v: Variant) =>
    selectedStoreId === null ? v.stock.reduce((n, s) => n + s.on_hand, 0) : (v.available_at_selected_store ?? 0);

  return (
    <div className="space-y-6">
      <fieldset>
        <legend className="flex w-full items-center justify-between">
          <span className="eyebrow text-ink">Size</span>
          <span className="text-xs text-muted">{store ? `Stock at ${store.city}` : "Stock across all stores"}</span>
        </legend>
        <div className="mt-3 grid grid-cols-4 gap-2 sm:grid-cols-6">
          {variants.map((v) => {
            const qty = qtyHere(v);
            return (
              <button
                key={v.id}
                type="button"
                onClick={() => {
                  setVariantId(v.id);
                  add.reset();
                }}
                aria-pressed={variantId === v.id}
                aria-label={`Size ${v.size}${qty === 0 ? ", sold out" : qty <= 3 ? `, only ${qty} left` : ""}`}
                className={cn(
                  "focus-ring relative h-12 border text-sm transition-colors",
                  variantId === v.id ? "border-ink bg-ink text-ivory" : "border-line bg-white hover:border-ink",
                  qty === 0 && variantId !== v.id && "text-muted/60",
                )}
              >
                <span className={cn(qty === 0 && "line-through decoration-muted/50")}>{v.size.replace("UK ", "UK")}</span>
                {qty > 0 && qty <= 3 && <span className="absolute right-1 top-1 size-1.5 rounded-full bg-warn" aria-hidden />}
              </button>
            );
          })}
        </div>
      </fieldset>

      {variant ? (
        <div className="border border-line bg-white p-4">
          <p className="flex items-center justify-between text-sm">
            <span>
              Size <strong className="font-semibold">{variant.size}</strong>
              {store && (
                <>
                  {" "}at {store.city}:{" "}
                  <StockText qty={variant.available_at_selected_store ?? 0} />
                </>
              )}
            </span>
            <span className="font-mono text-[11px] text-muted">{variant.sku}</span>
          </p>
          <ul className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs sm:grid-cols-3">
            {stores.map((s) => {
              const qty = variant.stock.find((x) => x.store_id === s.id)?.on_hand ?? 0;
              return (
                <li key={s.id} className={cn("flex justify-between gap-2", s.id === selectedStoreId && "font-semibold")}>
                  <span className="truncate">{s.city}</span>
                  <StockText qty={qty} short />
                </li>
              );
            })}
          </ul>
        </div>
      ) : (
        <p className="text-xs text-muted">Select a size to see stock in every store.</p>
      )}

      <div className="grid gap-3">
        <Button
          size="lg"
          disabled={!variant || !source || add.isPending}
          onClick={() => {
            if (variant && source) add.mutate([{ variant_id: variant.id, store_id: source.id, source: "product" }]);
          }}
        >
          {add.isSuccess ? <Check className="size-4" /> : <ShoppingBag className="size-4" />}
          {!variant
            ? "Select a size"
            : !source
              ? "Sold out in this size"
              : add.isSuccess
                ? "Added to bag"
                : source.is_online && store?.id !== source.id
                  ? "Add to bag · ships from online"
                  : `Add to bag · ${source.city}`}
        </Button>
        {add.isError && !String(add.error).includes("sign in") && (
          <p role="alert" className="text-xs text-sale">{errorMessage(add.error)}</p>
        )}
        <Link
          href={`/chat?product=${encodeURIComponent(productSlug)}`}
          className="focus-ring inline-flex h-13 items-center justify-center gap-2 border border-ink px-8 text-sm font-medium tracking-wide hover:bg-ink hover:text-ivory"
        >
          <MessageCircle className="size-4" /> Style this with Gabriella
        </Link>
      </div>
    </div>
  );
}

function StockText({ qty, short = false }: { qty: number; short?: boolean }) {
  const { label, tone } = stockLabel(qty);
  const text = short ? (qty === 0 ? "—" : qty <= 3 ? `${qty} left` : "In stock") : label;
  return <span className={cn(tone === "ok" && "text-ok", tone === "low" && "text-warn", tone === "none" && "text-muted")}>{text}</span>;
}
