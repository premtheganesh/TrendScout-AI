import SearchClient from "./SearchClient";

export default function SearchPage() {
  return (
    <div>
      <h1 className="text-2xl font-semibold">Search</h1>
      <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
        BM25 + E5 dense retrieval + shared-entity graph expansion, fused by reciprocal rank. Each result shows which channels found it.
      </p>
      <SearchClient />
    </div>
  );
}
