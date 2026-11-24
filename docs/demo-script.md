# Demo script (about 3 minutes)

> A captioned recording of this walkthrough is in [`docs/media/gabriella-demo.mp4`](media/gabriella-demo.mp4). To re-record it after changing the app (it needs the Docker stack running and Groq quota):
>
> ```bash
> uv run --no-project --with playwright --with imageio-ffmpeg python scripts/record_demo.py
> ```

Use this for a live walkthrough or a screen recording. Each step shows one capability, and the "Point out" line is the thing to say.

**Setup:** `docker compose up -d`, with `GROQ_API_KEY` set in `.env`. Open http://localhost:3000. Keep the Pune store selected (it's the default for the demo account).

## 1. Grounded outfit, budget and sizes (40 s)

Open **Chat** (`/chat`) without signing in and type:

> Casual dinner outfit for men under ₹6,000, I wear M and UK 9

**Point out:**

- The status lines while it works ("Putting together a look at Pune…").
- Every card is a real product with a size **in stock at Pune**, and the total fits the budget.
- The header says which model answered ("Powered by openai/gpt-oss-120b on Groq").

## 2. Refine across turns (20 s)

> Make it less formal

then

> Swap the shoes

**Point out:** it remembers the budget and sizes, and only changes what you asked for.

## 3. Honest failure (15 s)

> Formal outfit for men under ₹2,000

**Point out:** it doesn't invent a cheaper product. It says what the cheapest complete look actually costs and offers a next step.

## 4. Stock awareness (25 s)

Open any product page, pick a size, and look at the store-by-store stock panel. Then, in a chat about that product:

> Do you have something similar in M?

**Point out:** the substitutes are in stock in M at Pune, and each card explains why it's similar ("Same fabric", "₹800 less").

## 5. Photo of your own clothes (30 s)

Click the camera button and upload a photo of a shirt (any product image from `/shop` works as a stand-in), then ask:

> What trousers and shoes go with this? Menswear, M and UK 9

**Point out:**

- The photo card shows what it thinks the item is, and how sure it is ("Looks like a navy formal shirt · 88% sure").
- The outfit is built *around* your shirt, so it doesn't suggest another top.

Then ask "Show me similar ones" to run a visual search on the photo.

## 6. Personalisation (25 s)

Sign in as `demo@gabriella.example` / `gabriella-demo`. Start a new chat:

> Suggest something new based on what I bought before

**Point out:**

- The **Picked for you** group uses the shopper's usual colours, sizes and price band.
- It never suggests something they already own.
- Switch the **Personalised** toggle off in the chat header and ask again: the picks go back to generic.

## 7. Cart and checkout (25 s)

On an outfit, click **Add look**. The whole outfit goes into the bag in the chosen sizes. Open **Bag** and **Place order**.

**Point out:** checkout locks the stock rows, re-checks them and decrements them in one transaction, so two shoppers can never buy the last unit. The order shows up under **Orders**, and each unit sold is logged in `inventory_movements`.

## 8. Under the hood (optional, 20 s)

- Open http://localhost:8010/docs to show the typed API.
- Show [evaluation.md](evaluation.md): 26 scripted conversations, re-verified against the database, with 100% of displayed items grounded and in stock.
- Show a row in the `agent_traces` table (model requests, tokens, validation repairs per turn).

## Recording tips

- Record at 1440×900 with the browser zoom at 110%. Hide the bookmarks bar.
- Groq's free tier allows 8,000 tokens a minute and 200,000 a day for `gpt-oss-120b`, which is roughly 80–100 chat turns. Don't run the eval suite on the day you record. Wait a few seconds between turns; if you hit a limit, the answer still arrives, from the rule-based stylist.
- Trim the waiting out of the video, and keep it under 3 minutes.
