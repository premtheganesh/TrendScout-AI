"""
Streamlit frontend. Requires the API on http://localhost:8000.

    streamlit run src/ui/app.py
"""

import streamlit as st
import requests
import pandas as pd

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

API_BASE = "http://localhost:8000"

st.set_page_config(
    page_title="TrendScout AI",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def api_get(path: str, params: dict = None):
    """GET request to FastAPI; returns JSON or None on error."""
    try:
        r = requests.get(f"{API_BASE}{path}", params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        st.error("Cannot reach the API. Is `src/api/main.py` running on port 8000?")
        return None
    except Exception as e:
        st.error(f"API error: {e}")
        return None


def api_post(path: str, payload: dict, timeout: int = 30):
    """POST request to FastAPI; returns JSON or None on error."""
    try:
        r = requests.post(f"{API_BASE}{path}", json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        st.error("Cannot reach the API. Is `src/api/main.py` running on port 8000?")
        return None
    except Exception as e:
        st.error(f"API error: {e}")
        return None


def check_api_health() -> bool:
    try:
        r = requests.get(f"{API_BASE}/", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("TrendScout AI")
    st.caption("AI Startup Discovery — CSE 573")

    healthy = check_api_health()
    if healthy:
        st.success("API Online")
    else:
        st.error("API Offline")
        st.info("Start the API:\n```\n.venv/bin/python src/api/main.py\n```")

    st.divider()

    page = st.radio(
        "Navigate",
        ["This Week", "Ask", "Search", "Knowledge Graph", "Statistics"],
        label_visibility="collapsed",
    )

    if page == "Ask"and st.button("Clear conversation"):
        st.session_state.chat_history = []
        st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# PAGE: ASK  (RAG)
# ─────────────────────────────────────────────────────────────────────────────

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []


def render_sources(sources: list, key_prefix: str):
    """Show the documents an answer was grounded in."""
    if not sources:
        return
    with st.expander(f"Sources ({len(sources)})", expanded=False):
        for src in sources:
            cols = st.columns([1, 11])
            with cols[0]:
                st.markdown(f"**[{src['n']}]**")
            with cols[1]:
                title = src.get("title", "Untitled")
                url = src.get("url", "")
                if url:
                    st.markdown(f"**[{title}]({url})**  ·  `{src.get('type','')}`")
                else:
                    st.markdown(f"**{title}**  ·  `{src.get('type','')}`")

                snippet = src.get("snippet", "")
                if snippet:
                    st.caption(snippet)

                # Show which retrieval channels found this document — the
                # difference between a ranked list and an explainable one.
                ranks = src.get("ranks") or {}
                if ranks:
                    channel_names = {
                        "keyword": "BM25",
                        "semantic": "dense",
                        "graph": "graph",
                    }
                    badges = "  ".join(
                        f"`{channel_names.get(k, k)} #{v}`" for k, v in sorted(ranks.items())
                    )
                    st.caption(f"Found by: {badges}")

                shared = src.get("shared_entities") or []
                if shared:
                    st.caption("Linked via: " + ", ".join(shared[:5]))
            st.divider()


if page == "This Week":
    st.title("This Week in AI Startups")
    digests = api_get("/digests") if healthy else None
    if not digests or not digests.get("items"):
        st.info("No digest yet. Run `python scripts/generate_digest.py`.")
    else:
        weeks = [d["week"] for d in digests["items"]]
        week = st.selectbox("Week", weeks)
        digest = api_get(f"/digests/{week}")
        if digest:
            st.caption(
                f"{str(digest.get('week_start', ''))[:10]} → {str(digest.get('week_end', ''))[:10]}"
                f" · generated {str(digest.get('generated_at', ''))[:16]} · {digest.get('model', '')}"
            )
            for section in digest.get("sections", []):
                st.subheader(section["title"])
                if section.get("markdown"):
                    st.markdown(section["markdown"])
                else:
                    st.caption("Nothing this week.")
                with st.expander(f"Sources ({len(section.get('sources', []))})"):
                    for src in section.get("sources", []):
                        line = f"**[{src['n']}]** {src['title']} · `{src['type']}`"
                        if src.get("url"):
                            line += f" · [link]({src['url']})"
                        st.markdown(line)

elif page == "Ask":
    st.title("Ask TrendScout")
    st.caption(
        "Retrieval-augmented answers grounded in the indexed corpus. "
        "Every claim is cited **[n]** against a source below it — if the "
        "corpus doesn't cover something, the answer says so rather than "
        "guessing."
    )

    if not healthy:
        st.warning("Start the API to ask questions.")
    else:
        if not st.session_state.chat_history:
            st.markdown("**Try one of these:**")
            examples = [
                "Which AI music startups are indexed and who funded them?",
                "What open source RAG frameworks are in the corpus?",
                "Which startups are based in Boston?",
                "What is the most recent AI funding news?",
            ]
            cols = st.columns(2)
            for i, example in enumerate(examples):
                if cols[i % 2].button(example, key=f"ex_{i}", use_container_width=True):
                    st.session_state.pending_question = example
                    st.rerun()

        for turn in st.session_state.chat_history:
            with st.chat_message(turn["role"]):
                st.markdown(turn["content"])
                if turn["role"] == "assistant":
                    render_sources(turn.get("sources", []), key_prefix=turn.get("id", ""))

        question = st.chat_input("Ask about AI startups, articles or repos…")
        if not question and st.session_state.get("pending_question"):
            question = st.session_state.pop("pending_question")

        if question:
            with st.chat_message("user"):
                st.markdown(question)

            with st.chat_message("assistant"):
                with st.spinner("Retrieving and reasoning…"):
                    history = [
                        {"role": t["role"], "content": t["content"]}
                        for t in st.session_state.chat_history
                    ]
                    payload = {
                        "question": question,
                        "top_k": 8,
                        "history": history,
                    }
                    result = api_post("/chat", payload, timeout=120)

                if result:
                    st.markdown(result["answer"])
                    render_sources(result.get("sources", []), key_prefix="live")

                    plan = result.get("plan") or {}
                    bits = []
                    if plan.get("search_query"):
                        bits.append(f"searched `{plan['search_query']}`")
                    if plan.get("type"):
                        bits.append(f"in `{plan['type']}`")
                    if plan.get("location"):
                        bits.append(f"filtered to `{plan['location']}`")
                    if bits:
                        st.caption("· ".join(bits))

                    st.session_state.chat_history.append(
                        {"role": "user", "content": question})
                    st.session_state.chat_history.append({
                        "role": "assistant",
                        "content": result["answer"],
                        "sources": result.get("sources", []),
                    })


# ─────────────────────────────────────────────────────────────────────────────
# PAGE: SEARCH
# ─────────────────────────────────────────────────────────────────────────────

elif page == "Search":
    st.title("Hybrid Search")
    st.caption(
        "BM25, E5+FAISS and shared-entity graph expansion, fused with "
        "Reciprocal Rank Fusion."
    )

    col1, col2 = st.columns([3, 1])
    with col1:
        query = st.text_input("Search query", placeholder="e.g. AI music generation startup")
    with col2:
        doc_type = st.selectbox(
            "Type",
            ["All", "startup", "article", "repo", "launch", "model", "paper"],
        )

    with st.expander("Advanced options"):
        col_a, col_b, col_c, col_d = st.columns(4)
        with col_a:
            top_k = st.slider("Results", 1, 20, 10)
        with col_b:
            use_keyword = st.checkbox("BM25 (lexical)", value=True)
        with col_c:
            use_semantic = st.checkbox("E5 (semantic)", value=True)
        with col_d:
            use_graph = st.checkbox("Graph expansion", value=True)

    if st.button("Search", type="primary", disabled=not healthy):
        if not query.strip():
            st.warning("Please enter a search query.")
        else:
            with st.spinner("Searching…"):
                payload = {
                    "query": query,
                    "type": None if doc_type == "All" else doc_type,
                    "top_k": top_k,
                    "use_keyword": use_keyword,
                    "use_semantic": use_semantic,
                    "use_graph": use_graph,
                }
                results = api_post("/search", payload)

            if results is not None:
                if not results:
                    st.info("No results found. Try a different query.")
                else:
                    st.success(f"Found **{len(results)}** results")
                    for i, r in enumerate(results, 1):
                        doc = r.get("document", {})
                        name = doc.get("name") or doc.get("title") or doc.get("repo_name") or "Untitled"
                        desc = doc.get("description") or doc.get("summary") or doc.get("content", "")
                        score = r.get("rrf_score")
                        coll = r.get("type", "")
                        doc_id = r.get("doc_id", "")

                        with st.expander(f"{i}. {name}  —  `{coll}`  {'·  Score: {:.4f}'.format(score) if score else ''}"):
                            if desc:
                                st.write(desc[:400] + ("…" if len(desc) > 400 else ""))

                            # Extra fields depending on type
                            meta_cols = st.columns(3)
                            if doc.get("location"):
                                meta_cols[0].metric("Location", doc["location"])
                            if doc.get("industry"):
                                meta_cols[1].metric("Industry", doc["industry"])
                            if doc.get("founded_year"):
                                meta_cols[2].metric("Founded", doc["founded_year"])
                            if doc.get("stars"):
                                meta_cols[0].metric("Stars", doc["stars"])
                            if doc.get("language"):
                                meta_cols[1].metric("Language", doc["language"])
                            if doc.get("published_date"):
                                meta_cols[2].metric("Published", doc["published_date"])

                            # "More like this" button
                            if st.button("Find similar", key=f"sim_{i}"):
                                with st.spinner("Finding similar documents…"):
                                    sim_payload = {"doc_id": doc_id, "top_k": 5}
                                    similar = api_post("/similar", sim_payload)
                                if similar:
                                    st.write("**Similar documents:**")
                                    for s in similar:
                                        sdoc = s.get("document", {})
                                        sname = sdoc.get("name") or sdoc.get("title") or sdoc.get("repo_name") or "Untitled"
                                        st.write(f"- {sname} (`{s.get('type')}`)")


# ─────────────────────────────────────────────────────────────────────────────
# PAGE: KNOWLEDGE GRAPH
# ─────────────────────────────────────────────────────────────────────────────

elif page == "Knowledge Graph":
    st.title("Knowledge Graph Explorer")
    st.caption("Explore entities extracted from startups, articles, and repos via spaCy NER.")

    tab1, tab2, tab3 = st.tabs(["Top Entities", "Startup Entities", "Custom Cypher"])

    # ── Tab 1: Top entities ──────────────────────────────────────────────────
    with tab1:
        st.subheader("Most-mentioned entities")

        col1, col2 = st.columns([2, 1])
        with col1:
            entity_type = st.selectbox(
                "Filter by type",
                ["All", "ORG", "PERSON", "GPE", "MONEY", "PRODUCT", "DATE", "EVENT"],
            )
        with col2:
            entity_limit = st.slider("Show top N", 5, 50, 15)

        if st.button("Load entities", disabled=not healthy):
            with st.spinner("Querying knowledge graph…"):
                params = {"limit": entity_limit}
                if entity_type != "All":
                    params["entity_type"] = entity_type
                data = api_get("/graph/entities", params)

            if data:
                entities = data.get("entities", [])
                if not entities:
                    st.info("No entities found for that filter.")
                else:
                    df = pd.DataFrame(entities)
                    # Bar chart
                    st.bar_chart(df.set_index("entity")["mentions"])
                    # Table
                    st.dataframe(
                        df.rename(columns={"entity": "Entity", "type": "Type", "mentions": "Mentions"}),
                        use_container_width=True,
                        hide_index=True,
                    )
                    st.caption(f"Showing {len(entities)} entities")

    # ── Tab 2: Startup entities ───────────────────────────────────────────────
    with tab2:
        st.subheader("Entities for a specific startup")
        startup_name = st.text_input("Startup name", placeholder="e.g. Suno")

        if st.button("Look up", disabled=not healthy):
            if not startup_name.strip():
                st.warning("Enter a startup name.")
            else:
                with st.spinner(f"Looking up {startup_name}…"):
                    data = api_get(f"/graph/startup/{startup_name.strip()}")

                if data:
                    entities = data.get("entities", [])
                    st.success(f"**{startup_name}** mentions **{data.get('count', 0)}** entities")
                    if entities:
                        df = pd.DataFrame(entities)
                        # Group by type
                        for etype, group in df.groupby("type"):
                            with st.expander(f"{etype} ({len(group)})"):
                                st.write(", ".join(group["entity"].tolist()))

    # ── Tab 3: Custom Cypher ──────────────────────────────────────────────────
    with tab3:
        st.subheader("Run a custom Cypher query")

        default_query = (
            "MATCH (s:Startup)-[:MENTIONS]->(e:Entity)\n"
            "WHERE e.entity_type = 'ORG'\n"
            "RETURN s.name AS startup, e.entity_text AS org\n"
            "LIMIT 10"
        )
        cypher = st.text_area("Cypher query", value=default_query, height=120)

        if st.button("Run query", disabled=not healthy):
            with st.spinner("Executing…"):
                data = api_post("/graph/query", {"query": cypher})

            if data:
                results = data.get("results", [])
                st.info(f"Returned **{data.get('count', 0)}** records")
                if results:
                    st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────────────────────────
# PAGE: STATISTICS
# ─────────────────────────────────────────────────────────────────────────────

elif page == "Statistics":
    st.title("System Statistics")
    st.caption("Live counts from MongoDB, Neo4j, and the FAISS vector index.")

    if st.button("Refresh stats", disabled=not healthy) or healthy:
        with st.spinner("Loading…"):
            data = api_get("/stats")

        if data:
            docs = data.get("documents", {})
            by_type = docs.get("by_type", {})
            neo4j = data.get("neo4j", {})
            emb = data.get("embeddings", {})

            # ── Row 1: MongoDB ────────────────────────────────────────────────
            st.subheader("MongoDB (Document Store)")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Startups", by_type.get("startup", 0))
            c2.metric("Articles", by_type.get("article", 0))
            c3.metric("GitHub Repos", by_type.get("repo", 0))
            c4.metric("Total Documents", docs.get("total", 0))

            st.divider()

            # ── Row 2: Neo4j ──────────────────────────────────────────────────
            st.subheader("Neo4j (Knowledge Graph)")
            if neo4j.get("status") == "unavailable":
                st.warning(
                    "Neo4j is offline. "
                    "Start it and restart the API; graph views need it.",
                )
            else:
                c1, c2, c3 = st.columns(3)
                c1.metric("Total Nodes", neo4j.get("total_nodes", 0))
                c2.metric("Entities", neo4j.get("entities", 0))
                c3.metric("Relationships", neo4j.get("relationships", 0))

            st.divider()

            # ── Row 3: Embeddings ─────────────────────────────────────────────
            st.subheader("FAISS Vector Index")
            c1, c2 = st.columns(2)
            c1.metric("Vectors", emb.get("vectors", 0))
            c2.metric("Dimensions", emb.get("dimension", 0))

            # Simple summary bar
            st.divider()
            st.subheader("Data breakdown")
            breakdown = {
                "Startups": by_type.get("startup", 0),
                "Articles": by_type.get("article", 0),
                "GitHub Repos": by_type.get("repo", 0),
            }
            st.bar_chart(pd.Series(breakdown))
