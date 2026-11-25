# Gabriella evaluation: llm

Generated 2026-11-25 18:27 UTC · model: `groq:openai/gpt-oss-120b`

## Conversations

| Metric | Value |
| --- | --- |
| Cases passed | 26/26 (100.0%) |
| Grounded recommendation rate | 100.0% of 63 items |
| Stock-valid recommendation rate | 100.0% |
| No-result rate | 26.9% of cases (includes cases that expect none) |
| Turn latency p50 / p95 | 2118 / 10149 ms |
| Turns answered by the model | 100.0% |
| Tool-call success | 98.2% of 57 calls |
| Server-side repairs | 0 |
| Tokens used | 63,865 |

By capability: clarify 1/1, image 3/3, no-result 3/3, occasion 4/4, outfit 3/3, personalisation 2/2, refine 3/3, search 4/4, similar 1/1, stock 2/2

| Case | Result | Items | Latency (ms) | Notes |
| --- | --- | --- | --- | --- |
| dinner-budget | ✅ | 3 | 11782 | Here’s a relaxed dinner look under ₹6,000, all in your size. |
| office-men | ✅ | 4 | 1831 | Here’s a polished office outfit in your sizes, with pieces that coordinate nicely for a sm |
| sangeet-women | ✅ | 4 | 2118 | Here’s a festive sangeet outfit that stays within your ₹12,000 budget and fits your size S |
| party-women | ✅ | 4 | 3216 | Here’s a chic party look under ₹9,000, perfect for a stylish evening. |
| travel-men | ✅ | 4 | 2212 | Here’s a comfortable travel look in XL, perfect for moving through airports and exploring  |
| navy-office | ✅ | 4 | 3434 | Here’s a sharp navy office look that balances professionalism with a relaxed vibe. |
| budget-impossible | ✅ | 0 | 2036 | I'm sorry, we don't have a complete formal men's outfit under ₹2,000 at this store. The mo |
| ask-gender | ✅ | 0 | 906 | Are you looking for men's or women's dinner attire? |
| less-formal | ✅ | 4 | 4338/10149 | Here’s a relaxed office outfit with lighter tones and casual sneakers, perfect for a smart |
| refine-budget | ✅ | 3 | 2373/2837 | A crisp olive linen shirt with relaxed black chinos and tan tassel loafers stays under ₹7, |
| start-fresh | ✅ | 0 | 2830/4312 | Fresh start. What are you shopping for today? |
| white-sneakers | ✅ | 1 | 1136 | These white leather court sneakers are in stock in UK 9 and match your colour request. |
| black-dress-sale | ✅ | 3 | 3014 | I’m sorry, we don’t have any black dresses on sale right now, but here are a few timeless  |
| kurta-budget | ✅ | 2 | 1526 | Here are two silk‑blend kurtas under ₹2,500 that match your style and budget. |
| linen-shirt-L | ✅ | 2 | 1669 | Here are the linen shirts we have in size L for men. |
| mumbai-stock | ✅ | 0 | 1792 | I'm sorry, we don't have any white sneakers in UK 9 at our Bandra store right now. You cou |
| similar-chinos-M | ✅ | 6 | 2235 | Sure, here are a few chinos in size M that are similar to your straight beige pair. |
| availability-sold-out | ✅ | 4 | 2047 | The relaxed garment‑dyed cotton chinos in size M are currently sold out at our Pune store, |
| style-product | ✅ | 4 | 3722 | Pair your navy non‑iron shirt with beige straight chinos, tan tassel loafers, and a tan ca |
| impossible-filters | ✅ | 0 | 1773 | I'm sorry, we don't have gold sneakers in UK 3 at the moment. Would you be open to a diffe |
| off-topic | ✅ | 0 | 945 | I’m sorry, I can only help with clothing from our store. Let me know what you’re looking f |
| personal-picks | ✅ | 4 | 1878 | Here are some fresh picks that echo your classic, smart‑casual style while staying within  |
| personal-off | ✅ | 0 | 945 | Sure! To suggest fresh picks that match your style, could you share what you bought previo |
| photo-shirt-outfit | ✅ | 2 | 2068 | Pair your navy shirt with sleek black chinos and classic black chukka boots for a sharp, o |
| photo-sneaker-similar | ✅ | 3 | 1720 | Here are a few sneakers that echo the light grey shade of your own pair. |
| photo-dress-shoes | ✅ | 2 | 2928 | A sleek grey‑melange low‑top sneaker keeps the look relaxed yet polished, and a navy overs |
