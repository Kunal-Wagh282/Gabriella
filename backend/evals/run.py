"""Gabriella evaluation suite.

    uv run python -m evals.run                    # rule-based stylist (no model, fast, free)
    uv run python -m evals.run --mode llm         # whatever model .env configures (e.g. Groq)
    uv run python -m evals.run --only chat        # chat | retrieval | image

Runs against the seeded catalogue in the configured database, through the real HTTP API
(in-process), and re-verifies every answer against the database. Writes
evals/reports/<mode>-latest.{md,json}.

Note: chat cases create conversations, and signed-in cases use the demo shopper; nothing is
purchased.
"""

import argparse
import asyncio
import json
import os
import random
import statistics
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

os.environ.setdefault("LOG_LEVEL", "WARNING")

import httpx  # noqa: E402
from PIL import Image  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app.api.routes import chat as chat_routes  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.models import (  # noqa: E402
    AgentTrace,
    Category,
    Inventory,
    Product,
    ProductEmbedding,
    ProductImage,
    ProductVariant,
    Store,
)
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.retrieval import search as search_module  # noqa: E402
from app.services.profile import load_profile  # noqa: E402
from app.vision.garment import analyse  # noqa: E402
from evals.cases import CHAT_CASES, RETRIEVAL_CASES, ChatCase  # noqa: E402

REPORTS = Path(__file__).parent / "reports"
APPAREL = {"top", "bottom", "onepiece", "outerwear"}


def pct(n: float, d: float) -> float | None:
    return round(100 * n / d, 1) if d else None


def p(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return round(values[min(len(values) - 1, int(q * len(values)))], 1)


# ------------------------------------------------------------------ chat


async def _product_by_query(client: httpx.AsyncClient, query: str) -> dict[str, Any]:
    r = await client.get("/api/search", params={"q": query, "page_size": 1})
    items = r.json()["items"]
    if not items:
        raise RuntimeError(f"no catalogue product for {query!r}")
    return items[0]


async def _turn(
    client: httpx.AsyncClient, sid: str, text: str, upload_id: str | None
) -> tuple[dict, float]:
    start = time.perf_counter()
    events = []
    async with client.stream(
        "POST",
        f"/api/chat/sessions/{sid}/messages",
        json={"text": text, "upload_id": upload_id},
        timeout=180,
    ) as r:
        async for line in r.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    final = next(
        (e for e in reversed(events) if e["type"] in ("message", "error")), {"type": "error"}
    )
    return final, (time.perf_counter() - start) * 1000


async def _verify_items(groups: list[dict], store_id: int) -> dict[str, Any]:
    """Independent re-check of every displayed item against the database."""
    items = [i for g in groups for i in g["items"]]
    async with SessionLocal() as db:
        grounded = stock_ok = 0
        details = []
        for item in items:
            product = await db.get(Product, item["product"]["id"])
            ok = (
                product is not None
                and product.is_active
                and product.price == item["product"]["price"]
            )
            grounded += ok
            if item.get("variant"):
                on_hand = await db.scalar(
                    select(Inventory.on_hand).where(
                        Inventory.variant_id == item["variant"]["id"],
                        Inventory.store_id == store_id,
                    )
                )
                in_stock = bool(on_hand)
            else:
                in_stock = bool(
                    await db.scalar(
                        select(func.count())
                        .select_from(Inventory)
                        .join(ProductVariant, ProductVariant.id == Inventory.variant_id)
                        .where(
                            ProductVariant.product_id == item["product"]["id"],
                            Inventory.store_id == store_id,
                            Inventory.on_hand > 0,
                        )
                    )
                )
            stock_ok += in_stock
            slot = (
                await db.scalar(select(Category.slot).where(Category.id == product.category_id))
                if product
                else None
            )
            details.append(
                {
                    "slot": slot,
                    "category": product.category.slug if product else None,
                    "family": product.colour_family if product else None,
                    "formality": product.formality if product else None,
                    "gender": product.gender if product else None,
                    "role": item["role"],
                }
            )
    return {"items": len(items), "grounded": grounded, "stock_ok": stock_ok, "details": details}


def _check(
    case: ChatCase, final: dict, verified: dict, history: list[dict], profile: dict | None
) -> list[str]:
    """Returns failed expectations (empty list = pass)."""
    fails: list[str] = []
    if final.get("type") != "message":
        return ["no answer (error)"]
    msg = final["message"]
    groups = msg["groups"]
    items = [i for g in groups for i in g["items"]]
    details = verified["details"]
    kinds = {g["kind"] for g in groups}
    if case.kind == "none" and items:
        fails.append(f"expected no products, got {len(items)}")
    elif case.kind == "question" and items:
        fails.append("expected a question, got products")
    elif case.kind in ("outfit", "picks", "alternatives") and case.kind not in kinds:
        fails.append(f"expected {case.kind}, got {sorted(kinds) or 'nothing'}")
    if case.budget:
        for g in groups:
            if g["kind"] == "outfit" and g["total"] > case.budget:
                fails.append(f"outfit ₹{g['total']} over budget ₹{case.budget}")
            if g["kind"] != "outfit" and any(
                i["product"]["price"] > case.budget for i in g["items"]
            ):
                fails.append("a pick is over budget")
    for item, d in zip(items, details, strict=False):
        v = item.get("variant")
        if case.apparel_size and d["slot"] in APPAREL and v and v["size"] != case.apparel_size:
            fails.append(f"apparel size {v['size']} != {case.apparel_size}")
        if case.footwear_size and d["slot"] == "footwear" and v and v["size"] != case.footwear_size:
            fails.append(f"shoe size {v['size']} != {case.footwear_size}")
    slots = {d["slot"] for d in details}
    if case.slots_include - slots:
        fails.append(f"missing slots {sorted(case.slots_include - slots)}")
    if case.slots_exclude & slots:
        fails.append(f"unexpected slots {sorted(case.slots_exclude & slots)}")
    if case.categories_any and any(d["category"] not in case.categories_any for d in details):
        fails.append(
            "item outside expected categories: "
            + ", ".join(sorted({d["category"] for d in details} - case.categories_any))
        )
    if case.colour_family_any and not any(d["family"] in case.colour_family_any for d in details):
        fails.append(f"no item in colour families {sorted(case.colour_family_any)}")
    if case.gender and any(d["gender"] not in (case.gender, "unisex") for d in details):
        fails.append("item for the wrong gender")
    apparel_form = [d["formality"] for d in details if d["slot"] in APPAREL]
    if case.min_formality and apparel_form and statistics.mean(apparel_form) < case.min_formality:
        fails.append(f"mean formality {statistics.mean(apparel_form):.1f} < {case.min_formality}")
    if case.max_formality and apparel_form and statistics.mean(apparel_form) > case.max_formality:
        fails.append(f"mean formality {statistics.mean(apparel_form):.1f} > {case.max_formality}")
    for text in case.message_contains:
        if not any(alt.lower() in msg["content"].lower() for alt in text.split("|")):
            fails.append(f"message lacks {text!r}")
    if case.title_is and not any(g["title"] == case.title_is for g in groups):
        fails.append(f"no group titled {case.title_is!r}")
    if case.formality_drops and len(history) >= 2:
        before, after = history[-2], history[-1]
        if before and after and statistics.mean(after) >= statistics.mean(before):
            fails.append(
                f"formality did not drop ({statistics.mean(before):.1f} -> {statistics.mean(after):.1f})"
            )
    if case.profile_colour_share and profile and details:
        liked = set(profile.get("colour_families", []))
        share = sum(d["family"] in liked for d in details) / len(details)
        if share < case.profile_colour_share:
            fails.append(f"only {share:.0%} of items in the shopper's colour families")
        owned = set(profile.get("recent_product_ids", []))
        if any(i["product"]["id"] in owned for i in items):
            fails.append(
                "recommended something the shopper already bought: "
                + str([i["product"]["id"] for i in items if i["product"]["id"] in owned])
            )
    if case.id == "personal-off" and any(g["title"] == "Picked for you" for g in groups):
        fails.append("personalised picks shown with personalisation off")
    return fails


async def run_chat(pace: float, only_case: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    results = []
    async with SessionLocal() as db:
        stores = {s.code: s.id for s in (await db.scalars(select(Store))).all()}
    transport = httpx.ASGITransport(app=app)
    for case in [c for c in CHAT_CASES if only_case in (None, c.id)]:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://eval", timeout=180
        ) as client:
            profile = None
            if case.signed_in:
                await client.post(
                    "/api/auth/login",
                    json={
                        "email": settings.seed_demo_email,
                        "password": settings.seed_demo_password.get_secret_value(),
                    },
                )
                me = (await client.get("/api/auth/me")).json()
                async with SessionLocal() as db:
                    import uuid as _uuid

                    profile = await load_profile(db, _uuid.UUID(me["id"]))
            body: dict[str, Any] = {"store_id": stores[case.store]}
            if case.focus_query:
                body["product"] = (await _product_by_query(client, case.focus_query))["slug"]
            sid = (await client.post("/api/chat/sessions", json=body)).json()["id"]
            if not case.personalisation:
                await client.patch(
                    f"/api/chat/sessions/{sid}", json={"personalization_enabled": False}
                )
            upload_id = None
            if case.photo_query:
                src = await _product_by_query(client, case.photo_query)
                data = (await client.get(src["image"]["url"])).content
                upload = (
                    await client.post(
                        f"/api/chat/sessions/{sid}/uploads",
                        files={"file": ("photo.webp", data, "image/webp")},
                    )
                ).json()
                upload_id = upload["id"]
            history: list[list[int]] = []
            latencies = []
            final: dict = {}
            verified: dict = {"items": 0, "grounded": 0, "stock_ok": 0, "details": []}
            for n, text in enumerate(case.turns):
                final, ms = await _turn(client, sid, text, upload_id if n == 0 else None)
                latencies.append(ms)
                groups = (
                    final.get("message", {}).get("groups", [])
                    if final.get("type") == "message"
                    else []
                )
                verified = await _verify_items(groups, stores[case.store])
                history.append(
                    [d["formality"] for d in verified["details"] if d["slot"] in APPAREL]
                )
                if pace:
                    await asyncio.sleep(pace)
            fails = _check(case, final, verified, history, profile)
            async with SessionLocal() as db:
                traces = (
                    await db.scalars(select(AgentTrace).where(AgentTrace.session_id == sid))
                ).all()
            results.append(
                {
                    "id": case.id,
                    "group": case.group,
                    "passed": not fails,
                    "fails": fails,
                    "items": verified["items"],
                    "grounded": verified["grounded"],
                    "stock_ok": verified["stock_ok"],
                    "latency_ms": [round(x) for x in latencies],
                    "answer": final.get("message", {}).get("content")
                    if final.get("type") == "message"
                    else None,
                    "modes": [t.mode for t in traces],
                    "strategies": [t.validation.get("strategy") for t in traces],
                    "tool_calls": sum(len(t.tool_calls) for t in traces),
                    "tool_errors": sum(
                        1 for t in traces for c in t.tool_calls if c.get("ok") is False
                    ),
                    "model_requests": sum(t.model_requests for t in traces),
                    "tokens": sum(t.input_tokens + t.output_tokens for t in traces),
                    "repairs": sum(len(t.validation.get("repairs", []) or []) for t in traces),
                }
            )
            status = "PASS" if not fails else "FAIL " + "; ".join(fails)
            print(f"  {case.id:24} {status}")
    items = sum(r["items"] for r in results)
    latencies = [ms for r in results for ms in r["latency_ms"]]
    turns = [m for r in results for m in r["modes"]]
    by_group: dict[str, list[bool]] = {}
    for r in results:
        by_group.setdefault(r["group"], []).append(r["passed"])
    return {
        "cases": results,
        "summary": {
            "cases": len(results),
            "passed": sum(r["passed"] for r in results),
            "pass_rate": pct(sum(r["passed"] for r in results), len(results)),
            "items_shown": items,
            "grounded_rate": pct(sum(r["grounded"] for r in results), items),
            "stock_valid_rate": pct(sum(r["stock_ok"] for r in results), items),
            "no_result_rate": pct(sum(1 for r in results if r["items"] == 0), len(results)),
            "turn_latency_p50_ms": p(latencies, 0.5),
            "turn_latency_p95_ms": p(latencies, 0.95),
            "model_answered_rate": pct(sum(1 for m in turns if m == "llm"), len(turns)),
            "tool_calls": sum(r["tool_calls"] for r in results),
            "tool_call_success_rate": pct(
                sum(r["tool_calls"] - r["tool_errors"] for r in results),
                sum(r["tool_calls"] for r in results),
            ),
            "server_repairs": sum(r["repairs"] for r in results),
            "tokens": sum(r["tokens"] for r in results),
            "by_group": {g: f"{sum(v)}/{len(v)}" for g, v in sorted(by_group.items())},
        },
    }


# ------------------------------------------------------------------ retrieval


async def run_retrieval() -> dict[str, Any]:
    from app.retrieval.search import hybrid_search
    from app.schemas.catalogue import ProductFilters

    async def precision(case, *, vectors: bool) -> tuple[float, float]:
        original = search_module.has_embeddings
        if not vectors:

            async def none(_session):  # noqa: ANN001, ANN202
                return False

            search_module.has_embeddings = none
        try:
            async with SessionLocal() as db:
                start = time.perf_counter()
                outcome = await hybrid_search(db, case.query, ProductFilters())
                ms = (time.perf_counter() - start) * 1000
                ids = [h.product_id for h in outcome.hits[:5]]
                rows = (
                    (
                        await db.execute(
                            select(Product.id, Category.slug, Product.colour_family)
                            .join(Category, Category.id == Product.category_id)
                            .where(Product.id.in_(ids))
                        )
                    ).all()
                    if ids
                    else []
                )
        finally:
            search_module.has_embeddings = original
        hits = sum(
            1
            for _, cat, fam in rows
            if cat in case.categories and (not case.colour_families or fam in case.colour_families)
        )
        return hits / 5, ms

    rows = []
    for case in RETRIEVAL_CASES:
        hybrid, ms = await precision(case, vectors=True)
        lexical, _ = await precision(case, vectors=False)
        rows.append(
            {
                "query": case.query,
                "hybrid_p_at_5": hybrid,
                "lexical_p_at_5": lexical,
                "latency_ms": round(ms, 1),
            }
        )
        print(f"  {case.query:40} hybrid P@5 {hybrid:.1f} | keyword-only {lexical:.1f}")
    lat = [r["latency_ms"] for r in rows]
    return {
        "queries": rows,
        "summary": {
            "hybrid_precision_at_5": round(statistics.mean(r["hybrid_p_at_5"] for r in rows), 3),
            "lexical_only_precision_at_5": round(
                statistics.mean(r["lexical_p_at_5"] for r in rows), 3
            ),
            "retrieval_latency_p50_ms": p(lat, 0.5),
            "retrieval_latency_p95_ms": p(lat, 0.95),
        },
    }


# ------------------------------------------------------------------ image


async def run_image(sample: int = 60) -> dict[str, Any]:
    settings = get_settings()
    random.seed(7)
    async with SessionLocal() as db:
        rows = (
            (
                await db.execute(
                    select(Product, ProductImage.url)
                    .join(
                        ProductImage,
                        (ProductImage.product_id == Product.id) & (ProductImage.position == 0),
                    )
                    .where(Product.is_active.is_(True))
                )
            )
            .unique()
            .all()
        )
        picked = random.sample(rows, min(sample, len(rows)))
        cat = slot = fam = neighbour = 0
        confusions: Counter = Counter()
        category_confusions: Counter = Counter()
        for product, url in picked:
            image = Image.open(
                settings.media_root / url.removeprefix(settings.media_url + "/")
            ).convert("RGB")
            a, vector = await analyse(db, image, exclude_product_id=product.id)
            cat += a.category == product.category.slug
            slot += a.slot == product.category.slot
            fam += a.colour_family == product.colour_family
            if a.category != product.category.slug:
                category_confusions[f"{product.category.slug} -> {a.category}"] += 1
            if a.slot != product.category.slot:
                confusions[f"{product.category.slug} -> {a.category}"] += 1
            # Visual search: do the 5 nearest products (excluding itself) share its category?
            near = (
                (
                    await db.execute(
                        select(Category.slug)
                        .select_from(ProductEmbedding)
                        .join(Product, Product.id == ProductEmbedding.product_id)
                        .join(Category, Category.id == Product.category_id)
                        .where(ProductEmbedding.product_id != product.id)
                        .order_by(ProductEmbedding.image_embedding.cosine_distance(vector))
                        .limit(5)
                    )
                )
                .scalars()
                .all()
            )
            neighbour += sum(c == product.category.slug for c in near) / 5
    n = len(picked)
    summary = {
        "images": n,
        "outfit_slot_accuracy": pct(slot, n),
        "category_accuracy": pct(cat, n),
        "colour_family_accuracy": pct(fam, n),
        "visual_neighbours_same_category": pct(neighbour, n),
    }
    print("  " + " | ".join(f"{k} {v}" for k, v in summary.items()))
    return {
        "summary": summary,
        "slot_confusions": dict(confusions.most_common(5)),
        "category_confusions": dict(category_confusions.most_common(8)),
    }


# ------------------------------------------------------------------ report


def write_report(mode: str, model: str, results: dict[str, Any]) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    (REPORTS / f"{mode}-latest.json").write_text(
        json.dumps(
            {"generated": stamp, "mode": mode, "model": model, **results},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    lines = [f"# Gabriella evaluation: {mode}", "", f"Generated {stamp} · model: `{model}`", ""]
    if "chat" in results:
        s = results["chat"]["summary"]
        lines += [
            "## Conversations",
            "",
            "| Metric | Value |",
            "| --- | --- |",
            f"| Cases passed | {s['passed']}/{s['cases']} ({s['pass_rate']}%) |",
            f"| Grounded recommendation rate | {s['grounded_rate']}% of {s['items_shown']} items |",
            f"| Stock-valid recommendation rate | {s['stock_valid_rate']}% |",
            f"| No-result rate | {s['no_result_rate']}% of cases (includes cases that expect none) |",
            f"| Turn latency p50 / p95 | {s['turn_latency_p50_ms']} / {s['turn_latency_p95_ms']} ms |",
            f"| Turns answered by the model | {s['model_answered_rate']}% |",
            f"| Tool-call success | {s['tool_call_success_rate']}% of {s['tool_calls']} calls |",
            f"| Server-side repairs | {s['server_repairs']} |",
            f"| Tokens used | {s['tokens']:,} |",
            "",
            "By capability: " + ", ".join(f"{g} {v}" for g, v in s["by_group"].items()),
            "",
            "| Case | Result | Items | Latency (ms) | Notes |",
            "| --- | --- | --- | --- | --- |",
        ]
        for r in results["chat"]["cases"]:
            note = (
                "; ".join(r["fails"]) if r["fails"] else (r["answer"] or "")[:90].replace("|", "/")
            )
            lines.append(
                f"| {r['id']} | {'✅' if r['passed'] else '❌'} | {r['items']} | "
                f"{'/'.join(map(str, r['latency_ms']))} | {note} |"
            )
        lines.append("")
    if "retrieval" in results:
        s = results["retrieval"]["summary"]
        lines += [
            "## Retrieval (precision@5)",
            "",
            f"Hybrid (full-text + CLIP text + CLIP image, RRF): **{s['hybrid_precision_at_5']}** · "
            f"keyword-only: **{s['lexical_only_precision_at_5']}** · "
            f"latency p50 / p95: {s['retrieval_latency_p50_ms']} / {s['retrieval_latency_p95_ms']} ms",
            "",
            "| Query | Hybrid | Keyword only |",
            "| --- | --- | --- |",
            *[
                f"| {q['query']} | {q['hybrid_p_at_5']:.1f} | {q['lexical_p_at_5']:.1f} |"
                for q in results["retrieval"]["queries"]
            ],
            "",
        ]
    if "image" in results:
        s = results["image"]["summary"]
        lines += [
            "## Photo understanding (CLIP zero-shot + nearest-photo vote + colour extraction)",
            "",
            f"On {s['images']} catalogue photos: outfit slot **{s['outfit_slot_accuracy']}%**, "
            f"exact category {s['category_accuracy']}%, colour family {s['colour_family_accuracy']}%, "
            f"visual neighbours in the same category {s['visual_neighbours_same_category']}%.",
            "",
            "Most common category mix-ups: "
            + (
                ", ".join(f"{k} ({v})" for k, v in results["image"]["category_confusions"].items())
                or "none"
            ),
            "",
        ]
    path = REPORTS / f"{mode}-latest.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--mode", choices=["fallback", "llm"], default="fallback")
    parser.add_argument("--only", choices=["chat", "retrieval", "image"])
    parser.add_argument("--case", help="run a single chat case by id")
    parser.add_argument(
        "--pace",
        type=float,
        default=None,
        help="seconds between chat turns (default 9 in llm mode, for free-tier rate limits)",
    )
    args = parser.parse_args()
    backend = chat_routes.default_backend()
    if args.mode == "fallback":
        chat_routes.default_backend = lambda: None  # type: ignore[assignment]
        model = "rule-based stylist"
    else:
        if backend is None:
            raise SystemExit("No model configured: set GROQ_API_KEY (or another provider) in .env")
        model = backend.name
    pace = args.pace if args.pace is not None else (9.0 if args.mode == "llm" else 0.0)
    results: dict[str, Any] = {}
    if args.only in (None, "chat"):
        print(f"chat ({model})")
        results["chat"] = await run_chat(pace, args.case)
    if args.only in (None, "retrieval"):
        print("retrieval")
        results["retrieval"] = await run_retrieval()
    if args.only in (None, "image"):
        print("image")
        results["image"] = await run_image()
    path = write_report(args.mode, model, results)
    print(f"\nreport: {path}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
