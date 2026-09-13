# TrendScout AI

Conversational market intelligence over the AI startup ecosystem.
CSE 573 - Semantic Web Mining.

Ask a question in plain English and get an answer that cites the documents
it came from:

> **Q:** *What open source frameworks for building RAG applications are there?*
>
> - **cognita** - a RAG framework for building modular, production-grade applications `[2]`
> - **canopy** - a RAG framework and context engine powered by Pinecone `[3]`
> - **fastRAG** - an efficient Retrieval-Augmentation-and-Generation framework `[4]`

Every claim carries a `[n]` pointing at a real indexed document. When the
corpus does not contain the answer, the system says so rather than
inventing one.

## How it works

```
                    +--------------------------------------+
   question ------->|  1. PLAN    the LLM turns the        |
                    |             question into a plan:    |
                    |             query, type, location,   |
                    |             time window (since_days) |
                    +------------------+-------------------+
                                       v
   +---------------------------------------------------------------+
   |  2. RETRIEVE   three channels, fused by Reciprocal Rank Fusion |
   +---------------------------------------------------------------+
   |                                                               |
   |   Okapi BM25          E5-base-v2 + FAISS       Graph          |
   |   exact terms,        meaning, paraphrase      shared-entity  |
   |   names, acronyms     ("music AI" ->           neighbours     |
   |                        "audio generation")                    |
   |        |                     |                      |         |
   |        +---------------------+----------------------+         |
   |                              v                                |
   |              score(d) = sum  weight_c / (60 + rank_c(d))      |
   +------------------------------+--------------------------------+
                                  v
                    +--------------------------------------+
                    |  3. GENERATE  the LLM answers using  |
                    |               ONLY those documents,  |
                    |               citing each as [n]     |
                    +--------------------------------------+
```

Retrieval is fully deterministic - no model output influences ranking - so
it stays reproducible and measurable. The LLM only shapes the query going
in and the prose coming out.

### Time

Every document carries `event_at` (when the thing happened — a launch
date, a publish date, a repo's creation date), and the planner sees
today's date, so "this week" becomes `since_days: 7` and a filter on
`event_at`. When nothing matches, constraints relax in a fixed order —
drop the location, widen the window ×4, and only then drop the date — and
every step is recorded in `plan.relaxations`. The answer model is told
what window was actually searched, so "nothing in the last 7 days" never
silently turns into an answer about last year.

### Why fuse by rank instead of score

BM25 scores are unbounded, cosine similarities live in `[-1, 1]`, and graph
scores are log weights. Those numbers are not comparable, and normalising
them needs constants that break whenever the corpus changes. Ranks are
always comparable. `k = 60` is the constant from Cormack et al. (2009); it
damps the top of any single list so one over-confident channel cannot
dominate the fusion.

## Results

Measured on 22 labelled queries with 65 graded relevance judgements
(`data/eval/queries.json`), written by reading the corpus rather than by
inspecting system output.

```
python scripts/evaluate_retrieval.py
```

| Configuration      | P@10  | R@10  |  MRR  | nDCG@10 |
| ------------------ | ----- | ----- | ----- | ------- |
| BM25 only          | 0.214 | 0.762 | 0.816 |  0.743  |
| Dense only         | 0.245 | 0.877 | 0.977 |  0.882  |
| **BM25 + Dense**   | 0.245 | 0.880 | 0.938 | **0.881** |
| + Graph (naive)    | 0.245 | 0.883 | 0.794 |  0.794  |
| + Graph (recall)   | 0.245 | 0.880 | 0.938 |  0.881  |

By query type:

| Configuration    | lexical | semantic |
| ---------------- | ------- | -------- |
| BM25 only        |  0.886  |  0.690   |
| Dense only       |  0.886  |  0.881   |
| **BM25 + Dense** |  0.917  |  0.867   |

What this shows:

- **Dense retrieval carries the system.** Adding it to BM25 is worth
  **+18.5% nDCG**. On semantic queries alone, BM25 manages 0.690 against
  dense's 0.881.
- **BM25 earns its place on lexical queries, not overall.** The hybrid ties
  dense-only overall (0.881 vs 0.882) but is clearly better when the query
  is a name or exact term (0.917 vs 0.886) - which is what a user typing
  "Suno" is doing. Weighting BM25 equally with dense is worse than either
  (0.863), because lexical noise drags semantic queries down. The default
  weight of 0.5 was chosen by sweeping it (`--sweep`); anything in
  0.25-0.75 performs identically within the noise of a 22-query set.
- **The graph channel is neutral here, and naive fusion is harmful.**
  Letting it re-score documents the text channels already found costs
  **-9.9% nDCG**: a document ranked weakly by *both* BM25 and dense picks
  up a third contribution and overtakes documents ranked strongly by one.
  In one case `YiVal` (BM25 #10, dense #15) was promoted to #1 above two
  genuinely relevant results purely for sharing an entity with a seed.
  Restricting the channel to documents the text channels missed removes the
  harm and adds exactly 0.000, because at k=10 the text channels already
  fill every slot. It is kept for recall on narrow queries and for the
  connections it surfaces in the UI, not because it improves this
  benchmark.

Differences under ~0.01 on 22 queries are noise.

## Weekly digest

```bash
python scripts/generate_digest.py                  # current ISO week
python scripts/generate_digest.py --week previous  # what the Monday job runs
```

One document per ISO week in `digests`, in three sections — Launches,
Funding, Open source & models — written only from that week's documents.
Selection and ordering are deterministic (launches by points, funding
newest first, repos by stars, models by trending score, papers by
upvotes) and citation numbers are assigned *before* the model sees
anything; each section is generated with only its own numbered sources,
and any `[n]` the model invents is stripped and counted. A digest stores
the hash of its inputs, so re-running the script for an unchanged week
makes no model call. Served at `/digests`, `/digests/latest`,
`/digests/{week}` and on the site's home page.

## Companies and funding

Funding rounds are pulled out of funding news by a regex prefilter on the
title, one Groq JSON call per article, schema validation, and a
**rule-derived confidence**: `high` only when the company name and the
amount both appear verbatim in the text the model saw, `medium` when the
company does but the amount is absent or paraphrased, `low` otherwise.
Rounds covered by several outlets are merged when company, round name,
amount (±10%) and date (±14 days) agree, keeping every source article.
Each article is processed once per version of its text.

Measured on 41 hand-labelled articles (`data/eval/funding_labels.json`,
`python scripts/evaluate_extraction.py`): is-a-round precision 1.000 /
recall 0.931, company 27/27, amount 26/27 within 5%, round 10/10.

Companies are resolved strictly and recomputed on every run: YC slug,
then registered domain, then normalised name — and the name only when
exactly one company has it. No fuzzy matching. "Which startups raised
the most this month?" takes a structured path: the planner emits
`intent: funding_ranking`, the rounds are sorted by amount in the
database, and the model only writes the prose.

`GET /funding` (largest first), `GET /companies`, `GET /companies/{slug}`.

## Trends

Topics are counted per ISO week from the tags each source already
carries (GitHub topics, Hugging Face tags and paper keywords, YC tags,
article categories), normalised to one spelling. A topic is *rising* when
this week's count beats the mean of the four weeks before it:
`score = (count − baseline) / sqrt(baseline + 1)`, with a minimum of 3
mentions. Weeks with fewer than four prior weeks of data are flagged
`insufficient_history` rather than dressed up as trends. Velocity —
stars, likes, upvotes gained over a window — comes from the daily
`metric_snapshots`, and needs two snapshots on different days to say
anything; history starts the day the pipeline first runs and cannot be
backfilled.

`GET /trends?week=`, `GET /trends/velocity?type=repo&days=7`;
`python scripts/compute_trends.py`.

## Website

`web/` is a Next.js app (App Router, TypeScript, Tailwind): the week's
digest on the home page, ask, search, funding, companies, trends, digests
and an about page with the methodology and the evaluation table. Pages
are server-rendered against the API with a 10-minute cache, so a sleeping
backend still serves the last good page; chat and search go through the
site's own `/api/*` route handlers, so the browser never sees the backend
and CORS never enters the picture. `npm run gen:api` regenerates
`src/lib/openapi.d.ts` from the running API's `/openapi.json`.

```bash
cd web && cp .env.example .env.local     # API_URL=http://localhost:8000
npm install && npm run dev               # http://localhost:3000
npm run lint && npm run typecheck && npm run build
```

## Deployment

See `DEPLOY.md`: MongoDB Atlas (M0) + a Hugging Face Docker Space for the
API + GitHub Actions for the daily/weekly pipeline + Vercel for the site,
all on free tiers. The API rebuilds its indexes from the vectors stored in
MongoDB at boot, so the container carries no data.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_trf

cp .env.example .env        # then fill in GROQ_API_KEY and MongoDB/Neo4j

python scripts/ingest.py               # fetch every source into MongoDB
python scripts/run_pipeline.py         # NER, embeddings, indexes, snapshots (incremental)
python scripts/setup_neo4j_schema.py   # optional; the pipeline syncs Neo4j when it is up

python src/api/main.py                 # API -> localhost:8000/docs
cd web && npm install && npm run dev  # site -> localhost:3000 (API_URL in web/.env.local)
streamlit run tools/streamlit_app.py   # internal debug UI -> localhost:8501
```

MongoDB must be running (`brew services start mongodb-community`). Neo4j is
optional: if it is unreachable the graph endpoints return 503 and everything
else works, because graph-expansion retrieval reads the same entity links
from MongoDB.

All configuration is read from `.env` through `src/config.py`; any value can
be overridden per process (`MONGODB_DB=... INDEX_DIR=... python ...`).

### Ingestion

```bash
python scripts/ingest.py --list                        # configured sources
python scripts/ingest.py                               # all sources, default windows
python scripts/ingest.py --source techcrunch_ai --days 56 --max-pages 30   # backfill
python scripts/ingest.py --dry-run                     # fetch + normalise, write nothing
```

### Processing and scheduling

```bash
python scripts/run_pipeline.py                        # everything that changed
python scripts/run_pipeline.py --stages embed,index   # some stages
python scripts/run_pipeline.py --force                # redo every document
scripts/update.sh daily                               # ingest due sources + pipeline + API reload
scripts/install_schedule.sh                           # launchd: daily 07:30, weekly Mon 08:00
```

The pipeline is incremental. Each document's `content_hash` is the sha1 of
exactly the text that gets indexed; entities and embeddings record the
hash they were computed from, and each stage redoes only rows whose hash
moved. A daily run with 50 new articles extracts and embeds 50 documents,
then rebuilds FAISS and BM25 from stored vectors in well under a second.
Star counts are kept out of the indexed text on purpose, so a weekly star
tick does not force a re-embed; their history goes to `metric_snapshots`
instead, one row per document per day.

A running API picks up new indexes without a restart:
`POST /admin/reload` with `Authorization: Bearer $ADMIN_TOKEN`. `GET /meta`
reports what is indexed, when it was built, and what every source last
did.

Every source is a class with two methods: `fetch(since)` talks to the
network, `normalize(raw)` is pure and is unit-tested on saved fixtures with
sockets disabled. The runner adds identity (`doc_key`), `event_at` and
`content_hash`, then upserts: a document seen before with the same text is
`unchanged`, with different text is `changed`, otherwise `new`. Re-running
a source over the same window therefore reports `new=0 changed=0`. Each
source runs in isolation and writes one row to the `runs` collection
(counts, duration, status, error), so one broken feed never blocks the
others.

| Source | Type | Schedule | What |
| --- | --- | --- | --- |
| `yc_oss` | startup | weekly | Y Combinator directory via the yc-oss JSON mirror; AI-tagged companies from 2023+ batches |
| `startupsavant` | startup | monthly | StartupSavant's yearly "startups to watch" list (headless browser; local only) |
| `yc_launches` | launch | weekly | Y Combinator Launches, AI-ish only |
| `hn_launches` | launch | daily | Hacker News: Show HN with ≥10 points and an AI title, and every Launch HN |
| `techcrunch_ai` | article | daily | TechCrunch AI category feed, paged |
| `crunchbase_news` | article | daily | Crunchbase News feed (funding rounds) |
| `eu_startups` | article | daily | EU-Startups feed (European rounds) |
| `google_news` | article | daily | Google News search for AI startup funding; stories already held from their original outlet are skipped by title |
| `github_new` | repo | weekly | Repositories created in the window for `llm`, `generative-ai`, `ai-agents`, `rag`; top 60 by stars, awesome-lists skipped |
| `hf_models` | model | weekly | Hugging Face trending models (top 50) |
| `hf_papers` | paper | daily | Hugging Face daily papers, with the GitHub repo each links to |

### Reproducing the evaluation

The corpus the numbers above were measured on is committed as
`data/eval/corpus_v2.jsonl` (857 records, no embeddings). Load it into its
own database and index directory, then evaluate:

```bash
MONGODB_DB=trendscout_eval INDEX_DIR=data/eval_index \
    python scripts/load_eval_corpus.py --build-indexes
MONGODB_DB=trendscout_eval INDEX_DIR=data/eval_index \
    python scripts/evaluate_retrieval.py
```

This reproduces the table exactly, and keeps working as the live corpus
grows, because the evaluation never reads the live database.

## API

| Method | Endpoint                  | Purpose                                   |
| ------ | ------------------------- | ----------------------------------------- |
| `POST` | `/chat`                   | Question in, cited answer out             |
| `POST` | `/search`                 | Hybrid search; typed filters (`type`, `location`, `source`, `since_days`) |
| `GET`  | `/documents`              | Newest documents, filter by type/source/window |
| `GET`  | `/documents/{id}`         | One document with its entities              |
| `GET`  | `/digests`, `/digests/latest`, `/digests/{week}` | Weekly digests          |
| `GET`  | `/funding`                | Extracted funding rounds, largest first   |
| `GET`  | `/trends`, `/trends/velocity` | Rising topics; stars/likes gained     |
| `GET`  | `/companies`, `/companies/{slug}` | Resolved companies with linked documents and rounds |
| `POST` | `/similar`                | "More like this" by embedding             |
| `POST` | `/graph/query`            | Read-only Cypher (bearer `ADMIN_TOKEN`)   |
| `GET`  | `/graph/entities`         | Most-mentioned entities                   |
| `GET`  | `/graph/startup/{name}`   | One startup's entity neighbourhood        |
| `GET`  | `/stats`                  | Corpus and index counts                   |
| `GET`  | `/health`                 | Liveness, document and vector counts      |
| `GET`  | `/meta`                   | Freshness per source, index build time    |
| `POST` | `/admin/reload`           | Re-read indexes (bearer `ADMIN_TOKEN`)    |

```bash
curl -X POST localhost:8000/chat -H 'Content-Type: application/json' \
  -d '{"question": "Which AI startups in San Francisco raised funding?"}'
```

Search results carry the per-channel ranks that produced them
(`"ranks": {"keyword": 1, "semantic": 3}`), so the ordering is explainable.

Requests are validated and capped (question length, `top_k`, history
turns; unknown fields are rejected), `/chat` is rate-limited per client
IP (`CHAT_RATE_LIMIT_PER_MINUTE`), and CORS origins come from
`CORS_ORIGINS`.

## Corpus

Every document lives in one MongoDB collection, `documents`, tagged with a
`type`. The registry in `src/corpus/types.py` is the only place that knows
which types exist; adding one means adding an entry there plus a rendering
branch in `document_text.py`.

| `type`    | What                                              |
| --------- | ------------------------------------------------- |
| `startup` | a company (Y Combinator, StartupSavant)           |
| `article` | a news story (TechCrunch, Crunchbase News, EU-Startups, Google News) |
| `repo`    | a GitHub repository                               |
| `launch`  | a product launch (YC Launches, Show HN, Launch HN) |
| `model`   | a trending Hugging Face model                     |
| `paper`   | a Hugging Face daily paper                        |

`GET /meta` reports live counts per type. The evaluation numbers above
were measured on the frozen 210-document snapshot, not the live corpus.

Each document carries a stable `doc_key` (unique index — re-ingesting the
same thing updates rather than duplicates), `event_at` (when the thing
happened, a real datetime, or null when the source gives none), `first_seen_at`
/ `last_seen_at`, and `content_hash` over exactly the text that gets indexed.


## Layout

```
src/
  corpus/
    types.py              document type registry (the only list of types)
    identity.py           doc_key, canonical URLs, content_hash
    dates.py              event_at / first_seen_at parsing
  sources/
    base.py               Source: fetch(since) + normalize(raw)
    rss.py                generic RSS/Atom source (one class, many feeds)
    yc_oss.py, yc_launches.py, hn.py, github.py, huggingface.py,
    google_news.py, startupsavant.py
    registry.py           every configured source
  ingest/
    store.py              upsert by doc_key: new / changed / unchanged
    runner.py             run sources in isolation, log to `runs`
  pipeline/
    run.py                stages: refresh, entities, embed, index, snapshots, neo4j
    hashes.py             content_hash upkeep; adopts pre-marker rows
    entities.py           NER for stale docs; atomic canonical_entities swap
    embed.py, index.py    E5 for stale docs; FAISS + BM25 from stored vectors
    snapshots.py          daily star/fork history per repo
  graph/neo4j_import.py   MongoDB -> Neo4j merge (used by the pipeline)
  entities/resolve.py     companies from documents + rounds (slug > domain > unique name)
  extraction/funding.py   funding rounds: prefilter -> LLM JSON -> validate -> confidence -> dedupe
  trends/
    topics.py             topic vocabulary from source tags
    compute.py            weekly counts, rising score, velocity from snapshots
  digest/
    weeks.py              ISO week arithmetic
    select.py             the week's documents, grouped and ordered
    generate.py           numbered sources -> per-section LLM calls -> validated markdown
  search/
    hybrid_search.py      three-channel retrieval + RRF
    bm25_index.py         Okapi BM25 over the corpus
    graph_expansion.py    shared-entity neighbour retrieval
    document_text.py      canonical doc -> text, used by every channel
  rag/pipeline.py         plan -> retrieve -> grounded answer
  embeddings/             E5-base-v2, prefix-aware
  extractors/             spaCy NER
  database/               MongoDB + Neo4j clients
  llm/groq_client.py      Groq wrapper with model resolution
  api/main.py             FastAPI
  config.py               all settings, from .env / environment
scripts/
  ingest.py               fetch sources into MongoDB
  run_pipeline.py         process what changed
  generate_digest.py      write the week's digest (no-op if inputs unchanged)
  evaluate_extraction.py  funding extraction vs hand labels
  compute_trends.py       recount weekly topics, print what is rising
  update.sh               ingest + pipeline + API reload (what launchd runs)
  install_schedule.sh     install the launchd jobs
  build_indexes.py        alias: run_pipeline.py --stages refresh,embed,index
  migrate_to_documents.py one-time move from per-type collections (done)
  extract_entities.py     alias: run_pipeline.py --stages refresh,entities
  evaluate_retrieval.py   metrics, ablations, weight sweep
  export_eval_corpus.py   freeze the corpus as a snapshot
  load_eval_corpus.py     load a snapshot into a separate database
  import_to_neo4j.py      push the graph to Neo4j
data/eval/queries.json    labelled evaluation set
data/eval/corpus_v2.jsonl frozen corpus the numbers were measured on
tests/
```

## Tests

```bash
pytest tests/ -q
```

Unit tests (tokenisation, fusion arithmetic, document rendering, RAG
plumbing, configuration, the evaluation snapshot) run with no database and
no network. Tests marked `needs_mongo` / `needs_indexes` skip rather than
fail when MongoDB or the indexes are missing; `pytest -m "not needs_mongo"`
runs only the offline ones.

## Stack

Python 3.13, MongoDB, Neo4j, FAISS, rank-bm25, intfloat/e5-base-v2, spaCy (en_core_web_trf),
Groq, FastAPI, Next.js (App Router, TypeScript, Tailwind), pytest. Streamlit
remains as an internal debug view in `tools/`.
