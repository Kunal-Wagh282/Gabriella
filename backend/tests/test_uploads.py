"""Photo of the shopper's own garment: validation, colour extraction, styling around it, expiry."""

import io
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from PIL import Image
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.models import Upload
from app.vision import garment
from app.workers.worker import purge_expired_uploads
from seed.render import render_flatlay
from tests.conftest import Catalogue


def _png(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, "PNG")
    return buf.getvalue()


@pytest.mark.parametrize(
    ("hex_", "expected"),
    [
        ("#1F2A44", {"Navy"}),
        ("#D6C3A3", {"Beige"}),
        ("#B3282D", {"Red"}),
        # A white garment on a light backdrop is genuinely ambiguous; any light neutral is fair.
        ("#F7F6F2", {"White", "Beige"}),
    ],
)
def test_dominant_colour_ignores_the_background(hex_: str, expected: set[str]):
    image = render_flatlay("shirt", hex_, seed=1)
    rgb = garment.dominant_colour(image)
    palette = {
        "Navy": "#1F2A44",
        "Beige": "#D6C3A3",
        "White": "#F7F6F2",
        "Black": "#1C1C1E",
        "Red": "#B3282D",
    }
    nearest = min(palette, key=lambda n: garment._redmean(rgb, garment._hex_to_rgb(palette[n])))
    assert nearest in expected


def test_rejects_bad_files():
    with pytest.raises(AppError, match="readable image"):
        garment.load_image(b"not an image")
    gif = io.BytesIO()
    Image.new("RGB", (10, 10)).save(gif, "GIF")
    with pytest.raises(AppError, match="JPEG, PNG or WebP"):
        garment.load_image(gif.getvalue())
    with pytest.raises(AppError, match="8 MB"):
        garment.load_image(b"0" * (garment.MAX_BYTES + 1))


def test_reencoding_strips_metadata_and_downsizes():
    big = Image.new("RGB", (3000, 2000), "navy")
    buf = io.BytesIO()
    big.save(buf, "JPEG", exif=b"Exif\x00\x00GPS-secret")
    image = garment.load_image(buf.getvalue())
    assert max(image.size) == garment.MAX_SIDE and not image.info.get("exif")


async def _session(client: httpx.AsyncClient, catalogue: Catalogue) -> str:
    return (await client.post("/api/chat/sessions", json={"store_id": catalogue.pune})).json()["id"]


async def _upload(client: httpx.AsyncClient, sid: str, data: bytes) -> httpx.Response:
    return await client.post(
        f"/api/chat/sessions/{sid}/uploads", files={"file": ("shirt.png", data, "image/png")}
    )


async def test_upload_is_analysed_and_stored(
    client: httpx.AsyncClient, session: AsyncSession, catalogue: Catalogue
):
    sid = await _session(client, catalogue)
    r = await _upload(client, sid, _png(render_flatlay("shirt", "#1F2A44", seed=3)))
    assert r.status_code == 201, r.text
    body = r.json()
    # Fixture products share one placeholder hex, so only the shape is checked here;
    # colour accuracy is covered by test_dominant_colour_ignores_the_background.
    assert {"category", "slot", "colour", "pattern", "label"} <= body["analysis"].keys()
    assert 0 < body["analysis"]["confidence"] <= 1
    assert (
        body["url"].startswith("/media/uploads/") and "not an exact identification" in body["note"]
    )
    upload = (await session.scalars(select(Upload))).one()
    assert upload.expires_at > datetime.now(UTC) + timedelta(hours=23)
    assert garment.upload_path(upload.file_name).exists()

    bad = await client.post(
        f"/api/chat/sessions/{sid}/uploads", files={"file": ("x.txt", b"hello", "text/plain")}
    )
    assert bad.status_code == 415


async def test_styling_around_an_uploaded_shirt(
    client: httpx.AsyncClient, catalogue: Catalogue, monkeypatch: pytest.MonkeyPatch
):
    async def fake_analyse(
        _db: Any, _image: Image.Image
    ) -> tuple[garment.GarmentAnalysis, list[float]]:
        return garment.GarmentAnalysis(
            category="casual-shirts",
            category_name="Casual Shirts",
            slot="top",
            confidence=0.83,
            colour="Navy",
            colour_hex="#1F2A44",
            colour_family="blue",
            pattern="solid",
            formality=3,
            label="navy shirt",
        ), [0.0] * 512

    monkeypatch.setattr(garment, "analyse", fake_analyse)
    sid = await _session(client, catalogue)
    upload = (await _upload(client, sid, _png(render_flatlay("shirt", "#1F2A44", seed=3)))).json()

    events = []
    payload = {"text": "What trousers and shoes go with this? Menswear", "upload_id": upload["id"]}
    async with client.stream("POST", f"/api/chat/sessions/{sid}/messages", json=payload) as r:
        async for line in r.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    message = events[-1]["message"]
    (group,) = message["groups"]
    assert group["title"] == "Built around your navy shirt"
    roles = {i["role"] for i in group["items"]}
    assert (
        "top" not in roles and {"bottom", "footwear"} <= roles
    )  # their shirt isn't sold back to them
    assert catalogue.navy_shirt not in [i["product"]["id"] for i in group["items"]]

    session_view = (await client.get(f"/api/chat/sessions/{sid}")).json()
    assert session_view["context_upload"]["analysis"]["label"] == "navy shirt"
    assert session_view["messages"][0]["upload"]["url"] == upload["url"]


async def test_uploads_are_private_to_their_conversation(
    client: httpx.AsyncClient, catalogue: Catalogue
):
    first = await _session(client, catalogue)
    upload = (await _upload(client, first, _png(render_flatlay("shirt", "#1F2A44", seed=3)))).json()
    other = await _session(client, catalogue)
    r = await client.post(
        f"/api/chat/sessions/{other}/messages",
        json={"text": "style this", "upload_id": upload["id"]},
    )
    assert r.status_code == 200  # the stream opens, then reports the error
    assert '"type": "error"' in r.text


async def test_expired_uploads_are_purged(
    client: httpx.AsyncClient, session: AsyncSession, catalogue: Catalogue
):
    sid = await _session(client, catalogue)
    await _upload(client, sid, _png(render_flatlay("shirt", "#1F2A44", seed=3)))
    upload = (await session.scalars(select(Upload))).one()
    await session.execute(
        update(Upload).values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    )
    await session.commit()
    assert await purge_expired_uploads({}) == 1
    assert not garment.upload_path(upload.file_name).exists()
    assert (
        await session.scalars(select(Upload).execution_options(populate_existing=True))
    ).all() == []
