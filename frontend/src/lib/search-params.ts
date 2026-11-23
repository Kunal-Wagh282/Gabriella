import type { SortKey } from "@/lib/types";

export type RawSearchParams = Record<string, string | string[] | undefined>;

export const FILTER_KEYS = [
  "q",
  "category",
  "gender",
  "brand",
  "colour",
  "size",
  "occasion",
  "style",
  "min_price",
  "max_price",
  "in_stock",
  "on_sale",
] as const;

export const SORTS: { value: SortKey; label: string }[] = [
  { value: "relevance", label: "Best match" },
  { value: "featured", label: "Featured" },
  { value: "newest", label: "New in" },
  { value: "price_asc", label: "Price: low to high" },
  { value: "price_desc", label: "Price: high to low" },
];

export function toArray(value: string | string[] | undefined): string[] {
  if (value === undefined) return [];
  return (Array.isArray(value) ? value : [value]).filter(Boolean);
}

export function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/** Converts page search params into the API's query shape. */
export function catalogueQuery(sp: RawSearchParams, storeId: number | undefined) {
  const sort = first(sp.sort);
  const page = Number(first(sp.page) ?? 1);
  return {
    q: first(sp.q),
    category: toArray(sp.category),
    gender: toArray(sp.gender),
    brand: toArray(sp.brand),
    colour: toArray(sp.colour),
    size: toArray(sp.size),
    occasion: toArray(sp.occasion),
    style: toArray(sp.style),
    min_price: first(sp.min_price),
    max_price: first(sp.max_price),
    in_stock: first(sp.in_stock) === "true" ? true : undefined,
    on_sale: first(sp.on_sale) === "true" ? true : undefined,
    store_id: storeId,
    sort: SORTS.some((s) => s.value === sort) ? sort : first(sp.q) ? "relevance" : "featured",
    page: Number.isInteger(page) && page > 0 ? page : 1,
    page_size: 24,
  };
}

export function hrefWith(sp: RawSearchParams, changes: Record<string, string | string[] | null>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(sp)) {
    for (const v of toArray(value)) params.append(key, v);
  }
  for (const [key, value] of Object.entries(changes)) {
    params.delete(key);
    for (const v of value === null ? [] : Array.isArray(value) ? value : [value]) params.append(key, v);
  }
  if (!("page" in changes)) params.delete("page");
  const qs = params.toString();
  return qs ? `/shop?${qs}` : "/shop";
}
