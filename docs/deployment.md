# Deploying Gabriella

Gabriella is five services: Postgres with pgvector, Redis, the FastAPI API, the arq worker, and the Next.js web app. Docker Compose already runs all five, so the easiest public deployment is the same compose file on one server.

## Before any public deployment

1. **Rotate your Groq key** if it has ever been pasted into a chat, an issue or a commit. Create a new key at [console.groq.com/keys](https://console.groq.com/keys) and put it only in the server's `.env`.
2. **Set production settings** in the server's `.env`:

   ```dotenv
   GABRIELLA_ENV=prod              # the API refuses to start with a default JWT secret
   JWT_SECRET=<64+ random characters>
   COOKIE_SECURE=true              # cookies only over HTTPS
   POSTGRES_PASSWORD=<random>
   DATABASE_URL=postgresql+asyncpg://gabriella:<same password>@db:5432/gabriella
   SEED_DEMO_PASSWORD=<what you'll put on your CV or portfolio>
   SEED_ADMIN_PASSWORD=<random, keep private>
   LOG_LEVEL=INFO
   ```

   Generate secrets with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
3. **Know your model budget.** On Groq's free tier, `openai/gpt-oss-120b` allows 8,000 tokens a minute and 200,000 a day, so roughly 80–100 chat turns a day at about 2,000 tokens each. Limits are per model: if you expect more traffic, switch `GROQ_MODEL` to a model with a larger allowance. Check yours at [console.groq.com/settings/limits](https://console.groq.com/settings/limits). When the limit is hit, she switches to the rule-based stylist instead of failing, so the demo keeps working. Rate-limiting the chat endpoint per IP is still worth adding before sharing a link widely (see [Hardening](#hardening)).

## Option A (recommended): one small VM with Docker Compose

Best for a portfolio. It is the same stack you run locally, it has no cold starts, and everything stays on one bill (or none).

**Size:** 2 vCPU and 4 GB RAM is comfortable. The CLIP models use about 1 GB of RAM in the API container. Disk: about 6 GB for the images, models and database.

**Hosts that fit:** Oracle Cloud's Always Free ARM VM (free; the images build on ARM, but the first build is slow), a Hetzner CX22 (about €4/month), a DigitalOcean or Lightsail 4 GB droplet, or a GCP e2-medium on credits.

**1. Install Docker and get the code.**

```bash
curl -fsSL https://get.docker.com | sh
git clone https://github.com/<you>/gabriella.git && cd gabriella
cp .env.example .env && nano .env      # production settings from above + GROQ_API_KEY
```

**2. Add HTTPS with Caddy.** Point a domain (or a free subdomain from DuckDNS) at the VM. Create a `docker-compose.override.yml` on the server so Caddy terminates TLS and the app ports stop being public:

```yaml
services:
  caddy:
    image: caddy:2
    ports: ["80:80", "443:443"]
    command: caddy reverse-proxy --from gabriella.example.com --to web:3000
    volumes: [caddy-data:/data]
    depends_on: [web]
  db:    { ports: !reset [] }
  redis: { ports: !reset [] }
  api:   { ports: !reset [] }
  web:   { ports: !reset [] }
volumes:
  caddy-data:
```

Only the web app needs to be reachable, because it proxies `/api` and `/media` to the API inside the Docker network. Cookies stay first-party, so no CORS setup is needed.

**3. Start it.**

```bash
docker compose up -d --build
docker compose logs -f api        # first boot: migrate, seed, render images (1–2 min)
```

Then open `https://gabriella.example.com`, sign in with the demo account, and check that the chat header says "Powered by openai/gpt-oss-120b on Groq".

**4. Updates:** `git pull && docker compose up -d --build`. Migrations run on start-up.

**Backups (optional for a demo):** `docker compose exec db pg_dump -U gabriella gabriella | gzip > backup.sql.gz`. The catalogue can always be regenerated with `python -m seed --reset`.

## Option B: managed services, split up

Use this if you'd rather not run a server. Each piece goes on a free or cheap tier:

| Piece | Suggested host | Notes |
| --- | --- | --- |
| Web (Next.js) | Vercel | Set `API_INTERNAL_URL=https://<your-api-host>` at build and run time. The rewrites keep `/api` and cookies first-party. |
| API + worker | Render, Railway, Fly.io or Koyeb (Docker) | Build `backend/Dockerfile`. Run the worker as a second service with the command `arq app.workers.worker.WorkerSettings`. **Needs ≥ 1 GB RAM** for CLIP; 512 MB free tiers run out of memory. |
| Postgres + pgvector | Neon or Supabase | Both support `CREATE EXTENSION vector`. Use the **direct (non-pooled)** connection string as a `postgresql+asyncpg://…` URL; asyncpg's prepared statements don't work through a transaction pooler. |
| Redis | Upstash | Use the `rediss://` URL as `REDIS_URL`. |
| Media | A persistent disk on the API host, or object storage | Product images are rendered at seed time and uploads go to `MEDIA_ROOT`. Ephemeral filesystems lose them on redeploy (re-seeding recreates the catalogue images). |

Option B has more moving parts, and free API tiers sleep, so the first request after idling can take 30 s or more while CLIP loads. For a recruiter clicking a link, Option A gives the better first impression.

## Option C: no server, local demo plus a recording

If you don't want to host anything, run `docker compose up -d` locally and follow [demo-script.md](demo-script.md) to record a 2-minute screen capture. Put it at the top of the README. Many reviewers only watch the video anyway.

## Hardening

These matter only for a public link:

- **Rate-limit chat and uploads per IP**, for example 20 turns per 10 minutes, so one visitor can't use up the day's Groq quota. Redis is already in the stack, so a fixed-window counter is about 20 lines of FastAPI dependency.
- Keep `/api/admin/*` and `/metrics` private: firewall the metrics port or put basic auth on it at the proxy.
- Turn off public sign-up if you only want the demo account (remove the link in the UI and gate `POST /api/auth/register`).
- Uploaded photos are already stripped of EXIF data and deleted after 24 hours by the worker.
