import { SlidersHorizontal } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { ProductCard, ProductCardSkeleton, ProductGrid } from "@/components/product-card";
import { ActiveFilters, ShopFilters } from "@/components/shop-filters";
import { SortSelect } from "@/components/sort-select";
import { Skeleton } from "@/components/ui";
import { cn } from "@/lib/format";
import { catalogueQuery, hrefWith, toArray, type RawSearchParams } from "@/lib/search-params";
import { apiGet, selectedStoreId } from "@/lib/server-api";
import type { Facets, SearchPage, Store } from "@/lib/types";

export const metadata: Metadata = { title: "Shop" };

export default function ShopPage({ searchParams }: PageProps<"/shop">) {
  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6">
      <Suspense fallback={<ShopSkeleton />}>
        <ShopResults searchParams={searchParams} />
      </Suspense>
    </div>
  );
}

function heading(sp: RawSearchParams, facets: Facets): string {
  if (typeof sp.q === "string" && sp.q) return `Results for “${sp.q}”`;
  const cats = toArray(sp.category);
  if (cats.length === 1) {
    for (const g of facets.categories) {
      if (g.slug === cats[0]) return g.name;
      const child = g.children.find((c) => c.slug === cats[0]);
      if (child) return child.name;
    }
  }
  if (sp.on_sale === "true") return "Sale";
  if (sp.sort === "newest") return "New in";
  return "All products";
}

async function ShopResults({ searchParams }: { searchParams: Promise<RawSearchParams> }) {
  const sp = await searchParams;
  const storeId = await selectedStoreId();
  const query = catalogueQuery(sp, storeId);
  const [results, facets, stores] = await Promise.all([
    apiGet<SearchPage>("/search", query),
    apiGet<Facets>("/catalogue/facets"),
    apiGet<Store[]>("/stores"),
  ]);
  const store = stores.find((s) => s.id === storeId) ?? null;
  const pages = Math.max(1, Math.ceil(results.total / results.page_size));

  return (
    <>
      <div className="flex flex-col gap-4 border-b border-line pb-6 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="eyebrow">{results.total} {results.total === 1 ? "piece" : "pieces"}</p>
          <h1 className="mt-1 font-display text-5xl font-medium leading-none tracking-tight">{heading(sp, facets)}</h1>
          <p className="mt-3 text-sm text-muted">
            {store ? (
              <>Availability shown for <span className="text-ink">{store.name}</span>, {store.city}.</>
            ) : (
              <>Showing stock across all stores. Choose a store at the top to see what&apos;s on its shelves.</>
            )}
          </p>
        </div>
        <SortSelect />
      </div>

      <div className="mt-4 space-y-3">
        {results.query && <SearchInsight results={results} />}
        <ActiveFilters sp={sp} facets={facets} />
      </div>

      <div className="mt-6 grid gap-10 lg:grid-cols-[240px_1fr]">
        <aside aria-label="Filters">
          <details className="group lg:hidden">
            <summary className="flex cursor-pointer list-none items-center gap-2 border border-line bg-white px-4 py-3 text-sm">
              <SlidersHorizontal className="size-4" /> Filters
            </summary>
            <div className="pt-2">
              <ShopFilters facets={facets} sp={sp} storeName={store?.city ?? null} />
            </div>
          </details>
          <div className="hidden lg:block">
            <ShopFilters facets={facets} sp={sp} storeName={store?.city ?? null} />
          </div>
        </aside>

        <section aria-label="Products">
          {results.items.length ? (
            <ProductGrid>
              {results.items.map((p) => (
                <ProductCard key={p.id} product={p} storeSelected={Boolean(store)} />
              ))}
            </ProductGrid>
          ) : (
            <div className="border border-dashed border-line px-6 py-20 text-center">
              <p className="font-display text-3xl">Nothing matches just yet</p>
              <p className="mx-auto mt-2 max-w-md text-sm text-muted">
                Try removing a filter{store ? " or switching to all stores" : ""}. Gabriella will be able to suggest close alternatives once chat arrives.
              </p>
              <Link href="/shop" className="mt-6 inline-block text-sm underline underline-offset-4">
                Clear filters
              </Link>
            </div>
          )}

          {pages > 1 && (
            <nav className="mt-14 flex items-center justify-center gap-1" aria-label="Pagination">
              {Array.from({ length: pages }, (_, i) => i + 1).map((n) => (
                <Link
                  key={n}
                  href={hrefWith(sp, { page: String(n) })}
                  aria-current={n === results.page ? "page" : undefined}
                  className={cn(
                    "focus-ring grid size-9 place-items-center text-sm",
                    n === results.page ? "bg-ink text-ivory" : "hover:bg-sand",
                  )}
                >
                  {n}
                </Link>
              ))}
            </nav>
          )}
        </section>
      </div>
    </>
  );
}

const KIND_ORDER = ["category", "colour", "gender", "size", "price", "sale", "occasion", "style"];

/** Shows how the free-text query was understood, and how honest the match is. */
function SearchInsight({ results }: { results: SearchPage }) {
  const { retrieval, interpretation } = results;
  const hard = interpretation
    .filter((i) => !["occasion", "style"].includes(i.kind))
    .sort((a, b) => KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind));
  const soft = interpretation.filter((i) => ["occasion", "style"].includes(i.kind));
  return (
    <div className="flex flex-col gap-2 border border-line bg-white/70 px-4 py-3 text-xs sm:flex-row sm:items-center sm:justify-between">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {retrieval.match === "related" && (
          <span className="font-medium text-warn">No exact matches — these are the closest pieces we have.</span>
        )}
        {hard.length > 0 && (
          <span className="flex flex-wrap items-center gap-1.5">
            <span className="text-muted">Filtered to</span>
            {hard.map((i) => (
              <span key={i.kind + i.value} className="rounded-full bg-ink px-2.5 py-0.5 text-ivory">{i.label}</span>
            ))}
          </span>
        )}
        {soft.length > 0 && (
          <span className="flex flex-wrap items-center gap-1.5">
            <span className="text-muted">Favouring</span>
            {soft.map((i) => (
              <span key={i.kind + i.value} className="rounded-full border border-line px-2.5 py-0.5">{i.label}</span>
            ))}
          </span>
        )}
      </div>
      <span className="shrink-0 text-muted" title="Full-text and CLIP text/image vectors, fused with reciprocal rank fusion">
        {retrieval.mode === "hybrid" ? "Hybrid search" : retrieval.mode === "lexical" ? "Keyword search" : "Filters"} · {Math.round(retrieval.latency_ms)} ms
      </span>
    </div>
  );
}

function ShopSkeleton() {
  return (
    <>
      <div className="border-b border-line pb-6">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="mt-3 h-12 w-72" />
      </div>
      <div className="mt-10 grid gap-10 lg:grid-cols-[240px_1fr]">
        <div className="hidden space-y-4 lg:block">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-5 w-full" />
          ))}
        </div>
        <ProductGrid>
          {Array.from({ length: 8 }, (_, i) => (
            <ProductCardSkeleton key={i} />
          ))}
        </ProductGrid>
      </div>
    </>
  );
}
