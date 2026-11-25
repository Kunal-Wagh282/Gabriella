"use client";

import { ArrowUp, Camera, Loader2, Plus, Sparkles, X } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import { RecommendationGroup } from "@/components/chat/recommendation";
import { Price } from "@/components/ui";
import {
  constraintChips,
  createSession,
  describeAnswer,
  describeModel,
  getSession,
  sendMessage,
  updateSession,
  uploadImage,
  type UploadResult,
  type ChatMessage,
  type ChatSession,
} from "@/lib/chat";
import { cn } from "@/lib/format";
import { useMe, useStores } from "@/lib/hooks";
import { useStoreId } from "@/lib/store";

const SESSION_KEY = "gb_chat_session";
const STARTERS = [
  "A casual dinner outfit under ₹5,000",
  "Office wear for men, size M and UK 9",
  "Something for a sangeet",
  "A party look for women in S",
];

function rememberSession(id: string | null) {
  try {
    if (id) localStorage.setItem(SESSION_KEY, id);
    else localStorage.removeItem(SESSION_KEY);
  } catch {
    /* storage unavailable: the conversation still works for this visit */
  }
}

function savedSession(): string | null {
  try {
    return localStorage.getItem(SESSION_KEY);
  } catch {
    return null;
  }
}

export function ChatApp() {
  const params = useSearchParams();
  const router = useRouter();
  const storeId = useStoreId();
  const { data: stores } = useStores();
  const { data: me } = useMe();
  const [chat, setChat] = useState<ChatSession | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [steps, setSteps] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState("");
  const [pendingUpload, setPendingUpload] = useState<UploadResult | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const started = useRef(false);

  const store = stores?.find((s) => s.id === (chat?.store_id ?? storeId));

  const startNew = useCallback(
    async (product?: string | null) => {
      const session = await createSession({ store_id: storeId, product: product ?? null });
      rememberSession(session.id);
      setChat(session);
      setMessages([]);
      setError(null);
    },
    [storeId],
  );

  // Resume the last conversation, or start one (styling ?product= if given).
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const product = params.get("product");
    const existing = savedSession();
    (async () => {
      if (!product && existing) {
        try {
          const session = await getSession(existing);
          setChat(session);
          setMessages(session.messages);
          return;
        } catch {
          rememberSession(null);
        }
      }
      await startNew(product);
      if (product) router.replace("/chat");
    })().catch(() => setError("Couldn't reach Gabriella. Is the API running?"));
  }, [params, router, startNew]);

  // Keep the conversation's store in step with the header store picker.
  useEffect(() => {
    if (chat && storeId !== chat.store_id) {
      updateSession(chat.id, { store_id: storeId }).then((s) => setChat((c) => (c ? { ...c, store_id: s.store_id } : c)));
    }
  }, [storeId, chat]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, steps]);

  async function onPickFile(file: File | undefined) {
    if (!file || !chat) return;
    setError(null);
    setUploading(true);
    try {
      setPendingUpload(await uploadImage(chat.id, file));
    } catch (err) {
      setError(err instanceof Error ? err.message : "That photo could not be read");
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function togglePersonalisation() {
    if (!chat) return;
    const next = !chat.personalization_enabled;
    const updated = await updateSession(chat.id, { personalization_enabled: next });
    setChat((c) => (c ? { ...c, personalization_enabled: next, personalized: updated.personalized } : c));
  }

  async function send(text: string) {
    const upload = pendingUpload;
    const trimmed = text.trim() || (upload ? "What goes with this?" : "");
    if (!trimmed || !chat || busy) return;
    setDraft("");
    setPendingUpload(null);
    setError(null);
    setBusy(true);
    setSteps([]);
    setMessages((m) => [
      ...m,
      { id: `local-${Date.now()}`, role: "user", content: trimmed, created_at: null, groups: [], follow_ups: [], upload: upload ?? null },
    ]);
    try {
      await sendMessage(chat.id, trimmed, (event) => {
        if (event.type === "status") setSteps((s) => (s.at(-1) === event.text ? s : [...s, event.text]));
        else if (event.type === "message") {
          setMessages((m) => [...m, event.message]);
          setChat((c) => (c ? { ...c, constraints: event.constraints } : c));
        } else if (event.type === "error") setError(event.message);
      }, upload?.id);
      if (upload) setChat((c) => (c ? { ...c, context_upload: upload, context_product: null } : c));
    } catch {
      setError("The connection dropped. Please try again.");
    } finally {
      setBusy(false);
      setSteps([]);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void send(draft);
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send(draft);
    }
  }

  const chips = chat ? constraintChips(chat.constraints, store?.city) : [];
  const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant");

  return (
    <div className="mx-auto flex min-h-[calc(100dvh-8rem)] max-w-4xl flex-col px-4 sm:px-6">
      <div className="z-20 -mx-4 border-b border-line bg-ivory/95 px-4 py-3 backdrop-blur sm:sticky sm:top-24 sm:-mx-6 sm:px-6">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="grid size-10 place-items-center rounded-full bg-ink font-display text-xl text-ivory">G</span>
            <div>
              <h1 className="font-display text-2xl leading-none">Gabriella</h1>
              <p className="mt-1 text-[11px] text-muted">
                {!chat
                  ? "Your stylist · only recommends what's in stock"
                  : chat.mode === "fallback"
                    ? "Rule-based styling mode · every piece checked against live stock"
                    : `Powered by ${describeModel(chat.model)} · every piece checked against live stock`}
              </p>
            </div>
          </div>
          <button
            onClick={() => void startNew()}
            className="focus-ring inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap border border-line bg-white px-3 py-2 text-xs hover:border-ink"
          >
            <Plus className="size-3.5" /> New chat
          </button>
        </div>
        {chat?.personalized !== undefined && me && (
          <button
            onClick={() => void togglePersonalisation()}
            role="switch"
            aria-checked={chat.personalization_enabled}
            className={cn(
              "focus-ring mt-3 inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[11px]",
              chat.personalized ? "border-cognac/40 bg-cognac/5 text-cognac" : "border-line text-muted",
            )}
          >
            <span className={cn("size-2 rounded-full", chat.personalized ? "bg-cognac" : "bg-stone")} />
            {chat.personalized ? "Personalised from your past orders" : chat.personalization_enabled ? "No past orders to learn from yet" : "Personalisation off for this chat"}
            <span className="text-muted">· {chat.personalization_enabled ? "turn off" : "turn on"}</span>
          </button>
        )}
        {chips.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5" aria-label="What Gabriella knows">
            {chips.map((c) => (
              <span key={c} className="rounded-full border border-line bg-white px-2.5 py-0.5 text-[11px]">{c}</span>
            ))}
          </div>
        )}
      </div>

      {chat?.context_upload && !chat.context_product && (
        <div className="mt-6 flex items-center gap-4 border border-line bg-white p-3">
          <Image src={chat.context_upload.url} alt="Your garment" width={64} height={80} className="h-20 w-16 object-cover" unoptimized />
          <div className="min-w-0 flex-1">
            <p className="eyebrow">Styling your photo</p>
            <p className="text-sm">Looks like a {chat.context_upload.analysis.label} ({Math.round(chat.context_upload.analysis.confidence * 100)}% sure)</p>
            <p className="text-[11px] text-muted">A style suggestion from your photo, not an exact identification.</p>
          </div>
          <button
            aria-label="Stop styling this photo"
            onClick={() => updateSession(chat.id, { clear_product: true }).then(() => setChat({ ...chat, context_upload: null }))}
            className="focus-ring p-2 text-muted hover:text-ink"
          >
            <X className="size-4" />
          </button>
        </div>
      )}

      {chat?.context_product && (
        <div className="mt-6 flex items-center gap-4 border border-line bg-white p-3">
          {chat.context_product.image && (
            <Image src={chat.context_product.image.url} alt="" width={64} height={80} className="h-20 w-16 object-cover" />
          )}
          <div className="min-w-0 flex-1">
            <p className="eyebrow">Styling</p>
            <Link href={`/product/${chat.context_product.slug}`} className="block truncate text-sm hover:underline">
              {chat.context_product.name} · {chat.context_product.colour}
            </Link>
            <Price price={chat.context_product.price} mrp={chat.context_product.mrp} className="text-xs" />
          </div>
          <button
            aria-label="Stop styling this product"
            onClick={() => updateSession(chat.id, { clear_product: true }).then(() => setChat({ ...chat, context_product: null }))}
            className="focus-ring p-2 text-muted hover:text-ink"
          >
            <X className="size-4" />
          </button>
        </div>
      )}

      <div className="flex-1 space-y-8 py-8" aria-live="polite">
        {!chat && !error && (
          <p className="flex items-center justify-center gap-2 py-16 text-sm text-muted">
            <Loader2 className="size-4 animate-spin" /> Opening your conversation…
          </p>
        )}
        {messages.length === 0 && chat && !busy && (
          <div className="py-10 text-center">
            <Sparkles className="mx-auto size-6 text-cognac" strokeWidth={1.5} />
            <p className="mt-4 font-display text-4xl">What are we dressing for?</p>
            <p className="mx-auto mt-2 max-w-md text-sm text-muted">
              Tell me the occasion, your budget and sizes. Everything I suggest is in stock{store ? ` at ${store.city}` : ""} right now.
            </p>
            <div className="mt-8 flex flex-wrap justify-center gap-2">
              {(chat.context_product ? ["What goes with this?", "Do you have this in my size?", "Show me something similar"] : STARTERS).map((s) => (
                <button key={s} onClick={() => void send(s)} className="focus-ring rounded-full border border-line bg-white px-4 py-2 text-sm hover:border-ink">
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m) =>
          m.role === "user" ? (
            <div key={m.id} className="flex justify-end">
              <div className="flex max-w-[80%] flex-col items-end gap-2">
                {m.upload && (
                  <figure className="w-40 border border-line bg-white p-1">
                    <Image src={m.upload.url} alt="Your photo" width={320} height={400} className="h-auto w-full object-cover" unoptimized />
                    <figcaption className="px-1 py-1 text-[10px] text-muted">Looks like a {m.upload.analysis.label}</figcaption>
                  </figure>
                )}
                <p className="whitespace-pre-wrap bg-ink px-4 py-2.5 text-sm text-ivory">{m.content}</p>
              </div>
            </div>
          ) : (
            <div key={m.id} className="max-w-full">
              <p className="max-w-2xl text-[15px] leading-relaxed">{m.content}</p>
              {m.groups.map((g, i) => (
                <RecommendationGroup key={`${m.id}-${i}`} group={g} storeId={chat?.store_id ?? null} />
              ))}
              {m.answered_by && (
                <p className="mt-2 text-[11px] text-muted" title="Every answer passes the same stock, size and budget checks">
                  {describeAnswer(m.answered_by)}
                </p>
              )}
            </div>
          ),
        )}

        {busy && (
          <ol className="space-y-1.5 text-sm text-muted" aria-label="Gabriella is working">
            {(steps.length ? steps : ["Gabriella is looking…"]).map((s, i, all) => (
              <li key={s} className="flex items-center gap-2">
                {i === all.length - 1 ? <Loader2 className="size-3.5 animate-spin" /> : <span className="size-3.5 text-center text-ok">✓</span>}
                {s}
              </li>
            ))}
          </ol>
        )}
        {error && <p role="alert" className="border border-sale/30 bg-sale/5 px-4 py-3 text-sm text-sale">{error}</p>}
        <div ref={bottom} />
      </div>

      <div className="sticky bottom-0 -mx-4 border-t border-line bg-ivory/95 px-4 pb-4 pt-3 backdrop-blur sm:-mx-6 sm:px-6">
        {!busy && lastAssistant && lastAssistant.follow_ups.length > 0 && (
          <div className="mb-3 flex gap-2 overflow-x-auto pb-1">
            {lastAssistant.follow_ups.map((f) => (
              <button key={f} onClick={() => void send(f)} className="focus-ring shrink-0 rounded-full border border-line bg-white px-3 py-1.5 text-xs hover:border-ink">
                {f}
              </button>
            ))}
          </div>
        )}
        {pendingUpload && (
          <div className="mb-2 flex items-center gap-3 border border-line bg-white p-2">
            <Image src={pendingUpload.url} alt="Your photo" width={48} height={60} className="h-14 w-11 object-cover" unoptimized />
            <div className="min-w-0 flex-1 text-xs">
              <p>Looks like a <strong>{pendingUpload.analysis.label}</strong> · {Math.round(pendingUpload.analysis.confidence * 100)}% sure</p>
              <p className="text-[11px] text-muted">{pendingUpload.note}</p>
            </div>
            <button aria-label="Remove photo" onClick={() => setPendingUpload(null)} className="focus-ring p-1 text-muted hover:text-ink">
              <X className="size-4" />
            </button>
          </div>
        )}
        <form onSubmit={onSubmit} className="flex items-end gap-2 border border-line bg-white p-2 focus-within:border-ink">
          <input
            ref={fileInput}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            className="hidden"
            onChange={(e) => void onPickFile(e.target.files?.[0])}
          />
          <button
            type="button"
            onClick={() => fileInput.current?.click()}
            disabled={!chat || busy || uploading}
            aria-label="Add a photo of something you own"
            title="Add a photo of something you own"
            className="focus-ring grid size-10 shrink-0 place-items-center text-muted hover:text-ink disabled:opacity-40"
          >
            {uploading ? <Loader2 className="size-4 animate-spin" /> : <Camera className="size-5" strokeWidth={1.5} />}
          </button>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            rows={1}
            maxLength={1000}
            placeholder={chat?.context_product ? "Ask about this piece, or what to wear with it…" : "Describe the occasion, budget and sizes…"}
            aria-label="Message Gabriella"
            className="max-h-40 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 text-sm outline-none placeholder:text-muted/70"
          />
          <button
            type="submit"
            disabled={(!draft.trim() && !pendingUpload) || busy || !chat}
            aria-label="Send"
            className={cn("focus-ring grid size-10 shrink-0 place-items-center bg-ink text-ivory transition-opacity", ((!draft.trim() && !pendingUpload) || busy) && "opacity-30")}
          >
            {busy ? <Loader2 className="size-4 animate-spin" /> : <ArrowUp className="size-4" />}
          </button>
        </form>
        <p className="mt-2 text-center text-[10px] text-muted">
          Recommendations come only from this store&apos;s live catalogue. Gabriella never comments on body shape.
        </p>
      </div>
    </div>
  );
}
