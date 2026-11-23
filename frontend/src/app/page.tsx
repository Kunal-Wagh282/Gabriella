import { ArrowRight, MessageCircle, PackageCheck, Shirt } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { Suspense } from "react";

import { ProductCard, ProductCardSkeleton, ProductGrid } from "@/components/product-card";
import { Skeleton } from "@/components/ui";
import { apiGet, selectedStoreId } from "@/lib/server-api";
import type { Facets, Page, ProductSummary } from "@/lib/types";

const STEPS = [
  {
    icon: MessageCircle,
    title: "Tell her the plan",
    body: "“A casual dinner under ₹5,000” or “what goes with my navy shirt?” — in your own words, or with a photo.",
  },
  {
    icon: PackageCheck,
    title: "She checks the shelves",
    body: "Every suggestion is validated against live stock for your size at your chosen store before you see it.",
  },
  {
    icon: Shirt,
    title: "Get the whole outfit",
    body: "Top, bottom, shoes and a finishing touch, with a short note on why they work together.",
  },
];

export default function Home() {
  return (
    <>
      <section className="mx-auto grid max-w-7xl items-center gap-12 px-4 pb-16 pt-12 sm:px-6 lg:grid-cols-[1fr_1.1fr] lg:pt-20">
        <div>
          <p className="eyebrow">An AI stylist that knows the stockroom</p>
          <h1 className="mt-5 font-display text-6xl font-medium leading-[0.95] tracking-tight sm:text-7xl">
            Dressed by someone who knows <em className="font-normal">what&apos;s on the shelf.</em>
          </h1>
          <p className="mt-6 max-w-md text-base leading-relaxed text-muted">
            Gabriella recommends complete outfits from 500 pieces across twelve brands — only what&apos;s actually in
            stock, in your size, at the store you shop from.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link href="/shop" className="focus-ring inline-flex h-12 items-center gap-2 bg-ink px-7 text-sm font-medium text-ivory hover:bg-ink/85">
              Shop the collection <ArrowRight className="size-4" />
            </Link>
            <Link href="/chat" className="focus-ring inline-flex h-12 items-center gap-2 border border-ink px-7 text-sm hover:bg-ink hover:text-ivory">
              <MessageCircle className="size-4" /> Chat with Gabriella
            </Link>
          </div>
        </div>
        <Suspense fallback={<HeroSkeleton />}>
          <HeroCollage />
        </Suspense>
      </section>

      <section className="border-y border-line bg-sand/60">
        <div className="mx-auto grid max-w-7xl gap-10 px-4 py-14 sm:px-6 md:grid-cols-3">
          {STEPS.map(({ icon: Icon, title, body }, i) => (
            <div key={title}>
              <div className="flex items-center gap-3">
                <span className="font-display text-3xl text-muted">0{i + 1}</span>
                <Icon className="size-5" strokeWidth={1.5} />
              </div>
              <h2 className="mt-3 text-base font-semibold">{title}</h2>
              <p className="mt-2 text-sm leading-relaxed text-muted">{body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-4 pt-20 sm:px-6">
        <h2 className="font-display text-4xl">Shop by category</h2>
        <Suspense fallback={<div className="mt-8 grid grid-cols-2 gap-3 md:grid-cols-4">{Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="aspect-[4/5]" />)}</div>}>
          <CategoryTiles />
        </Suspense>
      </section>

      <section className="mx-auto max-w-7xl px-4 pt-20 sm:px-6">
        <div className="mb-8 flex items-end justify-between">
          <h2 className="font-display text-4xl">New in</h2>
          <Link href="/shop?sort=newest" className="text-sm underline underline-offset-4">See everything new</Link>
        </div>
        <Suspense fallback={<ProductGrid>{Array.from({ length: 8 }, (_, i) => <ProductCardSkeleton key={i} />)}</ProductGrid>}>
          <NewArrivals />
        </Suspense>
      </section>
    </>
  );
}

async function HeroCollage() {
  const [shirts, chinos, shoes] = await Promise.all(
    ["casual-shirts", "chinos", "loafers"].map((category) =>
      apiGet<Page<ProductSummary>>("/products", { category, gender: "men", page_size: 1, in_stock: true }),
    ),
  );
  const picks = [shirts.items[0], chinos.items[0], shoes.items[0]].filter(Boolean);
  return (
    <div className="relative grid grid-cols-2 gap-3">
      {picks.map((p, i) => (
        <Link
          key={p.id}
          href={`/product/${p.slug}`}
          className={i === 0 ? "row-span-2 overflow-hidden bg-sand" : "overflow-hidden bg-sand"}
        >
          {p.image && <Image src={p.image.url} alt={p.image.alt} width={640} height={800} priority className="h-full w-full object-cover transition-transform duration-700 hover:scale-[1.03]" />}
        </Link>
      ))}
      <div className="absolute -bottom-5 left-6 max-w-[16rem] border border-line bg-ivory p-4 shadow-lg">
        <p className="eyebrow">Gabriella suggests</p>
        <p className="mt-1 font-display text-lg leading-snug">
          {picks.map((p) => `${p.colour.toLowerCase()} ${p.category.toLowerCase().replace(/s$/, "")}`).join(", ")}
        </p>
      </div>
    </div>
  );
}

async function CategoryTiles() {
  const facets = await apiGet<Facets>("/catalogue/facets");
  const groups = facets.categories.filter((g) => g.product_count > 0).slice(0, 8);
  const covers = await Promise.all(
    groups.map((g) => apiGet<Page<ProductSummary>>("/products", { category: g.slug, page_size: 1 })),
  );
  return (
    <div className="mt-8 grid grid-cols-2 gap-3 md:grid-cols-4">
      {groups.map((g, i) => {
        const cover = covers[i].items[0];
        return (
          <Link key={g.id} href={`/shop?category=${g.slug}`} className="focus-ring group relative aspect-[4/5] overflow-hidden bg-sand">
            {cover?.image && <Image src={cover.image.url} alt="" width={640} height={800} className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.04]" />}
            <div className="absolute inset-x-0 bottom-0 flex items-end justify-between bg-gradient-to-t from-ink/55 to-transparent p-4 pt-16 text-ivory">
              <span className="font-display text-2xl">{g.name}</span>
              <span className="text-xs">{g.product_count}</span>
            </div>
          </Link>
        );
      })}
    </div>
  );
}

async function NewArrivals() {
  const storeId = await selectedStoreId();
  const page = await apiGet<Page<ProductSummary>>("/products", { sort: "newest", page_size: 8, store_id: storeId });
  return (
    <ProductGrid>
      {page.items.map((p) => (
        <ProductCard key={p.id} product={p} storeSelected={Boolean(storeId)} />
      ))}
    </ProductGrid>
  );
}

function HeroSkeleton() {
  return (
    <div className="grid grid-cols-2 gap-3">
      <Skeleton className="row-span-2 aspect-[4/5] h-full" />
      <Skeleton className="aspect-[4/5]" />
      <Skeleton className="aspect-[4/5]" />
    </div>
  );
}
