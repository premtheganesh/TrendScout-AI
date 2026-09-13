export default function AboutPage() {
  return (
    <article className="prose prose-zinc max-w-3xl dark:prose-invert">
      <h1 className="text-2xl font-semibold">How TrendScout works</h1>
      <p className="mt-3">
        TrendScout AI is a market-intelligence system over the AI startup ecosystem, built for CSE 573 Semantic Web Mining.
        Eleven free sources — the Y Combinator directory and Launches, Hacker News, TechCrunch, Crunchbase News, EU-Startups,
        Google News, GitHub, Hugging Face models and papers, StartupSavant — are ingested on a schedule into one document
        collection. Each document has a stable key (re-ingesting updates instead of duplicating), a real event date, and a hash
        of its indexed text that decides what gets re-processed.
      </p>
      <h2 className="mt-8 text-lg font-semibold">Retrieval</h2>
      <p className="mt-2">
        Three channels are fused by Reciprocal Rank Fusion: Okapi BM25 for exact terms and names, E5-base-v2 embeddings in a
        FAISS index for meaning, and a shared-entity graph for documents connected to the top hits. Ranking is deterministic —
        no model output influences it — so it is reproducible and measurable. The language model only turns the question into
        a plan (query, type, place, time window) and writes the prose, citing each claim.
      </p>
      <h2 className="mt-8 text-lg font-semibold">Evaluation</h2>
      <p className="mt-2">Measured on a frozen 210-document snapshot with 22 labelled queries and 65 graded judgements (nDCG@10):</p>
      <table className="mt-3 text-sm">
        <thead><tr><th className="pr-6 text-left">Configuration</th><th className="pr-6 text-right">P@10</th><th className="pr-6 text-right">R@10</th><th className="pr-6 text-right">MRR</th><th className="text-right">nDCG@10</th></tr></thead>
        <tbody>
          <tr><td className="pr-6">BM25 only</td><td className="pr-6 text-right">0.218</td><td className="pr-6 text-right">0.771</td><td className="pr-6 text-right">0.816</td><td className="text-right">0.746</td></tr>
          <tr><td className="pr-6">Dense only</td><td className="pr-6 text-right">0.250</td><td className="pr-6 text-right">0.888</td><td className="pr-6 text-right">0.977</td><td className="text-right">0.887</td></tr>
          <tr><td className="pr-6 font-medium">BM25 + Dense</td><td className="pr-6 text-right">0.245</td><td className="pr-6 text-right">0.880</td><td className="pr-6 text-right">0.938</td><td className="text-right font-medium">0.882</td></tr>
          <tr><td className="pr-6">+ Graph (naive)</td><td className="pr-6 text-right">0.245</td><td className="pr-6 text-right">0.883</td><td className="pr-6 text-right">0.779</td><td className="text-right">0.783</td></tr>
          <tr><td className="pr-6">+ Graph (recall)</td><td className="pr-6 text-right">0.245</td><td className="pr-6 text-right">0.880</td><td className="pr-6 text-right">0.938</td><td className="text-right">0.882</td></tr>
        </tbody>
      </table>
      <p className="mt-3 text-sm">
        Dense retrieval carries the system; BM25 earns its place on names and exact terms, and matters more as the corpus grows.
        Naive graph fusion is harmful — a document ranked weakly by both text channels picks up a third contribution and
        overtakes one ranked strongly by a single channel — so the graph channel is restricted to documents the text channels missed.
      </p>
      <h2 className="mt-8 text-lg font-semibold">Funding extraction</h2>
      <p className="mt-2">
        Rounds are extracted from funding news with a regex prefilter, one structured model call per article, schema validation,
        and a rule-derived confidence: <em>high</em> only when the company and the amount both appear verbatim in the text.
        On 41 hand-labelled articles: is-a-round precision 1.00 / recall 0.93, company 27/27, amount 26/27 within 5%, round 10/10.
      </p>
      <h2 className="mt-8 text-lg font-semibold">What it does not do</h2>
      <p className="mt-2">
        It never answers from a model&apos;s training data: when the corpus does not cover a question, it says so. Company matching
        is strict (YC slug, then website domain, then an unambiguous name) — no fuzzy matching. Trends need four weeks of history
        before they are called trends, and velocity needs two days of snapshots.
      </p>
    </article>
  );
}
