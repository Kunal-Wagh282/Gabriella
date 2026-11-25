"use client";

import { api } from "@/lib/client-api";
import type { ProductSummary } from "@/lib/types";

export type ItemRole = "top" | "bottom" | "onepiece" | "outerwear" | "footwear" | "accessory" | "pick";

export interface ChatItem {
  role: ItemRole;
  reason: string;
  product: ProductSummary;
  variant: { id: number; size: string; in_stock: boolean } | null;
}

export interface ChatGroup {
  title: string;
  kind: "outfit" | "picks" | "alternatives";
  note: string | null;
  total: number;
  items: ChatItem[];
}

export interface GarmentAnalysis {
  category: string;
  category_name: string;
  slot: string;
  confidence: number;
  colour: string;
  colour_hex: string;
  colour_family: string;
  pattern: string;
  label: string;
}

export interface UploadInfo {
  url: string;
  analysis: GarmentAnalysis;
}

export interface ChatMessage {
  id: number | string;
  role: "user" | "assistant";
  upload?: UploadInfo | null;
  content: string;
  created_at: string | null;
  groups: ChatGroup[];
  follow_ups: string[];
  /** Who wrote an assistant answer: the configured model, or the rule-based stylist. */
  answered_by?: AnsweredBy | null;
}

export interface AnsweredBy {
  kind: "model" | "rules";
  model: string | null;
  /** True when a model is configured but didn't answer (rate-limited, offline, unusable reply). */
  fallback: boolean;
}

export function describeAnswer(by: AnsweredBy): string {
  if (by.kind === "model" && by.model) return `Answered by ${describeModel(by.model)}`;
  return by.fallback
    ? "Answered by the rule-based stylist · the model was busy, so the same checks ran without it"
    : "Answered by the rule-based stylist";
}

export interface Constraints {
  occasion?: string;
  budget_max?: number;
  apparel_size?: string;
  footwear_size?: string;
  gender?: "men" | "women";
  colours?: string[];
  avoid_colours?: string[];
  formality?: "relaxed" | "smart" | "formal";
}

export interface ChatSession {
  id: string;
  title: string;
  store_id: number | null;
  constraints: Constraints;
  context_product: ProductSummary | null;
  mode: "llm" | "fallback";
  /** e.g. "groq:openai/gpt-oss-120b", "ollama:qwen2.5:7b" or "rule-based stylist" */
  model: string;
  personalization_enabled: boolean;
  /** True when a style profile from past orders is being used in this chat. */
  personalized: boolean;
  context_upload: UploadInfo | null;
  messages: ChatMessage[];
}

export type ChatEvent =
  | { type: "status"; text: string }
  | { type: "message"; message: ChatMessage; constraints: Constraints }
  | { type: "error"; message: string };

export function createSession(body: { store_id: number | null; product?: string | null }) {
  return api<ChatSession>("/chat/sessions", { method: "POST", body: JSON.stringify(body) });
}

export function getSession(id: string) {
  return api<ChatSession>(`/chat/sessions/${id}`);
}

export function updateSession(
  id: string,
  body: { store_id?: number | null; product?: string; clear_product?: boolean; personalization_enabled?: boolean },
) {
  return api<ChatSession>(`/chat/sessions/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}

/** POSTs a turn and reads the server-sent events from the response body. */
export async function sendMessage(
  sessionId: string,
  text: string,
  onEvent: (event: ChatEvent) => void,
  uploadId?: string | null,
): Promise<void> {
  const res = await fetch(`/api/chat/sessions/${sessionId}/messages`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "content-type": "application/json", accept: "text/event-stream" },
    body: JSON.stringify({ text, upload_id: uploadId ?? undefined }),
  });
  if (!res.ok || !res.body) {
    onEvent({ type: "error", message: res.status === 404 ? "This conversation has expired. Start a new one." : "Gabriella is unavailable right now." });
    return;
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let boundary: number;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const data = frame
        .split("\n")
        .filter((line) => line.startsWith("data: "))
        .map((line) => line.slice(6))
        .join("\n");
      if (data) onEvent(JSON.parse(data) as ChatEvent);
    }
  }
}

export const ROLE_LABEL: Record<ItemRole, string> = {
  top: "Top",
  bottom: "Bottom",
  onepiece: "Dress",
  outerwear: "Layer",
  footwear: "Shoes",
  accessory: "Finishing touch",
  pick: "Pick",
};

export function constraintChips(c: Constraints, storeCity?: string): string[] {
  const chips: string[] = [];
  if (storeCity) chips.push(storeCity);
  if (c.occasion) chips.push(c.occasion.replace(/^\w/, (m) => m.toUpperCase()));
  if (c.gender) chips.push(c.gender === "men" ? "Menswear" : "Womenswear");
  if (c.budget_max) chips.push(`Under ₹${c.budget_max.toLocaleString("en-IN")}`);
  if (c.apparel_size) chips.push(`Size ${c.apparel_size}`);
  if (c.footwear_size) chips.push(c.footwear_size);
  if (c.formality) chips.push({ relaxed: "Relaxed", smart: "Smart", formal: "Formal" }[c.formality]);
  for (const colour of c.colours ?? []) chips.push(colour.replace(/^\w/, (m) => m.toUpperCase()));
  for (const colour of c.avoid_colours ?? []) chips.push(`No ${colour}`);
  return chips;
}

const PROVIDERS: Record<string, string> = {
  groq: "Groq",
  ollama: "Ollama, running locally",
  openai_compatible: "self-hosted",
};

/** "groq:openai/gpt-oss-120b" -> "openai/gpt-oss-120b on Groq". */
export function describeModel(model: string): string {
  const [provider, ...rest] = model.split(":");
  const name = rest.join(":");
  if (!name) return model; // e.g. a Claude model id
  return `${name} on ${PROVIDERS[provider] ?? provider}`;
}

export interface UploadResult extends UploadInfo {
  id: string;
  note: string;
}

/** Sends a photo of the shopper's own garment for analysis. */
export async function uploadImage(sessionId: string, file: File): Promise<UploadResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`/api/chat/sessions/${sessionId}/uploads`, { method: "POST", body: form, credentials: "same-origin" });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.error?.message ?? "That photo could not be read");
  }
  return res.json();
}
