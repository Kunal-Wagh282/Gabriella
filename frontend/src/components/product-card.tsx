import Image from "next/image";
import Link from "next/link";

import { Badge, Price, Skeleton } from "@/components/ui";
import { cn, discountPercent } from "@/lib/format";
import type { ProductSummary } from "@/lib/types";

export function ProductCard({ product, storeSelected }: { product: ProductSummary; storeSelected: boolean }) {
  const off = discountPercent(product.price, product.mrp);
  return (
    <Link href={`/product/${product.slug}`} className="focus-ring group block">
      <div className="relative aspect-[4/5] overflow-hidden bg-sand">
        {product.image && (
          <Image
            src={product.image.url}
            alt={product.image.alt}
            width={640}
            height={800}
            className={cn(
              "h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.03]",
              !product.in_stock && "opacity-60",
            )}
          />
        )}
        <div className="absolute left-2 top-2 flex flex-col items-start gap-1">
          {off > 0 && <Badge tone="sale">−{off}%</Badge>}
          {!product.in_stock && <Badge tone="dark">{storeSelected ? "Not in your store" : "Sold out"}</Badge>}
        </div>
      </div>
      <div className="mt-3 space-y-1">
        <p className="eyebrow">{product.brand}</p>
        <h3 className="text-sm leading-snug group-hover:underline group-hover:underline-offset-4">{product.name}</h3>
        <div className="flex items-center gap-2 text-xs text-muted">
          <span className="size-2.5 rounded-full border border-black/10" style={{ background: product.colour_hex }} />
          {product.colour}
        </div>
        <Price price={product.price} mrp={product.mrp} className="pt-1 text-sm" />
        <p className="pt-0.5 text-[11px] tracking-wide text-muted">
          {product.sizes.map((s, i) => (
            <span key={s.variant_id} className={cn(!s.in_stock && "text-muted/45 line-through")}>
              {s.size.replace("UK ", "")}
              {i < product.sizes.length - 1 && <span className="text-muted/40"> · </span>}
            </span>
          ))}
        </p>
      </div>
    </Link>
  );
}

export function ProductCardSkeleton() {
  return (
    <div>
      <Skeleton className="aspect-[4/5]" />
      <Skeleton className="mt-3 h-3 w-1/3" />
      <Skeleton className="mt-2 h-4 w-3/4" />
      <Skeleton className="mt-2 h-4 w-1/4" />
    </div>
  );
}

export function ProductGrid({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-2 gap-x-4 gap-y-10 md:grid-cols-3 xl:grid-cols-4">{children}</div>;
}
