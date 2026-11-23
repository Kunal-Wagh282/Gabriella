import Image from "next/image";
import Link from "next/link";

import { Badge, Price } from "@/components/ui";
import { ROLE_LABEL, type ChatGroup, type ChatItem } from "@/lib/chat";
import { cn, formatINR } from "@/lib/format";

function ItemCard({ item }: { item: ChatItem }) {
  const { product, variant } = item;
  const soldOut = variant ? !variant.in_stock : !product.in_stock;
  return (
    <Link
      href={`/product/${product.slug}`}
      className="focus-ring group flex w-44 shrink-0 flex-col border border-line bg-white transition-shadow hover:shadow-lg sm:w-48"
    >
      <div className="relative aspect-[4/5] overflow-hidden bg-sand">
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
      </div>
      <div className="flex flex-1 flex-col gap-1 p-3">
        <p className="eyebrow">{product.brand}</p>
        <p className="text-[13px] leading-snug">{product.name}</p>
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
      </div>
    </Link>
  );
}

export function RecommendationGroup({ group }: { group: ChatGroup }) {
  return (
    <section className="mt-4 border border-line bg-ivory/60 p-4">
      <div className="flex items-baseline justify-between gap-4">
        <div>
          <p className="eyebrow">{group.kind === "outfit" ? "Complete look" : group.kind === "alternatives" ? "Alternatives" : "Picks"}</p>
          <h3 className="mt-0.5 font-display text-2xl leading-tight">{group.title}</h3>
        </div>
        {group.kind === "outfit" && (
          <p className="shrink-0 text-right text-xs text-muted">
            Total <span className="block text-base font-semibold text-ink tabular-nums">{formatINR(group.total)}</span>
          </p>
        )}
      </div>
      <div className="-mx-4 mt-4 flex gap-3 overflow-x-auto px-4 pb-2">
        {group.items.map((item) => (
          <ItemCard key={item.product.id} item={item} />
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
