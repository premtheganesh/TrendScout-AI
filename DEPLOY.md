# Deploying TrendScout AI (free tier)

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
2. Add the Space as a git remote and push the repository (the `Dockerfile`
   is at the root; `deploy/huggingface/README.md` is the Space card — copy
   it to the Space's `README.md`):
   ```bash
   git remote add space https://huggingface.co/spaces/<you>/trendscout-api
   git push space main
   ```
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
   after that takes ~1–2 minutes (model load + index build). The daily
   pipeline's `/admin/reload` call keeps it awake on weekdays.

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

- `.github/workflows/daily.yml` — 07:30 UTC: daily sources → pipeline → reload
- `.github/workflows/weekly.yml` — Monday 08:00 UTC: weekly sources → pipeline → last week's digest → reload
- `.github/workflows/tests.yml` — offline tests + web lint/typecheck on every push

Run either manually first (Actions → workflow → Run workflow) and read
the log. Note: GitHub disables scheduled workflows after **60 days without
a commit**; any push re-enables them.

## 4. Vercel (the site)

1. vercel.com → Add New Project → import the GitHub repo → **Root
   Directory: `web`** (framework is detected as Next.js).
2. Environment variable: `API_URL = https://<you>-trendscout-api.hf.space`
   (server-side only; the browser talks to the site's own `/api/*` routes).
3. Deploy. Pages are server-rendered with a 10-minute cache
   (`revalidate = 600`), so a sleeping backend still serves the last
   good page.
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
| GitHub Actions cron | `scripts/install_schedule.sh` (launchd) |
| HF Space | `python src/api/main.py` |
| Vercel | `cd web && npm run dev` |

## Costs and limits to know

- Groq free tier: ~8,000 tokens/minute. The digest and funding extraction
  back off automatically; a weekly run takes a few minutes longer than it
  would with a paid key.
- Atlas M0: 512 MB, shared CPU. Fine for tens of thousands of documents.
- Spaces free CPU: 16 GB RAM, sleeps after 48 h idle.
- Vercel Hobby: plenty for a project site.
