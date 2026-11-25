"""Chat orchestration: one shopper turn from message to persisted, validated, hydrated answer."""

import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.fallback import run_fallback_turn
from app.agent.llm import ModelBackend
from app.agent.loop import TurnResult, run_llm_turn
from app.agent.pipeline import run_pipeline_turn
from app.agent.schemas import Recommendation
from app.agent.tools import ToolContext
from app.core.config import get_settings
from app.core.errors import NotFound
from app.core.logging import get_logger
from app.core.metrics import AGENT_TURN_SECONDS, AGENT_TURNS, RECOMMENDED_ITEMS
from app.db.models import (
    AgentTrace,
    ChatMessage,
    ChatSession,
    Product,
    ProductVariant,
    Store,
    Upload,
    User,
)
from app.services.catalogue import resolve_product_id, summaries
from app.services.profile import load_profile, profile_summary

log = get_logger("gabriella.chat")
HISTORY_MESSAGES = 12
# Pipeline mode targets metered free tiers, so it carries less history.
PIPELINE_HISTORY_MESSAGES = 6


def agent_strategy(backend: ModelBackend) -> str:
    """`tools`: the model searches freely (best for unmetered models like Claude).
    `pipeline`: the server retrieves and drafts, the model refines in one call
    (default for Groq, Ollama and other OpenAI-compatible providers)."""
    configured = get_settings().agent_mode
    if configured != "auto":
        return configured
    return "tools" if backend.name.startswith("claude") else "pipeline"


Emit = Callable[[dict[str, Any]], Awaitable[None]]


async def create_session(
    db: AsyncSession, user: User | None, *, store_id: int | None, product_key: str | None
) -> ChatSession:
    if store_id is None and user is not None and user.preferences:
        store_id = user.preferences.preferred_store_id
    if store_id is not None and await db.get(Store, store_id) is None:
        raise NotFound("Store not found")
    chat = ChatSession(
        user_id=user.id if user else None,
        store_id=store_id,
        context_product_id=await resolve_product_id(db, product_key) if product_key else None,
        personalization_enabled=bool(
            user and user.preferences and user.preferences.personalization_enabled
        ),
        constraints={},
    )
    db.add(chat)
    await db.commit()
    return chat


async def load_session(db: AsyncSession, session_id: uuid.UUID, user: User | None) -> ChatSession:
    chat = await db.get(ChatSession, session_id)
    # Signed-in sessions belong to their owner; anonymous ones are reachable by their UUID only.
    if chat is None or (chat.user_id is not None and (user is None or user.id != chat.user_id)):
        raise NotFound("Conversation not found")
    return chat


async def messages_for(db: AsyncSession, chat: ChatSession) -> list[ChatMessage]:
    return list(
        (
            await db.scalars(
                select(ChatMessage)
                .where(ChatMessage.session_id == chat.id)
                .order_by(ChatMessage.id)
            )
        ).all()
    )


def _shown_ids(payload: dict[str, Any] | None) -> list[tuple[int, int | None]]:
    if not payload:
        return []
    return [
        (i["product_id"], i.get("variant_id"))
        for g in payload.get("groups", [])
        for i in g.get("items", [])
    ]


async def model_history(db: AsyncSession, past: list[ChatMessage]) -> list[dict[str, Any]]:
    """Earlier turns as plain text. Assistant turns note which products were shown, by ID,
    so follow-ups like 'swap the shoes' can refer back to them."""
    recent = past[-HISTORY_MESSAGES:]
    while recent and recent[0].role != "user":
        recent = recent[1:]
    ids = {pid for m in recent for pid, _ in _shown_ids(m.payload)}
    names = (
        {
            p.id: f"{p.name} ({p.colour}, ₹{p.price:,})"
            for p in (await db.scalars(select(Product).where(Product.id.in_(ids)))).unique()
        }
        if ids
        else {}
    )
    out: list[dict[str, Any]] = []
    for m in recent:
        if m.role == "user":
            out.append({"role": "user", "content": m.content})
            continue
        shown = "; ".join(
            f"#{pid} {names.get(pid, '')}" + (f" variant {vid}" if vid else "")
            for pid, vid in _shown_ids(m.payload)
        )
        out.append(
            {"role": "assistant", "content": m.content + (f"\n[Shown: {shown}]" if shown else "")}
        )
    # Keep strict user/assistant alternation (e.g. a failed turn left two user messages).
    merged: list[dict[str, Any]] = []
    for msg in out:
        if merged and merged[-1]["role"] == msg["role"]:
            merged[-1]["content"] += "\n\n" + msg["content"]
        else:
            merged.append(msg)
    if merged and merged[-1]["role"] == "user":
        merged.pop()  # the current turn is appended separately
    return merged


async def personalisation_profile(db: AsyncSession, chat: ChatSession) -> dict[str, Any] | None:
    """The style profile, only if the shopper is signed in and personalisation is on for both
    their account and this conversation."""
    if chat.user_id is None or not chat.personalization_enabled:
        return None
    user = await db.get(User, chat.user_id)
    if user is None or not (user.preferences and user.preferences.personalization_enabled):
        return None
    return await load_profile(db, user.id)


async def active_upload(db: AsyncSession, chat: ChatSession) -> dict[str, Any] | None:
    """The uploaded garment this chat is styling around, if it hasn't expired."""
    if chat.context_upload_id is None:
        return None
    upload = await db.get(Upload, chat.context_upload_id)
    if upload is None or upload.expires_at < datetime.now(UTC):
        return None
    vector = list(upload.image_embedding) if upload.image_embedding is not None else None
    return {"analysis": upload.analysis, "vector": vector, "url": upload.url}


async def turn_preamble(
    db: AsyncSession, chat: ChatSession, store: Store | None, profile: dict[str, Any] | None = None
) -> str:
    lines = [
        f"Shopper's store: {f'{store.name}, {store.city} ({store.code})' if store else 'not chosen; search all stores'}."
    ]
    if chat.constraints:
        known = {k: v for k, v in chat.constraints.items() if v not in (None, [], "")}
        if known:
            lines.append(f"Known constraints: {known}.")
    if chat.context_product_id:
        p = await db.get(Product, chat.context_product_id)
        if p:
            lines.append(
                f"Product in focus: #{p.id} {p.name}, {p.colour}, {p.category.name}, {p.gender}, ₹{p.price:,}."
            )
    if profile:
        lines.append(f"From past purchases (personalisation on): {profile_summary(profile)}.")
    upload = await active_upload(db, chat)
    if upload:
        a = upload["analysis"]
        lines.append(
            f"The shopper uploaded a photo of their own garment: {a['label']} ({a['category_name']}, "
            f"{a['colour']}, {a['pattern']}; {round(a['confidence'] * 100)}% confident). It is theirs, "
            "not for sale: style around it. Treat the detection as a hint, not an exact identification."
        )
    return "<session>\n" + "\n".join(lines) + "\n</session>\n\n"


async def run_turn(
    db: AsyncSession,
    chat: ChatSession,
    text: str,
    *,
    backend: ModelBackend | None,
    emit: Emit,
    product_key: str | None = None,
    upload_id: uuid.UUID | None = None,
) -> ChatMessage:
    start = time.perf_counter()
    if product_key:
        chat.context_product_id = await resolve_product_id(db, product_key)
        chat.context_upload_id = None
    if upload_id:
        upload = await db.get(Upload, upload_id)
        if upload is None or upload.session_id != chat.id:
            raise NotFound("That photo isn't part of this conversation")
        chat.context_upload_id, chat.context_product_id = upload.id, None
    past = await messages_for(db, chat)
    user_payload = None
    if upload_id:
        user_payload = {"upload": {"url": upload.url, "analysis": upload.analysis}}
    db.add(ChatMessage(session_id=chat.id, role="user", content=text, payload=user_payload))
    if chat.title == "New conversation":
        chat.title = text[:80]
    await db.commit()

    store = await db.get(Store, chat.store_id) if chat.store_id else None
    stores = {
        s.code: s for s in (await db.scalars(select(Store).where(Store.is_active.is_(True)))).all()
    }
    ctx = ToolContext(session=db, store=store, stores=stores)
    ctx.profile = await personalisation_profile(db, chat)
    ctx.upload = await active_upload(db, chat)
    # Products shown earlier in this conversation (and the one in focus) count as retrieved.
    ctx.seen_product_ids.update(pid for m in past for pid, _ in _shown_ids(m.payload))
    if chat.context_product_id:
        ctx.seen_product_ids.add(chat.context_product_id)

    mode = "llm" if backend is not None else "fallback"
    error: str | None = None
    result: TurnResult | None = None
    if backend is not None:
        try:
            history = await model_history(db, past)
            preamble = await turn_preamble(db, chat, store, ctx.profile)
            if agent_strategy(backend) == "pipeline":
                result = await run_pipeline_turn(
                    backend,
                    ctx,
                    chat.constraints,
                    chat.context_product_id,
                    history[-PIPELINE_HISTORY_MESSAGES:],
                    preamble,
                    text,
                    emit,
                )
                if result.validation.get("strategy") == "pipeline-draft":
                    mode = (
                        "fallback"  # the model didn't answer; the shopper got the validated draft
                    )
            else:
                result = await run_llm_turn(backend, ctx, history, preamble + text, emit)
            error = result.error
        except Exception as exc:  # noqa: BLE001 - never leave the shopper without an answer
            await db.rollback()
            # Rollback expires loaded rows; async sessions can't lazy-reload them.
            await db.refresh(chat)
            if store is not None:
                await db.refresh(store)
            log.exception("llm_turn_failed")
            error = f"{type(exc).__name__}: {exc}"[:500]
            mode = "fallback"
    if result is None:
        result = await run_fallback_turn(ctx, chat.constraints, chat.context_product_id, text, emit)

    rec: Recommendation = result.recommendation
    chat.constraints = rec.constraints.model_dump(exclude_none=True)
    payload = rec.model_dump(exclude={"constraints"})
    payload["answered_by"] = answered_by(backend, mode, result, error)
    message = ChatMessage(
        session_id=chat.id, role="assistant", content=rec.message, payload=payload
    )
    db.add(message)
    await db.flush()
    latency_ms = int((time.perf_counter() - start) * 1000)
    db.add(
        AgentTrace(
            session_id=chat.id,
            message_id=message.id,
            mode=mode,
            model=result.model,
            tool_calls=ctx.calls,
            validation=result.validation,
            model_requests=result.model_requests,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            cache_read_tokens=result.usage.cache_read_tokens,
            latency_ms=latency_ms,
            error=error,
        )
    )
    await db.commit()

    items = sum(len(g.items) for g in rec.groups)
    AGENT_TURNS.labels(mode=mode, outcome="error" if error else "ok").inc()
    AGENT_TURN_SECONDS.labels(mode=mode).observe(latency_ms / 1000)
    RECOMMENDED_ITEMS.labels(mode=mode).inc(items)
    log.info(
        "chat_turn",
        session_id=str(chat.id),
        mode=mode,
        items=items,
        latency_ms=latency_ms,
        tools=len(ctx.calls),
        validation=result.validation,
        error=error,
    )
    return message


def answered_by(
    backend: ModelBackend | None, mode: str, result: TurnResult, error: str | None
) -> dict[str, Any]:
    """Who wrote this answer, shown under the message so the header's model name never overclaims.
    `kind` is "model" or "rules"; `fallback` is true when a model is configured but didn't answer
    (rate-limited, offline, or an unusable reply)."""
    strategy = result.validation.get("strategy")
    by_model = (
        backend is not None
        and mode == "llm"
        and result.model_requests > 0
        and strategy not in ("pipeline-draft", "pipeline-reset")
    )
    if by_model:
        return {"kind": "model", "model": backend.name, "fallback": False}
    return {
        "kind": "rules",
        "model": None,
        "fallback": backend is not None
        and strategy != "pipeline-reset"
        and bool(error or mode == "fallback"),
    }


async def hydrate(db: AsyncSession, message: ChatMessage, store_id: int | None) -> dict[str, Any]:
    """Turn a stored message into what the UI renders. Cards and stock are read live, so an
    old recommendation never shows stale availability."""
    payload = message.payload or {}
    pairs = _shown_ids(payload)
    cards = {
        c.id: c for c in await summaries(db, list(dict.fromkeys(pid for pid, _ in pairs)), store_id)
    }
    variants: dict[int, dict[str, Any]] = {}
    variant_ids = [vid for _, vid in pairs if vid]
    if variant_ids:
        for v in (
            await db.scalars(select(ProductVariant).where(ProductVariant.id.in_(variant_ids)))
        ).all():
            in_stock = (
                next((s.in_stock for s in cards[v.product_id].sizes if s.variant_id == v.id), False)
                if v.product_id in cards
                else False
            )
            variants[v.id] = {"id": v.id, "size": v.size, "in_stock": in_stock}
    groups = []
    for g in payload.get("groups", []):
        items = [
            {
                "role": i.get("role", "pick"),
                "reason": i.get("reason", ""),
                "product": cards[i["product_id"]].model_dump(),
                "variant": variants.get(i.get("variant_id")) if i.get("variant_id") else None,
            }
            for i in g.get("items", [])
            if i["product_id"] in cards
        ]
        if items:
            groups.append(
                {
                    "title": g.get("title"),
                    "kind": g.get("kind", "picks"),
                    "note": g.get("note"),
                    "total": sum(it["product"]["price"] for it in items),
                    "items": items,
                }
            )
    return {
        "id": message.id,
        "role": message.role,
        "upload": payload.get("upload") if message.role == "user" else None,
        "content": message.content,
        "created_at": message.created_at.isoformat() if message.created_at else None,
        "groups": groups,
        "follow_ups": payload.get("follow_ups", []),
        "answered_by": payload.get("answered_by") if message.role == "assistant" else None,
    }
