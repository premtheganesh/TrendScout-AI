# Deploying TrendScout AI

**Status (2026-09-13):** the data pipeline is deployed — MongoDB Atlas holds
the corpus and the GitHub Actions weekly job refreshes it. The API and the
site are run locally on demand. The hosting steps below are written and
tested as far as a container build, but not carried out: Hugging Face
Docker Spaces became paid, and every host with the 2 GB the API needs
(Modal, Google Cloud Run, Oracle) asks for a payment card. If you host it
later, Modal is the least work — its free credit resets monthly and this
API uses a small fraction of it.

# The full setup, for when you want it

Four pieces, all free: MongoDB Atlas holds the data, GitHub Actions runs the
pipeline on a schedule, a Hugging Face Space serves the API, Vercel serves
the site. The steps below are exact; the only things you supply are
accounts and the secrets they issue.

```
 GitHub Actions (cron) ──ingest + process──▶ MongoDB Atlas (M0, 512 MB)
        │                                         ▲
        └── POST /admin/reload ──▶ HF Space (Docker, API on :7860) ──reads──┘
                                        ▲
                             Vercel (Next.js, web/) ── server-side fetch + /api/* proxy
```

## 0. What is already true

- The API rebuilds FAISS and BM25 **in memory from the vectors stored in
  MongoDB at boot** (`INDEX_BUILD_ON_BOOT=true`, set in the `Dockerfile`),
  so the container needs no data files and survives an ephemeral disk.
  ~3,900 documents: about 1 s. Cold start is dominated by loading the
  440 MB embedding model, which is baked into the image.
- Vectors are float32 binary (3 KB each). The whole corpus with entities,
  rounds, digests and snapshots is well under 100 MB — inside Atlas M0.
- Everything reads configuration from environment variables
  (`src/config.py`); nothing is hardcoded.

## 1. MongoDB Atlas

1. Create a free **M0** cluster at cloud.mongodb.com.
2. Database Access → add two users: `pipeline` (readWrite on `trendscout_ai`)
   and `api` (read on `trendscout_ai`).
3. Network Access → allow `0.0.0.0/0` (GitHub Actions and Spaces have no
   fixed IPs).
4. Copy the corpus from your machine:
   ```bash
   python scripts/copy_database.py --to "mongodb+srv://pipeline:<pw>@<cluster>.mongodb.net/" --drop
   ```
   That copies `documents`, `canonical_entities`, `funding_rounds`,
   `companies`, `digests`, `metric_snapshots`, `topic_weekly`, `runs` and
   recreates the indexes.

## 2. Hugging Face Space (the API)

1. huggingface.co → New Space → **Docker** SDK, free CPU basic (2 vCPU, 16 GB).
2. The Space reads its settings (`sdk: docker`, `app_port`) from the
   front-matter of the `README.md` it receives, and the repository's own
   README has none. Push a dedicated branch whose README is the Space card:
   ```bash
   git remote add space https://huggingface.co/spaces/<you>/trendscout-api
   git checkout -b space
   cp deploy/huggingface/README.md README.md
   git commit -am "Space card"
   git push space space:main
   git checkout main
   ```
   Re-run the same four commands (checkout, cp, commit, push) after each
   change you want deployed — or set the Space to build from GitHub in its
   settings, which then only needs the front-matter merged into `README.md`.
3. Settings → Variables and secrets:

   | Secret | Value |
   |---|---|
   | `MONGODB_URI` | the `api` user's connection string |
   | `MONGODB_DB` | `trendscout_ai` |
   | `GROQ_API_KEY` | from console.groq.com |
   | `ADMIN_TOKEN` | `python -c 'import secrets; print(secrets.token_urlsafe(32))'` |
   | `CORS_ORIGINS` | your Vercel URL once you have it (the site proxies, so this can stay strict) |
   | `CHAT_RATE_LIMIT_PER_MINUTE` | `10` |

4. When the build finishes, `https://<you>-trendscout-api.hf.space/health`
   must return `{"status":"ok","documents":…,"vectors":…}`.

   The free tier sleeps after 48 h without traffic; the first request
   after that takes about a minute (index build; the model is in the
   image). With a weekly schedule it will sleep between runs; the first
   visitor of the week wakes it.

## 3. GitHub Actions (the pipeline)

Repository → Settings → Secrets and variables → Actions:

| Secret | Value |
|---|---|
| `MONGODB_URI` | the `pipeline` user's connection string |
| `GROQ_API_KEY` | same Groq key |
| `ADMIN_TOKEN` | same token as the Space |
| `API_URL` | `https://<you>-trendscout-api.hf.space` |

`GITHUB_TOKEN` is provided automatically and is enough for the GitHub
search API. Workflows:

- `.github/workflows/weekly.yml` — Monday 08:00 UTC: every source → pipeline → last week's digest → reload
- `.github/workflows/tests.yml` — offline tests + web lint/typecheck on every push

Run either manually first (Actions → workflow → Run workflow) and read
the log. Note: GitHub disables scheduled workflows after **60 days without
a commit**; any push re-enables them.

## 4. Vercel (the site)

1. vercel.com → Add New Project → import the GitHub repo → **Root
   Directory: `web`** (framework is detected as Next.js).
2. Environment variable: `API_URL = https://<you>-trendscout-api.hf.space`
   (server-side only; the browser talks to the site's own `/api/*` routes).
3. Deploy. Pages are rendered per request and every API call is cached
   for 10 minutes in Next's data cache, which keeps the last good data when
   a refresh fails — so a sleeping backend still serves pages anyone has
   seen in the last cache window.
4. Put the Vercel URL into the Space's `CORS_ORIGINS`.

## 5. After the first deploy

```bash
curl https://<api>/meta          # counts, index build time, last run per source
curl https://<api>/digests/latest | head -c 400
```

Then open the site and ask "Which AI startups launched this week?".

## Local equivalents

| Cloud | Local |
|---|---|
| Atlas | `brew services start mongodb-community` |
| GitHub Actions cron | `scripts/install_schedule.sh` (launchd, Monday 08:00) |
| HF Space | `python src/api/main.py` |
| Vercel | `cd web && npm run dev` |

## Costs and limits to know

- Groq free tier: ~8,000 tokens/minute **and 200,000 tokens/day**. The
  digest and funding extraction back off on the per-minute limit; the weekly
  run caps extraction at 150 articles; a first full-corpus run can take
  more than one day.
- Atlas M0: 512 MB, shared CPU. Fine for tens of thousands of documents.
- Spaces free CPU: 16 GB RAM, sleeps after 48 h idle.
- Vercel Hobby: plenty for a project site.
