"""Record the Gabriella demo video by driving the running app in a real browser.

    docker compose up -d                       # the app at http://localhost:3000
    uv run --no-project --with playwright --with imageio-ffmpeg python scripts/record_demo.py

Writes docs/media/gabriella-demo.mp4 (full walkthrough) and docs/media/gabriella-demo.gif
(a short loop for the README). Uses the installed Chrome, so no browser download is needed.
Each chat turn uses the configured model (about 2k tokens on Groq); run it on a day with quota.
"""

import shutil
import subprocess
import sys
import time
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import Page, sync_playwright

BASE = "http://localhost:3000"
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "media"
RAW = OUT / "_raw"
SIZE = {"width": 1280, "height": 800}
DEMO_EMAIL, DEMO_PASSWORD = "demo@gabriella.example", "gabriella-demo"

CAPTION_JS = """
([text, sub]) => {
  let el = document.getElementById('__demo_caption');
  if (!el) {
    el = document.createElement('div');
    el.id = '__demo_caption';
    el.style.cssText = `position:fixed;left:50%;bottom:28px;transform:translateX(-50%);z-index:99999;
      max-width:880px;padding:14px 22px;background:rgba(24,20,16,.92);color:#f7f3ec;border-radius:12px;
      font:500 19px/1.35 system-ui,sans-serif;text-align:center;box-shadow:0 10px 30px rgba(0,0,0,.25);
      transition:opacity .3s;pointer-events:none`;
    document.body.appendChild(el);
  }
  if (!text) { el.style.opacity = 0; return; }
  el.innerHTML = text + (sub ? `<div style="font-weight:400;font-size:14px;opacity:.75;margin-top:4px">${sub}</div>` : '');
  el.style.opacity = 1;
}
"""

CARD_JS = """
([title, lines]) => {
  const el = document.createElement('div');
  el.id = '__demo_card';
  el.style.cssText = `position:fixed;inset:0;z-index:100000;background:#1a1612;color:#f7f3ec;display:flex;
    flex-direction:column;align-items:center;justify-content:center;gap:18px;font-family:system-ui,sans-serif;
    transition:opacity .5s`;
  el.innerHTML = `<div style="font:400 64px/1.1 Georgia,serif;letter-spacing:.5px">${title}</div>` +
    lines.map((l, i) => `<div style="font-size:${i ? 18 : 24}px;opacity:${i ? .7 : .95};max-width:900px;text-align:center">${l}</div>`).join('');
  document.body.appendChild(el);
}
"""


def caption(page: Page, text: str | None, sub: str | None = None, hold: float = 0) -> None:
    page.evaluate(CAPTION_JS, [text, sub])
    if hold:
        page.wait_for_timeout(int(hold * 1000))


def card(page: Page, title: str, lines: list[str], hold: float, keep: bool = False) -> None:
    page.evaluate(CARD_JS, [title, lines])
    page.wait_for_timeout(int(hold * 1000))
    if keep:
        return
    page.evaluate("document.getElementById('__demo_card').style.opacity = 0")
    page.wait_for_timeout(500)
    page.evaluate("document.getElementById('__demo_card').remove()")


def ask(page: Page, text: str, read: float = 4.0) -> None:
    box = page.get_by_label("Message Gabriella")
    box.click()
    box.press_sequentially(text, delay=28)
    page.wait_for_timeout(300)
    page.get_by_label("Send").click()
    working = page.locator("[aria-label='Gabriella is working']")
    try:
        working.wait_for(state="attached", timeout=5_000)
    except Exception:  # noqa: BLE001 - answered instantly
        pass
    working.wait_for(state="detached", timeout=120_000)
    page.wait_for_timeout(400)
    # Bring the newest answer to the top of the view (not past it into the footer).
    page.evaluate("""() => {
      const answers = [...document.querySelectorAll('main div.max-w-full')];
      answers.at(-1)?.scrollIntoView({block: 'start', behavior: 'smooth'});
    }""")
    page.wait_for_timeout(int(read * 1000))


def scroll(page: Page, dy: int, steps: int = 6) -> None:
    page.mouse.move(640, 450)
    for _ in range(steps):
        page.mouse.wheel(0, dy / steps)
        page.wait_for_timeout(90)


def new_chat(page: Page) -> None:
    page.goto(f"{BASE}/chat")
    page.evaluate("localStorage.removeItem('gb_chat_session')")
    page.goto(f"{BASE}/chat")
    page.get_by_label("Message Gabriella").wait_for()
    page.wait_for_timeout(600)


def record() -> tuple[Path, list[tuple[str, float]]]:
    """Returns the raw video and (scene, start second) marks for the GIF."""
    shutil.rmtree(RAW, ignore_errors=True)
    marks: list[tuple[str, float]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        ctx = browser.new_context(viewport=SIZE, record_video_dir=str(RAW), record_video_size=SIZE)
        page = ctx.new_page()
        t0 = time.monotonic()

        def mark(name: str) -> None:
            marks.append((name, time.monotonic() - t0))

        # 1. Title
        page.goto(BASE)
        page.wait_for_load_state("networkidle")
        card(page, "Gabriella", [
            "An AI stylist that only recommends what's actually on the shelf",
            "Open-weight LLM on Groq · CLIP · FastAPI · Postgres + pgvector · Next.js",
        ], 4.0)
        caption(page, "A simulated Indian fashion retailer: 500 products, 12 brands, stock per size in 6 stores", hold=3.5)

        # 2. Store + search
        page.get_by_role("button", name="Choose store").click()
        page.wait_for_timeout(700)
        page.get_by_role("option").filter(has_text="Pune").first.click()
        caption(page, "Pick your store: everything is checked against its live stock", hold=2.0)
        search = page.get_by_placeholder("Search linen shirts, beige chinos…").locator("visible=true").first
        search.click()
        search.press_sequentially("cosy winter layer", delay=45)
        search.press("Enter")
        page.wait_for_load_state("networkidle")
        caption(page, "Hybrid search understands intent, not just keywords",
                "Postgres full-text + CLIP text & image vectors, fused with reciprocal rank fusion", hold=4.0)
        scroll(page, 350)
        page.wait_for_timeout(1500)

        # 3. Outfit in chat
        mark("outfit")
        new_chat(page)
        caption(page, "Ask Gabriella for a complete look, with a budget and sizes")
        ask(page, "Casual dinner outfit for men under ₹6,000, I wear M and UK 9", read=1.0)
        caption(page, "Every piece is a real product, in stock in M / UK 9 at Pune, and the total fits the budget",
                "A server-side validator rejects anything the model didn't retrieve or that isn't on the shelf", hold=5.0)
        scroll(page, 300)
        page.wait_for_timeout(2000)
        mark("outfit-end")

        # 4. Refine
        caption(page, "Refine it in conversation: the occasion and sizes are remembered")
        ask(page, "Make it smarter, I can go up to ₹8,000", read=1.0)
        caption(page, "Restyled a step smarter within the new budget, still in M / UK 9", hold=4.5)

        # 5. Honest failure
        caption(page, "When something isn't possible, she says so, with real numbers")
        ask(page, "Formal outfit for men under ₹2,000", read=1.0)
        caption(page, "No invented bargains: she quotes the cheapest complete look the store actually has", hold=4.5)

        # 6. Photo of your own garment
        mark("photo")
        item = page.request.get(f"{BASE}/api/search?q=navy+casual+shirt+men&page_size=1").json()["items"][0]
        photo = page.request.get(BASE + item["image"]["url"]).body()
        new_chat(page)
        caption(page, "Upload a photo of something you already own")
        page.locator("input[type=file]").set_input_files(
            files=[{"name": "my-shirt.webp", "mimeType": "image/webp", "buffer": photo}]
        )
        page.get_by_text("Looks like a").first.wait_for(timeout=60_000)
        caption(page, "CLIP recognises the garment and its colour, and shows how sure it is", hold=3.5)
        ask(page, "What trousers and shoes go with this? Menswear, size M and UK 9", read=1.0)
        caption(page, "The outfit is built around your shirt: trousers, shoes and a finishing touch, no second top",
                hold=5.0)
        mark("photo-end")

        # 7. Personalisation
        page.request.post(f"{BASE}/api/auth/login", data={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
        new_chat(page)
        caption(page, "Signed in as a returning shopper with four past orders", hold=2.5)
        ask(page, "Suggest something new based on what I bought before", read=1.0)
        caption(page, "Picks from their favourite colours, sizes and price range",
                "Only a compact style summary is used, it never re-suggests what they own, and it can be switched off",
                hold=5.5)

        # 8. Buy the look
        caption(page, "Like a look? Buy the whole outfit in one click")
        ask(page, "Office outfit please", read=2.0)
        add = page.get_by_role("button", name="Add look").first
        add.scroll_into_view_if_needed()
        page.wait_for_timeout(600)
        add.click()
        page.wait_for_timeout(1500)
        page.goto(f"{BASE}/bag")
        page.wait_for_load_state("networkidle")
        caption(page, "The bag re-checks live stock for every line", hold=3.0)
        page.get_by_role("button", name="Place order (simulated)").click()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1500)
        caption(page, "Checkout locks the stock rows and decrements them in one transaction",
                "So two shoppers can never buy the last unit", hold=4.5)
        caption(page, None)

        # 9. End card
        card(page, "Gabriella", [
            "26 scripted conversations · 100% of shown items grounded and in stock",
            "Free to run: open-weight LLM on Groq or Ollama, CLIP on CPU, rule-based fallback",
            "github.com/Kunal-Wagh282/Gabriella",
        ], 5.0, keep=True)

        video = page.video
        ctx.close()
        browser.close()
        return Path(video.path()), marks


def encode(raw: Path, marks: list[tuple[str, float]]) -> None:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    mp4 = OUT / "gabriella-demo.mp4"
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(raw), "-c:v", "libx264", "-preset", "slow",
                    "-crf", "24", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(mp4)], check=True)
    # README loop: the outfit answer, sped up slightly, 900 px wide.
    at = dict(marks)
    start, end = at["outfit"] + 0.5, at["outfit-end"]
    gif = OUT / "gabriella-demo.gif"
    filters = ("setpts=0.8*PTS,fps=10,scale=900:-1:flags=lanczos,split[a][b];"
               "[a]palettegen=max_colors=96[p];[b][p]paletteuse=dither=bayer:bayer_scale=4")
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-ss", f"{start:.2f}", "-to", f"{end:.2f}", "-i", str(raw),
                    "-filter_complex", filters, str(gif)], check=True)
    for f in (mp4, gif):
        print(f"{f.relative_to(ROOT)}  {f.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    raw, marks = record()
    print("scenes:", ", ".join(f"{n}@{s:.0f}s" for n, s in marks))
    encode(raw, marks)
    if "--keep-raw" not in sys.argv:
        shutil.rmtree(RAW, ignore_errors=True)
