"use client";

import { Check, Plus, ShoppingBag } from "lucide-react";
import Image from "next/image";
import Link from "next/link";

import { Badge, Price } from "@/components/ui";
import { ROLE_LABEL, type ChatGroup, type ChatItem } from "@/lib/chat";
import { errorMessage, useAddToCart } from "@/lib/commerce";
import { cn, formatINR } from "@/lib/format";

function ItemCard({ item, storeId }: { item: ChatItem; storeId: number | null }) {
  const { product, variant } = item;
  const soldOut = variant ? !variant.in_stock : !product.in_stock;
  const add = useAddToCart();
  return (
    <div className="flex w-44 shrink-0 flex-col border border-line bg-white transition-shadow hover:shadow-lg sm:w-48">
      <Link href={`/product/${product.slug}`} className="focus-ring group relative block aspect-[4/5] overflow-hidden bg-sand">
        {product.image && (
          <Image
            src={product.image.url}
            alt={product.image.alt}
            width={320}
            height={400}
            className={cn("h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.04]", soldOut && "opacity-50")}
          />
        )}
        <Badge tone="neutral" className="absolute left-2 top-2">{ROLE_LABEL[item.role]}</Badge>
        {soldOut && <Badge tone="dark" className="absolute bottom-2 left-2">Just sold out</Badge>}
      </Link>
      <div className="flex flex-1 flex-col gap-1 p-3">
        <p className="eyebrow">{product.brand}</p>
        <Link href={`/product/${product.slug}`} className="text-[13px] leading-snug hover:underline">{product.name}</Link>
        <p className="flex items-center gap-1.5 text-[11px] text-muted">
          <span className="size-2 rounded-full border border-black/10" style={{ background: product.colour_hex }} />
          {product.colour}
        </p>
        <div className="mt-auto flex items-center justify-between pt-2">
          <Price price={product.price} mrp={product.mrp} className="text-[13px]" />
          {variant && (
            <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-semibold", variant.in_stock ? "bg-ok/10 text-ok" : "bg-stone text-muted")}>
              {variant.size}
            </span>
          )}
        </div>
        {variant && variant.in_stock ? (
          <button
            onClick={() => add.mutate([{ variant_id: variant.id, store_id: storeId, source: "chat" }])}
            disabled={add.isPending || add.isSuccess}
            className="focus-ring mt-2 inline-flex h-8 items-center justify-center gap-1.5 border border-ink text-[11px] font-medium hover:bg-ink hover:text-ivory disabled:border-ok disabled:bg-ok/5 disabled:text-ok"
          >
            {add.isSuccess ? <Check className="size-3" /> : <Plus className="size-3" />}
            {add.isSuccess ? "In your bag" : `Add ${variant.size}`}
          </button>
        ) : (
          <Link href={`/product/${product.slug}`} className="mt-2 inline-flex h-8 items-center justify-center border border-line text-[11px] hover:border-ink">
            Choose size
          </Link>
        )}
        {add.isError && <p className="text-[10px] text-sale">{errorMessage(add.error)}</p>}
      </div>
    </div>
  );
}

export function RecommendationGroup({ group, storeId }: { group: ChatGroup; storeId: number | null }) {
  const add = useAddToCart();
  const buyable = group.items.filter((i) => i.variant?.in_stock);
  return (
    <section className="mt-4 border border-line bg-ivory/60 p-4">
      <div className="flex items-baseline justify-between gap-4">
        <div>
          <p className="eyebrow">{group.kind === "outfit" ? "Complete look" : group.kind === "alternatives" ? "Alternatives" : "Picks"}</p>
          <h3 className="mt-0.5 font-display text-2xl leading-tight">{group.title}</h3>
        </div>
        {group.kind === "outfit" && (
          <div className="shrink-0 text-right">
            <p className="text-xs text-muted">Total <span className="block text-base font-semibold text-ink tabular-nums">{formatINR(group.total)}</span></p>
            {buyable.length > 1 && (
              <button
                onClick={() => add.mutate(buyable.map((i) => ({ variant_id: i.variant!.id, store_id: storeId, source: "chat" as const })))}
                disabled={add.isPending || add.isSuccess}
                className="focus-ring mt-2 inline-flex h-8 items-center gap-1.5 bg-ink px-3 text-[11px] font-medium text-ivory disabled:bg-ok"
              >
                {add.isSuccess ? <Check className="size-3" /> : <ShoppingBag className="size-3" />}
                {add.isSuccess ? "Look added" : `Add look (${buyable.length})`}
              </button>
            )}
          </div>
        )}
      </div>
      {add.isError && <p className="mt-2 text-xs text-sale">{errorMessage(add.error)}</p>}
      <div className="-mx-4 mt-4 flex gap-3 overflow-x-auto px-4 pb-2">
        {group.items.map((item) => (
          <ItemCard key={item.product.id} item={item} storeId={storeId} />
        ))}
      </div>
      {group.items.some((i) => i.reason) && (
        <ul className="mt-3 space-y-1.5 text-[13px] leading-relaxed">
          {group.items
            .filter((i) => i.reason)
            .map((i) => (
              <li key={i.product.id} className="flex gap-2">
                <span className="w-20 shrink-0 text-[11px] font-semibold uppercase tracking-wide text-muted">{ROLE_LABEL[i.role]}</span>
                <span className="text-ink/85">{i.reason}</span>
              </li>
            ))}
        </ul>
      )}
      {group.note && <p className="mt-3 text-xs text-muted">{group.note}</p>}
    </section>
  );
}
