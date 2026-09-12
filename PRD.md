# TrendScout AI — Product Requirements

Living document. Updated at the end of every phase with what was built,
what changed from the plan, and the measured numbers.

Last updated: 2026-09-12 (Phase 1)

---

## 1. Problem

TrendScout AI answers questions about the AI startup ecosystem with cited
answers over a corpus of startups, news and open-source repositories. It
works, but it is a snapshot: every document was scraped once on 2025-11-13.
It cannot say what launched this week, who raised money last month, or
which projects are gaining momentum, and re-running the scrapers would
duplicate the corpus rather than refresh it.

## 2. Goal

A live system that refreshes itself on a schedule, knows *when* things
happened, and answers three questions the snapshot cannot:

1. **What is new this week?** — launches, funding, notable open source.
2. **Who raised money, and how much?** — structured, rankable funding data.
3. **What is rising?** — topics and projects gaining mentions or stars.

Served through a public Next.js site backed by the existing FastAPI +
hybrid-retrieval + RAG stack, at zero hosting cost.

## 3. Non-goals

- Paid data (Crunchbase, Dealroom, PitchBook). Free sources only.
- Real-time updates. Daily for news, weekly for everything else.
- Neo4j in production. It stays a local, demonstrable artifact; the
  deployed site reads entity links from MongoDB.
- Fuzzy entity matching. Company resolution is strict and measurable.
- Replacing the retrieval design. BM25 + E5/FAISS + graph expansion with
  RRF stays; it is evaluated and the evaluation must not regress.

## 4. Users and questions

| User | Asks |
|---|---|
| Analyst / student | "Which AI startups launched this week?", "Who raised a Series A in the last 30 days?", "What is Suno, and who else is in Cambridge?" |
| Developer | "What new RAG frameworks appeared this month?", "Which repos gained the most stars this week?" |
| Reader | The weekly digest, with every claim linked to its source |

## 5. Current state (measured 2026-09-12)

| | Value |
|---|---|
| Documents | 210 (140 startups, 20 articles, 50 repos) |
| Canonical entities | 647; 83 appear in more than one document |
| Neo4j | 857 nodes, 1,013 MENTIONS relationships |
| Retrieval quality | nDCG@10 0.881, R@10 0.880, MRR 0.938 on 22 labelled queries (65 judgements) |
| Sources | TechCrunch RSS, YC directory (Playwright), StartupSavant (Playwright), GitHub search |
| Freshness | All documents scraped 2025-11-13 |
| Tests | 135 passed, 1 skipped |

Known problems this project fixes:

- Scrapers `insert_one` → duplicates on re-run.
- YC scraper pinned to 2025 batches and fragile CSS classes; GitHub query
  returns the same all-time-top repos every run; TechCrunch feed holds 20 items.
- No pipeline runner, run log or scheduler; Neo4j import blocks on `input()`.
- API loads indexes once with no reload; collection names hardcoded in ~15 files.
- `/graph/query` runs arbitrary Cypher unauthenticated; `/search` forwards a
  raw MongoDB filter from the client; CORS is `*`; endpoints are `async def`
  around blocking calls.
- ~~Evaluation numbers are not reproducible from a fresh clone~~ — fixed in Phase 1.

## 6. Sources

Verified 2026-09-12. Volumes are per week unless noted.

| Source | Type | Access | Volume | Cadence |
|---|---|---|---|---|
| yc-oss companies JSON | startup | public JSON | 1,370 AI-tagged companies, 2023–26 batches (seed) | weekly |
| YC Launches | launch | unofficial JSON | ~15 | weekly |
| Hacker News — Launch HN, Show HN ≥10 pts | launch | Algolia API | ~60 (22 AI-related) | daily |
| TechCrunch AI category | article | RSS, paged | ~37 | daily |
| Crunchbase News | article | RSS | ~8 | daily |
| EU-Startups | article | RSS | ~10 in feed (more with daily fetch) | daily |
| Google News "AI startup raises" | article | RSS | ~74 | daily, optional |
| GitHub repos created this week | repo | API (token) | 2,000+ eligible; cap ~50 by stars | weekly |
| Hugging Face trending models | model | API | 50 | weekly |
| Hugging Face daily papers | paper | API | ~146 | daily |
| StartupSavant top 100 | startup | Playwright | 100 / year | monthly, local only |

Rejected: SEC Form D (no descriptions; mostly funds), arXiv (research, not
startups), Wellfound (blocked), HF Spaces (spam). Backlog: Product Hunt,
BetaList, VentureBeat, SiliconANGLE.

**Projected corpus:** ~1,580 documents at seed; ~450 new per week;
~13,000 after six months.

## 7. Architecture

```
 sources (11)  ──fetch──▶ normalize ──upsert by doc_key──▶ MongoDB `documents`
                                                               │
                        content_hash changed?  ─── yes ───▶ NER ──▶ canonical_entities
                                                               │      (atomic swap)
                                                               ├──▶ E5 embed ──▶ FAISS + BM25 (full rebuild)
                                                               ├──▶ metric_snapshots (stars, likes, downloads)
                                                               └──▶ Neo4j (local only, --yes)
                                                               
 weekly: digest ── funding extraction ── company resolution ── trends
                                                               
 FastAPI (typed filters, admin token, /admin/reload) ◀── Next.js on Vercel
```

Key decisions:

1. **One `documents` collection** with `type ∈ {startup, article, launch,
   repo, model, paper}` and `source`. Migration preserves `_id`, so entity
   links, Neo4j `doc_id` and FAISS metadata stay valid.
2. **Identity:** unique `doc_key` (`startup:yc:{slug}`, `article:{canonical_url}`,
   `repo:gh:{full_name}`, `model:hf:{id}`, …). Upsert sets `first_seen_at`
   once and `last_seen_at` every run.
3. **`content_hash = sha1(document_text(doc))`** decides what gets
   re-processed. Volatile fields (stars) are excluded from the text.
4. **`event_at`** (real datetime) is the only date used for "this week".
   Never falls back to `first_seen_at`.
5. **Embeddings stored as float32 binary** (~3 KB/doc), so the corpus fits
   MongoDB Atlas's free tier and the API can rebuild indexes in memory at boot.
6. **Trend vocabulary is topics** (GitHub topics, HF tags, YC tags, RSS
   categories); NER entities are a secondary view.

## 8. Features

### 8.1 Time-aware retrieval
Planner gains `since_days`, with today's date in the prompt. Retrieval
relaxes constraints in a fixed order (drop location, keep date, then widen
the window) and reports what it relaxed. The date constraint is never
dropped silently.

### 8.2 Weekly digest
One document per ISO week, grouped into Launches / Funding / Open source &
models, generated only from that week's documents. Citation numbers are
assigned before the LLM sees anything; every `[n]` is validated.
Regeneration is a no-op unless the inputs changed.

### 8.3 Companies and funding
Strict resolution order: YC slug → registered domain → normalised name (only
when unique). Funding rounds extracted from news via regex prefilter →
LLM JSON → schema validation, with rule-derived confidence, and de-duplicated
across outlets. "Who raised the most" is answered by a database query, not
by the language model.

### 8.4 Trends
Weekly topic counts; "rising" = count vs trailing 4-week mean, minimum 3.
Star/like velocity from weekly snapshots. Weeks with insufficient history
are labelled as such.

### 8.5 API
Adds `/health`, `/meta`, `/documents`, `/digests*`, `/trends*`,
`/companies*`, `/funding`, `/admin/reload`. Typed search filters, CORS from
config, admin token on `/graph/query` (read-only), request caps and a
per-IP limit on `/chat`.

### 8.6 Frontend
Next.js (App Router, TypeScript, Tailwind) in `web/`: home (latest digest,
rising topics), digests, ask, search, companies, funding, trends, about
(methodology + evaluation). Streamlit moves to `tools/` as a debug view.

## 9. Phases

Each phase: plan → approve → build → test → compare to plan → push → update
this file.

| # | Phase | Status |
|---|---|---|
| 0 | PRD, backup, cleanup, rename | ✅ done 2026-09-12 |
| 1 | Config + frozen evaluation corpus | ✅ done 2026-09-12 |
| 2 | Unified `documents` collection | ⬜ |
| 3 | Ingestion framework + first 3 sources | ⬜ |
| 4 | Incremental processing + scheduling | ⬜ |
| 5 | Remaining sources | ⬜ |
| 6 | Time-aware retrieval + API hardening | ⬜ |
| 7 | Weekly digest | ⬜ |
| 8 | Companies + funding | ⬜ |
| 9 | Trends | ⬜ |
| 10 | Next.js frontend | ⬜ |
| 11 | Deploy (Atlas + HF Spaces + GitHub Actions + Vercel) | ⬜ |

Acceptance criteria per phase are in the phase log below and are checked
before the phase is marked done.

## 10. Risks

| Risk | Mitigation |
|---|---|
| YC blurbs dilute the corpus | Filter to AI tags + recent batches; re-run evaluation after ingest |
| Phase 2 refactor breaks retrieval | Frozen eval corpus (Phase 1) is the regression test; migration keeps `_id` |
| Unofficial endpoints (yc-oss, YC Launches, HN) change | Isolated per source; failures logged, never fatal |
| Groq free-tier limits | Regex prefilter before LLM; cache by content hash |
| Scope | Cut order: Google News → entity trends → company profiles beyond YC-slug matching |

---

## Phase log

### Phase 0 — PRD, backup, cleanup, rename (2026-09-12)

Planned:
- [x] `mongodump` before any mutation → `backups/2026-09-12-pre-live` (857 docs, 1.0 MB), restore verified into a scratch DB
- [x] Private reference note on the friend's TranscoutAI project (`docs/`, gitignored), then delete the clone
- [x] Delete untracked junk (`.DS_Store`, `.benchmarks/`, `.pytest_cache/`, `neo4j-db-load-*/`, empty `notebooks/`, `config/`)
- [x] Keep `neo4j.dump` and built indexes until Phase 1 proves the eval corpus restorable
- [x] `PRD.md` committed at repo root
- [x] Tests still pass (136 passed)
- [x] Push
- [x] Rename folder to `TrendScout - AI Conversational Agent` (venv script paths patched, 133 files)

Deferred deletions (each in the phase that proves nothing imports it):
`src/schemas/*`, `src/llm/normalizer.py` (Phase 2); `src/scrapers/startup_scraper.py`,
`data/ai_startups.py`, `scripts/remove_duplicates.py` (Phase 3);
`scripts/check_collections.py`, unused `mongo_client.py` methods (Phase 4).

Deviations from plan: none.

### Phase 1 — Config + frozen evaluation corpus (2026-09-12)

Planned:
- [x] `src/config.py` (pydantic-settings): Mongo URI/db, `INDEX_DIR`, Neo4j, Groq, GitHub token, CORS origins, admin token; environment overrides `.env`
- [x] Threaded through `MongoDBClient` (now honours `MONGODB_DB`), `BM25Index` (path resolved at call time), `HybridSearchEngine` (`index_dir` arg), `build_indexes.py`, `GroqClient`, `Neo4jClient`, `GitHubScraper` — no `os.getenv` left for these keys
- [x] `data/eval/corpus_v1.jsonl` — 857 records (140 startups, 20 articles, 50 repos, 647 canonical entities), 469 KB, `_id`s preserved, embeddings excluded
- [x] `scripts/export_eval_corpus.py`, `scripts/load_eval_corpus.py --build-indexes` (refuses to overwrite the live DB without `--force`)
- [x] pytest markers `needs_mongo` / `needs_indexes` / `eval_corpus` registered; skipping moved to a collection hook so `-m "not needs_mongo"` works
- [x] `feedparser` installed; `pydantic-settings`, `pytest-socket`, `pytest-recording` pinned
- [x] Tests: 147 passed (136 → +7 config, +4 snapshot integrity)

Acceptance:
- `MONGODB_DB=trendscout_eval INDEX_DIR=data/eval_index python scripts/evaluate_retrieval.py` after a fresh load reproduces the README table **exactly** (BM25 0.743 · Dense 0.882 · Hybrid 0.881 · +Graph naive 0.794 · +Graph recall 0.881 nDCG@10) — target was ±0.005
- Live `data/` indexes untouched by the eval build (separate `INDEX_DIR`)
- `INDEX_DIR=/nonexistent pytest tests/test_integration.py` → 14 skipped with a clear reason, 6 passed

Deviations from plan: none. Extra: `tests/test_eval_corpus.py` checks the
snapshot's counts, that no embeddings leaked in, that every entity link
resolves, and that every label in `queries.json` still matches a title.
