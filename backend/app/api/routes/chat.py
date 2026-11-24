"""Chat with Gabriella. Turns stream as server-sent events: progress, then the validated answer."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from anyio import to_thread
from fastapi import APIRouter, File, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import Field

from app.agent import service
from app.agent.llm import default_backend
from app.api.deps import OptionalUser, SessionDep
from app.core.errors import NotFound
from app.core.logging import get_logger
from app.db.models import Store, Upload
from app.db.session import SessionLocal
from app.schemas.common import ApiModel
from app.services.catalogue import resolve_product_id, summaries
from app.vision import garment

router = APIRouter(prefix="/chat", tags=["chat"])
log = get_logger("gabriella.chat")


class SessionCreate(ApiModel):
    store_id: int | None = None
    product: str | None = Field(None, max_length=160, description="Product id or slug to style")


class SessionUpdate(ApiModel):
    store_id: int | None = None
    product: str | None = Field(None, max_length=160)
    clear_product: bool = False
    personalization_enabled: bool | None = None


class TurnRequest(ApiModel):
    text: str = Field(..., min_length=1, max_length=1000)
    product: str | None = Field(None, max_length=160)
    upload_id: uuid.UUID | None = None


async def _session_out(db: Any, chat: Any, with_messages: bool = True) -> dict[str, Any]:
    backend = default_backend()
    upload = await service.active_upload(db, chat)
    product = None
    if chat.context_product_id:
        cards = await summaries(db, [chat.context_product_id], chat.store_id)
        product = cards[0].model_dump() if cards else None
    messages = []
    if with_messages:
        for m in await service.messages_for(db, chat):
            messages.append(await service.hydrate(db, m, chat.store_id))
    return {
        "id": str(chat.id),
        "title": chat.title,
        "store_id": chat.store_id,
        "constraints": chat.constraints,
        "context_product": product,
        "mode": "llm" if backend is not None else "fallback",
        "model": backend.name if backend is not None else "rule-based stylist",
        "personalization_enabled": chat.personalization_enabled,
        "context_upload": {k: v for k, v in upload.items() if k != "vector"} if upload else None,
        "personalized": await service.personalisation_profile(db, chat) is not None,
        "messages": messages,
    }


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(body: SessionCreate, db: SessionDep, user: OptionalUser):
    chat = await service.create_session(db, user, store_id=body.store_id, product_key=body.product)
    return await _session_out(db, chat)


@router.get("/sessions/{session_id}")
async def get_session(session_id: uuid.UUID, db: SessionDep, user: OptionalUser):
    chat = await service.load_session(db, session_id, user)
    return await _session_out(db, chat)


@router.patch("/sessions/{session_id}")
async def update_session(
    session_id: uuid.UUID, body: SessionUpdate, db: SessionDep, user: OptionalUser
):
    chat = await service.load_session(db, session_id, user)
    changes = body.model_dump(exclude_unset=True)
    if "store_id" in changes:
        if body.store_id is not None and await db.get(Store, body.store_id) is None:
            raise NotFound("Store not found")
        chat.store_id = body.store_id
    if body.product:
        chat.context_product_id = await resolve_product_id(db, body.product)
    elif body.clear_product:
        chat.context_product_id = None
        chat.context_upload_id = None
    if body.personalization_enabled is not None:
        chat.personalization_enabled = body.personalization_enabled
    await db.commit()
    return await _session_out(db, chat, with_messages=False)


def _sse(event: dict[str, Any]) -> bytes:
    return f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n".encode()


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: uuid.UUID, body: TurnRequest, request: Request, db: SessionDep, user: OptionalUser
):
    """Run one turn. Streams `status` events while tools run, then one `message` event with the
    validated, hydrated answer (or `error`). The turn completes and is saved even if the client
    disconnects."""
    await service.load_session(db, session_id, user)  # authorise before streaming
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def emit(event: dict[str, Any]) -> None:
        await queue.put(event)

    async def work() -> None:
        try:
            # A dedicated DB session: the request-scoped one closes when streaming starts.
            async with SessionLocal() as turn_db:
                chat = await service.load_session(turn_db, session_id, user)
                message = await service.run_turn(
                    turn_db,
                    chat,
                    body.text,
                    backend=default_backend(),
                    emit=emit,
                    product_key=body.product,
                    upload_id=body.upload_id,
                )
                await emit(
                    {
                        "type": "message",
                        "message": await service.hydrate(turn_db, message, chat.store_id),
                        "constraints": chat.constraints,
                    }
                )
        except Exception as exc:  # noqa: BLE001
            log.exception("chat_turn_error")
            await emit(
                {
                    "type": "error",
                    "message": "Something went wrong on our side. Please try again.",
                    "detail": type(exc).__name__,
                }
            )
        finally:
            await queue.put(None)

    task = asyncio.create_task(work())

    async def stream() -> AsyncIterator[bytes]:
        yield _sse({"type": "status", "text": "Gabriella is looking…"})
        while (event := await queue.get()) is not None:
            yield _sse(event)
        await task

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.post("/sessions/{session_id}/uploads", status_code=status.HTTP_201_CREATED)
async def upload_garment(
    session_id: uuid.UUID, db: SessionDep, user: OptionalUser, file: UploadFile = File(...)
):
    """Photo of the shopper's own garment. Validated, re-encoded without metadata, analysed with
    CLIP (garment type, pattern) plus colour extraction, and deleted after 24 hours."""
    chat = await service.load_session(db, session_id, user)
    data = await file.read(garment.MAX_BYTES + 1)
    image = await to_thread.run_sync(garment.load_image, data)
    analysis, vector = await garment.analyse(db, image)
    name, url = await to_thread.run_sync(garment.save_upload, image)
    upload = Upload(
        session_id=chat.id,
        file_name=name,
        url=url,
        analysis=analysis.as_dict(),
        image_embedding=vector,
        expires_at=garment.upload_expiry(),
    )
    db.add(upload)
    await db.commit()
    return {
        "id": str(upload.id),
        "url": url,
        "analysis": analysis.as_dict(),
        "note": "A style suggestion from your photo, not an exact identification.",
    }
