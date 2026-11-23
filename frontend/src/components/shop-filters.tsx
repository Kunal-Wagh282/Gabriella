import { Check, X } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { cn, formatINR, titleCase } from "@/lib/format";
import { hrefWith, toArray, type RawSearchParams } from "@/lib/search-params";
import type { CategoryNode, Facets } from "@/lib/types";

const PRICE_BANDS: { label: string; min?: number; max?: number }[] = [
  { label: `Under ${formatINR(1000)}`, max: 999 },
  { label: `${formatINR(1000)} – ${formatINR(2500)}`, min: 1000, max: 2500 },
  { label: `${formatINR(2500)} – ${formatINR(5000)}`, min: 2500, max: 5000 },
  { label: `Over ${formatINR(5000)}`, min: 5000 },
];
const GENDER_LABEL: Record<string, string> = { men: "Men", women: "Women", unisex: "Unisex" };

function toggle(sp: RawSearchParams, key: string, value: string): string {
  const current = toArray(sp[key]);
  const next = current.includes(value) ? current.filter((v) => v !== value) : [...current, value];
  return hrefWith(sp, { [key]: next });
}

function Section({ title, children, open = true }: { title: string; children: ReactNode; open?: boolean }) {
  return (
    <details open={open} className="group border-b border-line py-4">
      <summary className="eyebrow flex cursor-pointer list-none items-center justify-between text-ink">
        {title}
        <span className="text-muted transition-transform group-open:rotate-45">+</span>
      </summary>
      <div className="mt-3">{children}</div>
    </details>
  );
}

function CheckLink({ href, active, children, count }: { href: string; active: boolean; children: ReactNode; count?: number }) {
  return (
    <Link href={href} scroll={false} className="focus-ring flex items-center gap-2.5 py-1 text-sm hover:text-ink" aria-current={active || undefined}>
      <span className={cn("grid size-4 shrink-0 place-items-center border", active ? "border-ink bg-ink text-ivory" : "border-line bg-white")}>
        {active && <Check className="size-3" strokeWidth={3} />}
      </span>
      <span className={cn(active ? "text-ink" : "text-ink/80")}>{children}</span>
      {count !== undefined && <span className="ml-auto text-xs text-muted">{count}</span>}
    </Link>
  );
}

function CategoryTree({ nodes, sp }: { nodes: CategoryNode[]; sp: RawSearchParams }) {
  const active = toArray(sp.category);
  return (
    <ul className="space-y-1">
      {nodes.map((group) => (
        <li key={group.id}>
          <CheckLink href={toggle(sp, "category", group.slug)} active={active.includes(group.slug)} count={group.product_count}>
            {group.name}
          </CheckLink>
          {(active.includes(group.slug) || group.children.some((c) => active.includes(c.slug))) && (
            <ul className="ml-6 mt-1 space-y-0.5">
              {group.children.map((c) => (
                <li key={c.id}>
                  <CheckLink href={toggle(sp, "category", c.slug)} active={active.includes(c.slug)} count={c.product_count}>
                    {c.name}
                  </CheckLink>
                </li>
              ))}
            </ul>
          )}
        </li>
      ))}
    </ul>
  );
}

export function ShopFilters({ facets, sp, storeName }: { facets: Facets; sp: RawSearchParams; storeName: string | null }) {
  const sizes = toArray(sp.size);
  const colours = toArray(sp.colour).map((c) => c.toLowerCase());
  const inStock = sp.in_stock === "true";
  return (
    <div>
      <Section title="Availability">
        <CheckLink href={hrefWith(sp, { in_stock: inStock ? null : "true" })} active={inStock}>
          {storeName ? `In stock at ${storeName}` : "In stock online or in store"}
        </CheckLink>
        <CheckLink href={hrefWith(sp, { on_sale: sp.on_sale === "true" ? null : "true" })} active={sp.on_sale === "true"}>
          On sale
        </CheckLink>
      </Section>
      <Section title="Category">
        <CategoryTree nodes={facets.categories} sp={sp} />
      </Section>
      <Section title="Shop for">
        {facets.genders.map((g) => (
          <CheckLink key={g.value} href={toggle(sp, "gender", g.value)} active={toArray(sp.gender).includes(g.value)} count={g.count}>
            {GENDER_LABEL[g.value] ?? g.value}
          </CheckLink>
        ))}
      </Section>
      <Section title="Size">
        <div className="flex flex-wrap gap-1.5">
          {facets.sizes.map((s) => (
            <Link
              key={s}
              href={toggle(sp, "size", s)}
              scroll={false}
              className={cn(
                "focus-ring min-w-11 border px-2 py-1.5 text-center text-xs",
                sizes.includes(s) ? "border-ink bg-ink text-ivory" : "border-line bg-white hover:border-ink",
              )}
            >
              {s}
            </Link>
          ))}
        </div>
      </Section>
      <Section title="Colour">
        <div className="grid grid-cols-6 gap-2">
          {facets.colours.map((c) => {
            const active = colours.includes(c.name.toLowerCase());
            return (
              <Link
                key={c.name}
                href={toggle(sp, "colour", c.name.toLowerCase())}
                scroll={false}
                title={`${c.name} (${c.count})`}
                aria-label={c.name}
                className={cn("focus-ring size-7 rounded-full border border-black/10", active && "ring-2 ring-ink ring-offset-2 ring-offset-ivory")}
                style={{ background: c.hex }}
              />
            );
          })}
        </div>
      </Section>
      <Section title="Price">
        {PRICE_BANDS.map((band) => {
          const active = sp.min_price === (band.min?.toString() ?? undefined) && sp.max_price === (band.max?.toString() ?? undefined);
          return (
            <CheckLink
              key={band.label}
              href={hrefWith(sp, active ? { min_price: null, max_price: null } : { min_price: band.min?.toString() ?? null, max_price: band.max?.toString() ?? null })}
              active={active}
            >
              {band.label}
            </CheckLink>
          );
        })}
      </Section>
      <Section title="Occasion" open={false}>
        {facets.occasions.map((o) => (
          <CheckLink key={o.value} href={toggle(sp, "occasion", o.value)} active={toArray(sp.occasion).includes(o.value)} count={o.count}>
            {titleCase(o.value)}
          </CheckLink>
        ))}
      </Section>
      <Section title="Style" open={false}>
        {facets.style_tags.map((o) => (
          <CheckLink key={o.value} href={toggle(sp, "style", o.value)} active={toArray(sp.style).includes(o.value)} count={o.count}>
            {titleCase(o.value)}
          </CheckLink>
        ))}
      </Section>
      <Section title="Brand" open={false}>
        {facets.brands.map((b) => (
          <CheckLink key={b.value} href={toggle(sp, "brand", b.value)} active={toArray(sp.brand).includes(b.value)} count={b.count}>
            {titleCase(b.value.replaceAll("-", " ")).replace(" And ", " & ").replace("Palette Co", "Palette & Co")}
          </CheckLink>
        ))}
      </Section>
    </div>
  );
}

export function ActiveFilters({ sp, facets }: { sp: RawSearchParams; facets: Facets }) {
  const categoryName = new Map<string, string>();
  for (const g of facets.categories) {
    categoryName.set(g.slug, g.name);
    for (const c of g.children) categoryName.set(c.slug, c.name);
  }
  const chips: { label: string; href: string }[] = [];
  const add = (key: string, label: (v: string) => string) =>
    toArray(sp[key]).forEach((v) => chips.push({ label: label(v), href: toggle(sp, key, v) }));
  add("category", (v) => categoryName.get(v) ?? v);
  add("gender", (v) => GENDER_LABEL[v] ?? v);
  add("size", (v) => `Size ${v}`);
  add("colour", titleCase);
  add("occasion", titleCase);
  add("style", titleCase);
  add("brand", (v) => titleCase(v.replaceAll("-", " ")));
  if (sp.min_price || sp.max_price) {
    const label = sp.min_price && sp.max_price ? `${formatINR(+sp.min_price)} – ${formatINR(+sp.max_price)}` : sp.max_price ? `Under ${formatINR(+sp.max_price + 1)}` : `Over ${formatINR(+sp.min_price!)}`;
    chips.push({ label, href: hrefWith(sp, { min_price: null, max_price: null }) });
  }
  if (sp.in_stock === "true") chips.push({ label: "In stock", href: hrefWith(sp, { in_stock: null }) });
  if (sp.on_sale === "true") chips.push({ label: "On sale", href: hrefWith(sp, { on_sale: null }) });
  if (sp.q) chips.push({ label: `“${sp.q}”`, href: hrefWith(sp, { q: null }) });
  if (!chips.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      {chips.map((c) => (
        <Link key={c.label + c.href} href={c.href} scroll={false} className="focus-ring inline-flex items-center gap-1.5 rounded-full border border-line bg-white px-3 py-1 text-xs hover:border-ink">
          {c.label} <X className="size-3" />
        </Link>
      ))}
      <Link href="/shop" className="text-xs text-muted underline underline-offset-4 hover:text-ink">
        Clear all
      </Link>
    </div>
  );
}
