# Evaluation

Gabriella's evaluation suite lives in `backend/evals/`. It answers three questions:

1. **Conversations:** does she give correct, grounded answers across the jobs a shopper actually brings?
2. **Retrieval:** does hybrid search beat plain keyword search?
3. **Vision:** how well does she read a photo of someone's own garment?

```bash
cd backend
uv run python -m evals.run                         # rule-based stylist: no model, about 2 minutes
uv run python -m evals.run --mode llm --only chat  # the model configured in .env, paced for free tiers
uv run python -m evals.run --only chat --case less-formal   # one case
```

Reports are written to `backend/evals/reports/<mode>-latest.md` (readable) and `.json` (every case, answer, latency and token count).

## How conversations are scored

Each of the 26 cases (`evals/cases.py`) is a scripted conversation of one or two turns. It runs through the **real HTTP API** (in-process, with real Postgres, CLIP and model), exactly as the web app calls it. That includes sign-in, picking a store, focusing a product and uploading a photo.

**Universal checks** run on every answer. They are deliberately independent of the server's own validator: the runner re-reads the database itself.

- **Grounded:** every displayed product exists, is active, and is shown at its real price.
- **Stock-valid:** every displayed size is in stock at the shopper's store (or, for size-less picks, at least one size is).
- **Budget:** outfit totals, and individual picks, are within the stated budget.
- **Sizes:** apparel and footwear cards use the sizes the shopper gave.

**Case-specific checks** cover the answer type (outfit, picks, alternatives, question or none), required and forbidden outfit slots, allowed categories (for example, ethnic wear for a sangeet), colour family, gender, a formality range, a formality *drop* after "make it less formal", the share of personalised picks in the shopper's colour families, no re-recommending owned items, and key phrases in the message (with paraphrases allowed).

| Group | Cases | What it exercises |
| --- | --- | --- |
| outfit | 3 | Budget, sizes and slots; styling around a product; colour requests |
| occasion | 4 | Office, sangeet (ethnic wear), party, travel (formality ranges) |
| refine | 3 | "Make it less formal", "keep it under 7000", "start fresh" |
| search | 4 | Product discovery with size, colour, sale and budget filters |
| stock | 2 | A different store; a sold-out size on a focused product |
| similar | 1 | Substitutes in the shopper's size |
| image | 3 | Outfit around a photographed shirt; visual search from a sneaker; shoes for a dress |
| personalisation | 2 | Picks from purchase history, and the same request with personalisation off |
| clarify | 1 | Asking for missing information (menswear or womenswear?) |
| no-result | 3 | An impossible budget, impossible filters, an off-topic question |

## Results

<!-- EVAL-TABLE:START -->
| Metric | Groq · `openai/gpt-oss-120b` (pipeline mode) | Rule-based stylist |
| --- | --- | --- |
| Cases passed | **26 / 26** | **26 / 26** |
| Grounded items (exist, active, correct price) | 100% of 63 | 100% of 74 |
| Stock-valid items (size in stock at the store) | 100% | 100% |
| Turns answered by the model | 100% | – |
| Tool-call success | 98.2% of 57 calls | – |
| Turn latency p50 / p95 | 2,118 / 10,149 ms | 137 / 320 ms |
| Tokens used (29 turns) | 63,865 (≈ 2,200 per turn) | 0 |

**History.** The first Groq run passed 23/26:

- `availability-sold-out` said "out of stock" and `off-topic` said "clothing". Both were correct answers failing over-literal phrase checks, which now accept paraphrases.
- `start-fresh` was a real bug: the model kept the old context. A reset now bypasses the model.

The run above came after those fixes, plus the schema fix for `null` variant IDs and the reason check described below.

**Resilience run.** A run made with Groq's free-tier cap of **200,000 tokens per day** already used up still passed **26/26**, with 100% of 74 items grounded and in stock. Every rate-limited turn was answered by the rule-based draft ([`llm-quota-exhausted.md`](../backend/evals/reports/llm-quota-exhausted.md)).

To refresh these numbers, run `uv run python -m evals.run --mode llm --only chat`. It needs about 65k tokens and 12 minutes at the default pacing.
<!-- EVAL-TABLE:END -->

### What the numbers mean

- **The two 100% rows are guaranteed by design, and the suite confirms it.** The validator and repair step make an ungrounded or out-of-stock card impossible to display, whatever the model does. The suite checks this independently.
- **"Answered by the model"** is the share of turns where Groq's answer was used. The rest hit a free-tier limit (8,000 tokens per minute, 200,000 per day) and were answered by the rule-based draft instead. The conversation continues either way.
- **Rule-based latency** is milliseconds because no model is called. Groq turns cost one model request and about 2,000 tokens each, in pipeline mode.

## Retrieval

There are 14 queries with the categories (and sometimes colours) a correct result must have. Precision@5 is the share of the top 5 results that are correct, with no stock filter. The comparison is the full hybrid ranker vs. keyword-only (Postgres full-text search with the same parser and filters).

<!-- RETRIEVAL:START -->
| | Hybrid (full-text + CLIP text + CLIP image, RRF) | Keyword only |
| --- | --- | --- |
| Mean precision@5 (14 queries) | **0.914** | 0.843 |
| Latency p50 / p95 | 51 / 85 ms | – |

Per-query scores are in [`fallback-latest.md`](../backend/evals/reports/fallback-latest.md).
<!-- RETRIEVAL:END --><!-- RETRIEVAL:END -->

Most queries name the product ("leather belt"), and full-text search alone already gets those right. The hybrid ranker earns its keep on **vague, intent-style queries** with no product noun. For example, "cosy winter layer" scores 1.0 with hybrid vs 0.0 with keywords only, because CLIP's text and image vectors connect "cosy winter" to knitwear and jackets. The misses ("beige chinos" and "white sneakers" at 0.6) come from colour: both rankers also return near-colour items (stone, off-white), which the strict colour-family check counts as wrong.

## Photo understanding

60 random catalogue images, each analysed as if it were a shopper's upload, **with the image itself excluded from the nearest-neighbour vote** so it can't recognise itself.

<!-- VISION:START -->
| Metric | Result |
| --- | --- |
| Outfit slot correct | **96.7%** |
| Exact category (30 classes) | 75.0% (CLIP zero-shot alone: 61.7%) |
| Colour family | 60.0% |
| 5 nearest catalogue photos in the same category | 79.3% |

Most common category mix-ups: casual shirt → formal shirt, polo → formal shirt, casual shirt → kurta, chinos → trousers.
<!-- VISION:END --><!-- VISION:END -->

- **The outfit slot** (top, bottom, one-piece, footwear, outerwear or accessory) is what the stylist needs to build around a garment, and it is nearly always right.
- **Blending CLIP zero-shot with a vote from the 12 nearest catalogue photos** raised exact-category accuracy from 61.7% (zero-shot alone) to 75.0%. Most remaining confusions are between neighbouring categories (casual vs formal shirts, loafers vs formal shoes), which lead to similar outfits anyway.
- **Colour** is the weakest signal. Light garments on light backgrounds get confused with the background, and neighbouring families (beige vs white, navy vs black) blur. The chat shows the guess and its confidence so the shopper can correct it.
- **Caveat:** catalogue images are clean, rendered flat-lays. Real phone photos, with people, hangers and clutter, will score lower.

## Changes made because of the evals

The first full run failed 5 of 26 cases. Each failure was a real bug, now fixed:

| Failing case | Root cause | Fix |
| --- | --- | --- |
| personal-picks | "Picked for you" ignored the shopper's size. The validator then swapped in a substitute the shopper **already owned** | Size filter on personal picks. The repair step now never substitutes an owned product |
| photo-sneaker-similar | A white sneaker photo was read as a cap (CLIP zero-shot) | Blend in a nearest-catalogue-photo vote: category accuracy went from 62% to 75% |
| similar-chinos-M | "Something similar in M?" was routed to the stock check, not the substitute search | Similarity intent takes precedence |
| budget-impossible | When the budget emptied a whole slot, the reply was generic | Report the cheapest complete look ("comes to about ₹7,097") |
| black-dress-sale | No black dress is on sale, so the answer was "nothing found" | Fall back to full-price matches and say so |

The Groq runs and the demo recording surfaced three more:

- **The model ignored "start fresh"** and carried the old occasion forward. A reset now skips the model entirely (it is deterministic, and it saves a request).
- **Stale reasons under swapped products.** The demo recording showed "white leather court sneakers…" as the reason under a pair of tassel loafers: the model had swapped the item but kept the old reason. The validator now checks that each reason describes its own product, and rewrites it from real attributes if not (tested against all 500 catalogue products).
- **Groq rejected some answers before they reached the server.** Groq validates tool arguments against the JSON schema, and the model sent `"variant_id": null` for sizes it hadn't been given, while the schema said integer-only. Those turns silently fell back to the draft. The schema now allows `null`, and the server fills in the in-stock variant.
