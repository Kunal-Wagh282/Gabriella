# Gabriella

An inventory-aware, multimodal fashion sales assistant for a **simulated** multi-brand retailer.
Gabriella recommends complete outfits — but only from products that exist in the catalogue and are
in stock, in the shopper's size, at the store they shop from.

> All brands, products, stores, prices and stock levels are generated. No real retailer is affiliated.

## Status

| Phase | Scope | State |
| --- | --- | --- |
| 1 | Schema, seeded catalogue, auth, catalogue UI, inventory model | ✅ Done |
| 2 | Hybrid search (SQL filters + pgvector) and product APIs | ✅ Done |
| 3 | Gabriella chat agent with tool calling and grounded product cards | ✅ Done |
| 4 | Outfit builder, cart, simulated checkout | Next |
| 5 | Personalisation from purchase history | Planned |
| 6 | Image upload and multimodal matching | Planned |
| 7 | Evaluation suite, observability, demo polish | Planned |

## Quick start (Docker)

```bash
cp .env.example .env        # optional: the defaults work for local use
docker compose up -d --build
```

The first build downloads the CLIP models (~0.6 GB) into the backend image. The first boot then runs the database migrations, seeds the catalogue and renders about 1,000 product images, which takes 1–2 minutes. After that, the worker embeds every product (about a minute) and keyword search upgrades to hybrid search. Then open:

- Web app: http://localhost:3000 (chat with Gabriella at `/chat`)
- API docs: http://localhost:8010/docs

### Choosing Gabriella's model (free options included)

Out of the box, with no key, Gabriella runs a deterministic **rule-based stylist**. It goes through the same grounding checks as the LLM modes. To make her conversational, pick one of these:

| Option | Cost | Setup |
| --- | --- | --- |
| **Groq** (recommended): open-weight `llama-3.3-70b-versatile` or `openai/gpt-oss-120b` | Free key, no card, rate-limited | Create a key at [console.groq.com/keys](https://console.groq.com/keys), set `GROQ_API_KEY=` in `.env` |
| **Ollama**: fully local and offline, e.g. Qwen 2.5 | Free | Install [Ollama](https://ollama.com), run `ollama pull qwen2.5:7b`, set `LLM_PROVIDER=ollama` in `.env` |
| Any OpenAI-compatible server (OpenRouter, vLLM, LM Studio) | Varies | `LLM_PROVIDER=openai_compatible`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` |
| Anthropic Claude | Paid API | `ANTHROPIC_API_KEY=` |

Then restart the API:

```bash
docker compose up -d api
```

The chat header shows which model is answering. On a laptop GPU with 4 GB of memory, a 7B Ollama model partly runs on the CPU and takes tens of seconds per turn; `OLLAMA_MODEL=qwen2.5:3b` is faster but makes more tool-call mistakes, which the validator catches. Product search never needs a key: CLIP embeddings run locally.
- Metrics: http://localhost:8010/metrics

Demo accounts (local only, configurable in `.env`):

| Role | Email | Password |
| --- | --- | --- |
| Shopper (Pune store) | `demo@gabriella.example` | `gabriella-demo` |
| Admin (restocks) | `admin@gabriella.example` | `gabriella-admin` |

Host ports are 5544 (Postgres), 6390 (Redis), 8010 (API) and 3000 (web), so they don't collide with other local stacks. Change them with `DB_HOST_PORT`, `REDIS_HOST_PORT`, `API_HOST_PORT` and `WEB_HOST_PORT`.

## Local development

Requires [uv](https://docs.astral.sh/uv/), Node 24 with pnpm, and Docker (for Postgres).

```bash
docker compose up -d db redis
```

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run python -m seed            # 500 products, stock for 6 stores, images in backend/media
uv run python -m app.workers.embed   # CLIP vectors for every product (downloads models once)
uv run uvicorn app.main:app --port 8010 --reload
```

Run the background worker to keep embeddings in sync as products change. It is optional locally, because `app.workers.embed` does the same job once:

```bash
cd backend && uv run arq app.workers.worker.WorkerSettings
```

```bash
cd frontend
pnpm install
pnpm dev                          # http://localhost:3000, proxies /api and /media to :8010
```

Rebuild the catalogue from scratch (asks for confirmation; wipes products, stock and users):

```bash
cd backend && uv run python -m seed --reset
```

### Tests and checks

```bash
cd backend && uv run pytest && uv run ruff check .
```

```bash
cd frontend && pnpm lint && pnpm exec tsc --noEmit
```

Backend tests run against the `gabriella_test` database, which is created automatically by `docker/postgres/init.sql`. Each run migrates it down and up with Alembic, so the migrations themselves get tested too. Tests use a deterministic hashing embedder (`EMBEDDING_BACKEND=hashing`), so they never need the CLIP models.

## Retrieval (Phase 2)

`GET /api/search?q=…` runs in five steps:

1. **Understand the query.** A deterministic parser (`app/retrieval/query_parser.py`) pulls out categories, colours, gender, sizes, price ranges and "on sale". For example, "beige chinos under ₹3k in M" becomes category chinos, colour beige, price ≤ 3000 and size M. Occasion and style words ("office", "sangeet", "smart casual") become **soft** signals, because each product carries only a few occasion tags and filtering on them would hide good matches.
2. **Apply hard filters in SQL first.** Only active products that pass the filters are considered. With `in_stock=true&store_id=…`, the requested size must actually be in stock at that store.
3. **Rank three ways within that set:**
   - Postgres full-text search on a weighted, trigger-maintained `tsvector`, using domain synonyms (pants→trousers, office→formal) and conversational stopwords.
   - CLIP query vector vs. product **text** vectors.
   - CLIP query vector vs. product **image** vectors (cross-modal: the words match the rendered flat-lay).

   Every eligible product gets a vector rank, so keyword hits keep their semantic credit. Vector-only results enter the list only if they're close to the best match.
4. **Fuse** the three lists with Reciprocal Rank Fusion (k = 60), then add small boosts for matching occasion and style.
5. **Be honest about match quality.** The result is `exact` when the shopper's own words match, `related` when only synonyms or vectors do, and `none` otherwise. The UI says "No exact matches — these are the closest pieces we have" for `related`.

Vectors only ever reorder products that already passed the SQL filters, so ranking can't surface something out of stock. `explain=true` returns each hit's lexical, text and image rank.

Related endpoints (the contracts Gabriella's tools will use in Phase 3):

| Endpoint | Purpose |
| --- | --- |
| `GET /api/search` | Hybrid search with the query interpretation, retrieval mode and latency |
| `GET /api/products/{id}/similar` | Substitutes from the same outfit slot with a compatible gender and a different style, ranked by blended CLIP text + image similarity, each with plain-language reasons. Add `size`, `store_id` and `in_stock=true` for "something like this in M at Pune" |
| `GET /api/variants/{id}/availability` | Exact stock for one size at one store, plus every other store |
| `POST /api/admin/embeddings/rebuild` | Queue a re-embed on the worker (admin only) |

The worker (arq on Redis) stores a hash of each product's embedded content, so a sync re-embeds only what changed. It runs on startup and hourly, and can be triggered on demand. Sold-out products keep their vectors; availability is decided by SQL at query time. Retrieval latency and match quality are exported as Prometheus metrics (`gabriella_retrieval_seconds`, `gabriella_search_total`).

## Gabriella, the agent (Phase 3)

Gabriella is a tool-use agent (`backend/app/agent/`) that runs on open-weight models through Groq or Ollama, or on Claude. The model never sees the catalogue up front: it has to call tools, and everything it shows passes server-side checks first.

**Tools.** Each is a thin, typed wrapper over the services above. Inputs are validated with Pydantic before anything runs.

| Tool | Does |
| --- | --- |
| `search_catalogue` | Hybrid search with hard filters (category, colour, gender, size, price, store stock). Returns compact product facts and the **in-stock sizes and variant IDs at the shopper's store** |
| `get_product` | Description, every size and stock at every store |
| `find_similar_products` | Substitutes from the same outfit slot, with reasons |
| `check_variant_inventory` | Exact stock for one size, here and elsewhere |
| `present_recommendation` | **The only way to answer.** A structured payload: a short message, groups of `{product_id, variant_id, role, reason}`, the updated constraints, and suggested replies |

**Grounding, enforced on the server** (`validator.py`). Every `present_recommendation` call is checked before the shopper sees anything:

- the product exists, is active, and was **returned by a tool in this conversation** (so a real but un-retrieved ID is rejected too);
- the variant belongs to that product, matches the shopper's size, and is in stock at their store;
- outfits fit the budget, and no product appears twice.

Problems go back to Claude as an error `tool_result` it must fix, up to twice. After that, `repair` swaps each invalid item for an in-stock alternative in the same slot (or drops it) and trims the outfit to the budget, so nothing invalid is ever displayed. Product cards are **re-hydrated from the database on every read**, so an old answer never shows stale stock.

**Conversation.**

- Constraints (occasion, budget, apparel and shoe sizes, gender, colours, formality) are kept per session, so "make it less formal" refines the last request instead of starting over. "Start fresh" clears them.
- Earlier turns are sent back as plain text, noting which product IDs were shown, so "swap the shoes" works.
- The store and the product in focus travel in the user turn, which keeps the system prompt and tools byte-stable for prompt caching.

**Provider-agnostic model layer** (`llm.py`, `openai_compat.py`). The agent loop speaks one internal tool-use format, and backends translate it:

- **`OpenAICompatibleBackend`** serves Groq, Ollama, OpenRouter, vLLM and LM Studio through the OpenAI chat-completions format. Open models are looser with tool calls, so parsing is lenient:
  - nested JSON sent as strings is decoded;
  - unparseable arguments are handed to the validator to reject;
  - Groq's `tool_use_failed` errors are retried.
- **`AnthropicBackend`** serves Claude, with streaming, adaptive thinking, prompt caching and server-side refusal fallbacks.

The same loop, tools and validator run whichever model is behind it. That matters most for smaller open models: their mistakes are caught on the server instead of reaching shoppers. Tool choice stays `auto`; the prompt and a one-time nudge make sure the turn ends in `present_recommendation`. If the model call fails (model offline, rate limit), the turn degrades to the deterministic stylist instead of erroring, and the trace records why.

**Deterministic stylist** (`fallback.py`), used when no API key is set:

- **Same contract:** the query parser, constraint carry-over and the same validator.
- **Outfit composer:** a per-slot shortlist from hybrid search under hard stock, size and budget filters, then a search over combinations scored on formality, occasion fit, retrieval rank and colour harmony (`styling.py`), under the whole budget.
- **Dress-code rules:** no shorts or caps at a wedding.
- **Ethnic wear** for weddings and festivals.
- **Honest budgets:** it says "the most affordable complete look here is ₹5,897" rather than failing silently.

**Streaming and observability.** `POST /api/chat/sessions/{id}/messages` streams server-sent events: `status` lines while tools run ("Searching chinos in M at Pune…"), then one `message` carrying the validated, hydrated answer. Every turn writes an `agent_traces` row with the mode, model, each tool call (input, result count, latency, errors), validation attempts and repairs, model requests, input/output/cache-read tokens, and latency. It also updates the `gabriella_agent_turns_total`, `gabriella_agent_turn_seconds` and `gabriella_recommended_items_total` metrics.

Agent tests replay scripted models (`ScriptedBackend`, and a fake OpenAI-format client for the Groq/Ollama path), so CI never calls a real model. They cover a hallucinated ID being rejected and then fixed, repair after repeated failures, refusals, and a turn that ends without a recommendation.

## Architecture

```
Browser ──► Next.js 16 (App Router, RSC, Tailwind)
              │  /api/*, /media/*  (rewrites — cookies stay first-party)
              ▼
            FastAPI ──► PostgreSQL 16 + pgvector
              │           products (+ weighted tsvector) · variants · inventory(variant × store)
              │           product_embeddings (CLIP text + image, HNSW) · inventory_movements
              │           users · auth_sessions
              ├─ /media   generated flat-lay product images
              └─ Redis ◄── arq worker (embeds new or changed products)
```

- **The database is the source of truth.** Price, size and stock always come from PostgreSQL. `product_embeddings` (512-d CLIP text and image vectors) is used only for discovery and never for availability.
- **Inventory** is tracked per variant (size) per store. A `CHECK (on_hand >= 0)` constraint backs it up, every change takes a row lock (`SELECT … FOR UPDATE`), and every change is written to an append-only `inventory_movements` table. A test races 10 buyers for the last unit and asserts that exactly one succeeds.
- **Auth** uses short-lived JWT access tokens and rotating refresh tokens, both in httpOnly SameSite cookies. Refresh tokens are stored hashed; replaying a used one revokes every session for that user.
- **Observability:** structured JSON logs carry a request ID (also returned as `X-Request-ID`), Prometheus serves `/metrics`, `/healthz` and `/readyz` report status, and every error uses one envelope: `{"error": {"code", "message", "request_id"}}`.
- **Catalogue data** comes from a deterministic generator (`backend/seed/`). It covers 30 categories, 12 fictional brands, 39 colours and realistic INR pricing, and deliberately leaves sizes sold out at some stores. Product images are rendered with Pillow from each product's own category, colour and pattern, so the picture always matches the data (which matters for image search in Phase 6).

## Repository layout

```
backend/
  app/          FastAPI app: core (config, logging, errors, metrics), db, schemas, services, routes
    agent/      Gabriella: tools, Claude loop, validator, deterministic stylist, chat service
    retrieval/  query parser, hybrid search, similar products
    ml/         embedding backends (CLIP via fastembed, hashing for tests)
    workers/    arq worker and one-off embed command
  alembic/      migrations
  seed/         catalogue taxonomy, generator, image renderer, loader
  tests/        API, retrieval, inventory-concurrency and seed-integrity tests
frontend/
  src/app/      routes: / , /shop, /product/[slug], /chat, /login, /signup, /account
  src/components, src/lib
docker/         Postgres init script
docker-compose.yml, .env.example
```
