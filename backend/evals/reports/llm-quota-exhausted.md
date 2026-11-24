# Gabriella evaluation: llm (daily token quota exhausted mid-run)

Generated 2026-11-23 20:03 UTC · model: `groq:openai/gpt-oss-120b`

## Conversations

| Metric | Value |
| --- | --- |
| Cases passed | 26/26 (100.0%) |
| Grounded recommendation rate | 100.0% of 74 items |
| Stock-valid recommendation rate | 100.0% |
| No-result rate | 23.1% of cases (includes cases that expect none) |
| Turn latency p50 / p95 | 229 / 2924 ms |
| Turns answered by the model | 24.1% |
| Tool-call success | 97.1% of 35 calls |
| Server-side repairs | 1 |
| Tokens used | 16,090 |

By capability: clarify 1/1, image 3/3, no-result 3/3, occasion 4/4, outfit 3/3, personalisation 2/2, refine 3/3, search 4/4, similar 1/1, stock 2/2

| Case | Result | Items | Latency (ms) | Notes |
| --- | --- | --- | --- | --- |
| dinner-budget | ✅ | 3 | 5750 | Here’s a relaxed dinner outfit under ₹6,000, all in your size. The charcoal tee pairs smoo |
| office-men | ✅ | 4 | 2343 | Here’s a polished office look in your sizes, with coordinated colours and a classic feel. |
| sangeet-women | ✅ | 4 | 2512 | Here’s a vibrant sangeet look under ₹12,000, perfect for the celebration. |
| party-women | ✅ | 4 | 2924 | Here’s a chic party outfit under ₹9,000 that balances comfort and sparkle. |
| travel-men | ✅ | 4 | 1850 | Here’s a relaxed travel look that’s all in stock for you in Pune, perfect for long journey |
| navy-office | ✅ | 4 | 288 | Here's an office look, all in stock at Pune in your sizes. |
| budget-impossible | ✅ | 0 | 324 | I couldn't fit a full outfit in stock at Pune within ₹2,000. The most affordable complete  |
| ask-gender | ✅ | 0 | 85 | Happy to put a look together. Are you shopping for menswear or womenswear? |
| less-formal | ✅ | 4 | 251/340 | Here's an office look, all in stock at Pune in your sizes. |
| refine-budget | ✅ | 3 | 250/262 | Here's an office look under ₹7,000, all in stock at Pune in your sizes. |
| start-fresh | ✅ | 0 | 290/31 | Fresh start. What are you shopping for today? |
| white-sneakers | ✅ | 1 | 163 | Here's what I found in stock at Pune. |
| black-dress-sale | ✅ | 3 | 173 | Nothing matching is on sale right now, so here are full-price options in stock at Pune. |
| kurta-budget | ✅ | 2 | 229 | Here's what I found in stock at Pune. |
| linen-shirt-L | ✅ | 6 | 162 | Here's what I found in stock at Pune. |
| mumbai-stock | ✅ | 1 | 170 | Here's what I found. None are in stock at Mumbai, but other stores have them. |
| similar-chinos-M | ✅ | 6 | 124 | Here are pieces close to the straight chinos that are in stock at Pune. |
| availability-sold-out | ✅ | 4 | 157 | The relaxed garment-dyed cotton chinos in M is sold out at Pune, but Bengaluru, Mumbai, On |
| style-product | ✅ | 4 | 195 | Here's an office look, all in stock at Pune in your sizes. |
| impossible-filters | ✅ | 0 | 992 | I'm sorry, we don't have gold sneakers in UK size 3 right now. If you’re open to a differe |
| off-topic | ✅ | 0 | 132 | I'm Gabriella, the stylist here, so I can only help with clothes from our store. What are  |
| personal-picks | ✅ | 6 | 158 | Based on what you've bought before, here are new pieces in your usual sizes. |
| personal-off | ✅ | 0 | 131 | I'm Gabriella, the stylist here, so I can only help with clothes from our store. What are  |
| photo-shirt-outfit | ✅ | 3 | 303 | Here's a versatile look, all in stock at Pune in your sizes. |
| photo-sneaker-similar | ✅ | 6 | 103 | These look closest to your light grey sneaker, in stock at Pune. |
| photo-dress-shoes | ✅ | 2 | 176 | Here's a versatile look, all in stock at Pune in your sizes. |
