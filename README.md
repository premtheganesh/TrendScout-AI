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
                    |             query, collection,       |
                    |             location filter          |
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

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm

cp .env.example .env        # then fill in GROQ_API_KEY and MongoDB/Neo4j

python scripts/extract_entities.py     # NER + canonical entity index
python scripts/build_indexes.py        # E5 embeddings -> FAISS, and BM25
python scripts/setup_neo4j_schema.py   # optional
python scripts/import_to_neo4j.py

python src/api/main.py                 # API -> localhost:8000/docs
streamlit run src/ui/app.py            # UI  -> localhost:8501
```

MongoDB must be running (`brew services start mongodb-community`). Neo4j is
optional: if it is unreachable the graph endpoints return 503 and everything
else works, because graph-expansion retrieval reads the same entity links
from MongoDB.

All configuration is read from `.env` through `src/config.py`; any value can
be overridden per process (`MONGODB_DB=... INDEX_DIR=... python ...`).

### Reproducing the evaluation

The corpus the numbers above were measured on is committed as
`data/eval/corpus_v1.jsonl` (857 records, no embeddings). Load it into its
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
| `POST` | `/search`                 | Hybrid search; toggle channels per request |
| `POST` | `/similar`                | "More like this" by embedding             |
| `POST` | `/graph/query`            | Arbitrary Cypher                          |
| `GET`  | `/graph/entities`         | Most-mentioned entities                   |
| `GET`  | `/graph/startup/{name}`   | One startup's entity neighbourhood        |
| `GET`  | `/stats`                  | Corpus and index counts                   |

```bash
curl -X POST localhost:8000/chat -H 'Content-Type: application/json' \
  -d '{"question": "Which AI startups in San Francisco raised funding?"}'
```

Search results carry the per-channel ranks that produced them
(`"ranks": {"keyword": 1, "semantic": 3}`), so the ordering is explainable.

## Layout

```
src/
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
  ui/app.py               Streamlit
  config.py               all settings, from .env / environment
scripts/
  build_indexes.py        rebuild FAISS + BM25 into INDEX_DIR
  extract_entities.py     NER + canonical entity index
  evaluate_retrieval.py   metrics, ablations, weight sweep
  export_eval_corpus.py   freeze the corpus as a snapshot
  load_eval_corpus.py     load a snapshot into a separate database
  import_to_neo4j.py      push the graph to Neo4j
data/eval/queries.json    labelled evaluation set
data/eval/corpus_v1.jsonl frozen corpus the numbers were measured on
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

## Corpus

| Collection     | Documents | Source                       |
| -------------- | --------- | ---------------------------- |
| `startups`     | 140       | StartupSavant, Y Combinator  |
| `articles`     | 20        | TechCrunch RSS               |
| `github_repos` | 50        | GitHub API                   |
| **total**      | **210**   | 647 canonical entities       |

83 of those entities appear in more than one document; those create the
graph edges. In Neo4j: 857 nodes, 1013 MENTIONS relationships.

## Stack

Python 3.13, MongoDB, Neo4j, FAISS, rank-bm25, intfloat/e5-base-v2, spaCy,
Groq, FastAPI, Streamlit, pytest.
