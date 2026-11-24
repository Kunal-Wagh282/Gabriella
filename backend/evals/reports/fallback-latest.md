# Gabriella evaluation: fallback

Generated 2026-11-23 20:04 UTC · model: `rule-based stylist`

## Conversations

| Metric | Value |
| --- | --- |
| Cases passed | 26/26 (100.0%) |
| Grounded recommendation rate | 100.0% of 74 items |
| Stock-valid recommendation rate | 100.0% |
| No-result rate | 23.1% of cases (includes cases that expect none) |
| Turn latency p50 / p95 | 137 / 320 ms |
| Turns answered by the model | 0.0% |
| Tool-call success | 96.6% of 29 calls |
| Server-side repairs | 1 |
| Tokens used | 0 |

By capability: clarify 1/1, image 3/3, no-result 3/3, occasion 4/4, outfit 3/3, personalisation 2/2, refine 3/3, search 4/4, similar 1/1, stock 2/2

| Case | Result | Items | Latency (ms) | Notes |
| --- | --- | --- | --- | --- |
| dinner-budget | ✅ | 3 | 3425 | Here's a dinner look under ₹6,000, all in stock at Pune in your sizes. |
| office-men | ✅ | 4 | 320 | Here's an office look, all in stock at Pune in your sizes. |
| sangeet-women | ✅ | 4 | 210 | Here's a wedding look under ₹12,000, all in stock at Pune in your sizes. |
| party-women | ✅ | 4 | 230 | Here's a party look under ₹9,000, all in stock at Pune in your sizes. |
| travel-men | ✅ | 4 | 230 | Here's a travel look, all in stock at Pune in your sizes. |
| navy-office | ✅ | 4 | 254 | Here's an office look, all in stock at Pune in your sizes. |
| budget-impossible | ✅ | 0 | 259 | I couldn't fit a full outfit in stock at Pune within ₹2,000. The most affordable complete  |
| ask-gender | ✅ | 0 | 33 | Happy to put a look together. Are you shopping for menswear or womenswear? |
| less-formal | ✅ | 4 | 234/216 | Here's an office look, all in stock at Pune in your sizes. |
| refine-budget | ✅ | 3 | 184/192 | Here's an office look under ₹7,000, all in stock at Pune in your sizes. |
| start-fresh | ✅ | 0 | 273/24 | Fresh start. What are you shopping for today? |
| white-sneakers | ✅ | 1 | 101 | Here's what I found in stock at Pune. |
| black-dress-sale | ✅ | 3 | 144 | Nothing matching is on sale right now, so here are full-price options in stock at Pune. |
| kurta-budget | ✅ | 2 | 85 | Here's what I found in stock at Pune. |
| linen-shirt-L | ✅ | 6 | 108 | Here's what I found in stock at Pune. |
| mumbai-stock | ✅ | 1 | 126 | Here's what I found. None are in stock at Mumbai, but other stores have them. |
| similar-chinos-M | ✅ | 6 | 124 | Here are pieces close to the straight chinos that are in stock at Pune. |
| availability-sold-out | ✅ | 4 | 77 | The relaxed garment-dyed cotton chinos in M is sold out at Pune, but Bengaluru, Mumbai, On |
| style-product | ✅ | 4 | 137 | Here's an office look, all in stock at Pune in your sizes. |
| impossible-filters | ✅ | 0 | 94 | I couldn't find anything matching that. Could you describe it differently? |
| off-topic | ✅ | 0 | 99 | I'm Gabriella, the stylist here, so I can only help with clothes from our store. What are  |
| personal-picks | ✅ | 6 | 119 | Based on what you've bought before, here are new pieces in your usual sizes. |
| personal-off | ✅ | 0 | 78 | I'm Gabriella, the stylist here, so I can only help with clothes from our store. What are  |
| photo-shirt-outfit | ✅ | 3 | 247 | Here's a versatile look, all in stock at Pune in your sizes. |
| photo-sneaker-similar | ✅ | 6 | 51 | These look closest to your light grey sneaker, in stock at Pune. |
| photo-dress-shoes | ✅ | 2 | 119 | Here's a versatile look, all in stock at Pune in your sizes. |

## Retrieval (precision@5)

Hybrid (full-text + CLIP text + CLIP image, RRF): **0.914** · keyword-only: **0.843** · latency p50 / p95: 45.2 / 75.5 ms

| Query | Hybrid | Keyword only |
| --- | --- | --- |
| beige chinos | 0.6 | 0.6 |
| denim jacket | 1.0 | 1.0 |
| office shoes for men | 1.0 | 1.0 |
| cosy winter layer | 1.0 | 0.0 |
| light summer shirt | 1.0 | 1.0 |
| black party dress | 0.6 | 0.6 |
| outfit for a sangeet | 1.0 | 1.0 |
| white sneakers | 0.6 | 0.6 |
| formal trousers | 1.0 | 1.0 |
| leather belt | 1.0 | 1.0 |
| something to wear to a beach holiday | 1.0 | 1.0 |
| smart office blazer | 1.0 | 1.0 |
| ethnic footwear for a wedding | 1.0 | 1.0 |
| warm hoodie | 1.0 | 1.0 |

## Photo understanding (CLIP zero-shot + nearest-photo vote + colour extraction)

On 60 catalogue photos: outfit slot **96.7%**, exact category 75.0%, colour family 60.0%, visual neighbours in the same category 79.3%.

Most common category mix-ups: casual-shirts -> formal-shirts (4), polos -> formal-shirts (2), casual-shirts -> kurtas (2), chinos -> trousers (1), blouses-tops -> formal-shirts (1), shorts -> trousers (1), blouses-tops -> t-shirts (1), sandals -> caps (1)
