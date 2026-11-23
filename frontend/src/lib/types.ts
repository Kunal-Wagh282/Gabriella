// Mirrors the FastAPI response models in backend/app/schemas.

export type Gender = "men" | "women" | "unisex";
export type SortKey = "relevance" | "featured" | "newest" | "price_asc" | "price_desc";

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface Store {
  id: number;
  code: string;
  name: string;
  city: string;
  address: string;
  is_online: boolean;
}

export interface Brand {
  id: number;
  slug: string;
  name: string;
  tagline: string;
  price_tier: string;
}

export interface CategoryRef {
  id: number;
  slug: string;
  name: string;
  slot: string | null;
}

export interface CategoryNode extends CategoryRef {
  product_count: number;
  children: CategoryNode[];
}

export interface ProductImage {
  url: string;
  alt: string;
  kind: string;
}

export interface SizeAvailability {
  variant_id: number;
  size: string;
  in_stock: boolean;
}

export interface ProductSummary {
  id: number;
  slug: string;
  name: string;
  brand: string;
  category: string;
  gender: Gender;
  colour: string;
  colour_hex: string;
  price: number;
  mrp: number;
  image: ProductImage | null;
  sizes: SizeAvailability[];
  in_stock: boolean;
}

export interface StoreStock {
  store_id: number;
  store_code: string;
  on_hand: number;
}

export interface Variant {
  id: number;
  sku: string;
  size: string;
  stock: StoreStock[];
  available_at_selected_store: number | null;
}

export interface ProductDetail {
  id: number;
  slug: string;
  style_code: string;
  name: string;
  brand: Brand;
  category: CategoryRef;
  parent_category: CategoryRef | null;
  gender: Gender;
  colour: string;
  colour_hex: string;
  colour_family: string;
  secondary_colours: string[];
  pattern: string;
  material: string;
  fit: string;
  style_tags: string[];
  occasions: string[];
  seasons: string[];
  formality: number;
  price: number;
  mrp: number;
  description: string;
  is_active: boolean;
  images: ProductImage[];
  variants: Variant[];
  colourways: { id: number; slug: string; colour: string; colour_hex: string }[];
}

export interface ValueCount {
  value: string;
  count: number;
}

export interface Facets {
  categories: CategoryNode[];
  brands: ValueCount[];
  colours: { name: string; hex: string; family: string; count: number }[];
  sizes: string[];
  genders: ValueCount[];
  style_tags: ValueCount[];
  occasions: ValueCount[];
  price_min: number;
  price_max: number;
}

export interface Preferences {
  preferred_store_id: number | null;
  personalization_enabled: boolean;
}

export interface User {
  id: string;
  email: string;
  full_name: string;
  is_admin: boolean;
  preferences: Preferences;
}

export interface ApiErrorBody {
  error: { code: string; message: string; request_id?: string; details?: unknown };
}

export interface SearchInterpretation {
  kind: "category" | "colour" | "gender" | "size" | "price" | "occasion" | "style" | "sale";
  value: string;
  label: string;
  phrase: string;
}

export interface SearchPage extends Page<ProductSummary> {
  query: string | null;
  interpretation: SearchInterpretation[];
  retrieval: {
    mode: "filter" | "lexical" | "hybrid";
    match: "exact" | "related" | "none";
    lexical_candidates: number;
    vector_candidates: number;
    latency_ms: number;
  };
}

export interface SimilarProduct {
  product: ProductSummary;
  similarity: number;
  reasons: string[];
}
