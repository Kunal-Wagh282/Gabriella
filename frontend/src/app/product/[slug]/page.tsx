import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { ProductCard, ProductGrid } from "@/components/product-card";
import { PurchasePanel } from "@/components/purchase-panel";
import { Badge, Price, Skeleton } from "@/components/ui";
import { cn, titleCase } from "@/lib/format";
import { ApiError, apiGet, selectedStoreId } from "@/lib/server-api";
import type { Page, ProductDetail, ProductSummary, SimilarProduct, Store } from "@/lib/types";

const FORMALITY = ["", "Loungewear", "Casual", "Smart casual", "Business", "Formal"];

export default function ProductPage({ params }: PageProps<"/product/[slug]">) {
  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6">
      <Suspense fallback={<ProductSkeleton />}>
        <ProductView params={params} />
      </Suspense>
    </div>
  );
}

async function ProductView({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const storeId = await selectedStoreId();
  let product: ProductDetail;
  try {
    product = await apiGet<ProductDetail>(`/products/${encodeURIComponent(slug)}`, { store_id: storeId });
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
    throw err;
  }
  const [stores, related] = await Promise.all([
    apiGet<Store[]>("/stores"),
    apiGet<Page<ProductSummary>>("/products", {
      category: product.category.slug,
      gender: product.gender === "unisex" ? undefined : [product.gender, "unisex"],
      store_id: storeId,
      page_size: 5,
    }),
  ]);
  const others = related.items.filter((p) => p.id !== product.id).slice(0, 4);

  const details: [string, string][] = [
    ["Material", product.material],
    ["Fit", product.fit],
    ["Pattern", titleCase(product.pattern)],
    ["Colour", [product.colour, ...product.secondary_colours].join(", ")],
    ["Formality", FORMALITY[product.formality]],
    ["Occasions", product.occasions.map(titleCase).join(", ")],
    ["Season", product.seasons.map(titleCase).join(", ")],
    ["Style code", product.style_code],
  ];

  return (
    <>
      <nav className="text-xs text-muted" aria-label="Breadcrumb">
        <Link href="/shop" className="hover:text-ink">Shop</Link>
        {product.parent_category && (
          <>
            {" / "}
            <Link href={`/shop?category=${product.parent_category.slug}`} className="hover:text-ink">{product.parent_category.name}</Link>
          </>
        )}
        {" / "}
        <Link href={`/shop?category=${product.category.slug}`} className="hover:text-ink">{product.category.name}</Link>
      </nav>

      <div className="mt-6 grid gap-10 lg:grid-cols-[1.25fr_1fr] lg:gap-16">
        <div className="grid grid-cols-2 gap-2">
          {product.images.map((img, i) => (
            <div key={img.url} className={cn("relative overflow-hidden bg-sand", i === 0 ? "col-span-2 aspect-[4/5] sm:col-span-1" : "aspect-[4/5] sm:aspect-auto")}>
              <Image src={img.url} alt={img.alt} width={640} height={800} priority={i === 0} className="h-full w-full object-cover" />
              {img.kind === "swatch" && <span className="absolute bottom-3 left-3 eyebrow bg-ivory/80 px-2 py-1">Fabric</span>}
            </div>
          ))}
        </div>

        <div className="lg:sticky lg:top-28 lg:self-start">
          <p className="eyebrow">{product.brand.name}</p>
          <h1 className="mt-2 font-display text-4xl font-medium leading-tight tracking-tight sm:text-5xl">{product.name}</h1>
          <Price price={product.price} mrp={product.mrp} className="mt-4 text-lg" />
          <p className="mt-1 text-xs text-muted">Inclusive of all taxes</p>

          {!product.is_active && (
            <Badge tone="dark" className="mt-4">Discontinued</Badge>
          )}

          <div className="mt-6">
            <p className="text-sm">
              <span className="eyebrow text-ink">Colour</span> <span className="ml-2">{product.colour}</span>
            </p>
            <div className="mt-3 flex gap-2">
              {product.colourways.map((c) => (
                <Link
                  key={c.id}
                  href={`/product/${c.slug}`}
                  title={c.colour}
                  aria-label={c.colour}
                  aria-current={c.id === product.id || undefined}
                  className={cn("focus-ring size-8 rounded-full border border-black/10", c.id === product.id && "ring-2 ring-ink ring-offset-2 ring-offset-ivory")}
                  style={{ background: c.colour_hex }}
                />
              ))}
            </div>
          </div>

          <div className="mt-8">
            <PurchasePanel productSlug={product.slug} variants={product.variants} stores={stores} selectedStoreId={storeId ?? null} />
          </div>

          <div className="mt-10 border-t border-line pt-6">
            <p className="text-sm leading-relaxed text-ink/85">{product.description}</p>
            <div className="mt-4 flex flex-wrap gap-1.5">
              {product.style_tags.map((t) => (
                <Link key={t} href={`/shop?style=${t}`} className="rounded-full border border-line px-3 py-1 text-xs hover:border-ink">
                  {titleCase(t)}
                </Link>
              ))}
            </div>
            <dl className="mt-6 grid grid-cols-[110px_1fr] gap-y-2 text-sm">
              {details.map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="text-muted">{k}</dt>
                  <dd>{v}</dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      </div>

      <Suspense fallback={null}>
        <SimilarRail productId={product.id} storeId={storeId} storeName={stores.find((s) => s.id === storeId)?.city} />
      </Suspense>

      {others.length > 0 && (
        <section className="mt-24">
          <div className="mb-6 flex items-end justify-between">
            <h2 className="font-display text-3xl">More {product.category.name.toLowerCase()}</h2>
            <Link href={`/shop?category=${product.category.slug}`} className="text-sm underline underline-offset-4">View all</Link>
          </div>
          <ProductGrid>
            {others.map((p) => (
              <ProductCard key={p.id} product={p} storeSelected={Boolean(storeId)} />
            ))}
          </ProductGrid>
        </section>
      )}
    </>
  );
}

/** Substitutes ranked by CLIP text + image similarity, restricted to what's in stock here. */
async function SimilarRail({ productId, storeId, storeName }: { productId: number; storeId?: number; storeName?: string }) {
  const similar = await apiGet<SimilarProduct[]>(`/products/${productId}/similar`, {
    store_id: storeId,
    in_stock: true,
    limit: 4,
  });
  if (!similar.length) return null;
  return (
    <section className="mt-24">
      <div className="mb-6">
        <h2 className="font-display text-3xl">Similar pieces{storeName ? ` in stock at ${storeName}` : " in stock"}</h2>
        <p className="mt-1 text-sm text-muted">Matched on look and description, then checked against live stock.</p>
      </div>
      <ProductGrid>
        {similar.map(({ product, reasons }) => (
          <div key={product.id}>
            <ProductCard product={product} storeSelected={Boolean(storeId)} />
            {reasons.length > 0 && (
              <p className="mt-2 text-[11px] leading-relaxed text-muted">{reasons.slice(0, 3).join(" · ")}</p>
            )}
          </div>
        ))}
      </ProductGrid>
    </section>
  );
}

function ProductSkeleton() {
  return (
    <div className="mt-10 grid gap-10 lg:grid-cols-[1.25fr_1fr] lg:gap-16">
      <Skeleton className="aspect-[4/5]" />
      <div className="space-y-4">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-12 w-3/4" />
        <Skeleton className="h-6 w-32" />
        <Skeleton className="mt-8 h-24 w-full" />
      </div>
    </div>
  );
}
