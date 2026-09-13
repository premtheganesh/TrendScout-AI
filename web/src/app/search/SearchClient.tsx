"use client";

import { useState } from "react";
import DocCard from "@/components/DocCard";
import type { SearchResult } from "@/lib/types";

const TYPES = ["", "startup", "article", "repo", "launch", "model", "paper"];
const WINDOWS: [number, string][] = [[0, "any time"], [7, "last 7 days"], [30, "last 30 days"], [90, "last 90 days"], [365, "last year"]];

export default function SearchClient() {
  const [query, setQuery] = useState("");
  const [type, setType] = useState("");
  const [since, setSince] = useState(0);
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, type: type || undefined, since_days: since || undefined }),
      });
      const data = (await res.json()) as SearchResult[] | { detail?: string };
      if (!res.ok || !Array.isArray(data)) throw new Error((data as { detail?: string }).detail ?? `HTTP ${res.status}`);
      setResults(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "request failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-6 space-y-6">
      <form onSubmit={run} className="flex flex-wrap gap-2">
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="e.g. AI music generation startup" className="min-w-[240px] flex-1 rounded-lg border border-zinc-300 bg-white px-3 py-2 dark:border-zinc-700 dark:bg-zinc-900" />
        <select value={type} onChange={(e) => setType(e.target.value)} className="rounded-lg border border-zinc-300 bg-white px-2 py-2 dark:border-zinc-700 dark:bg-zinc-900">
          {TYPES.map((t) => <option key={t} value={t}>{t || "all types"}</option>)}
        </select>
        <select value={since} onChange={(e) => setSince(Number(e.target.value))} className="rounded-lg border border-zinc-300 bg-white px-2 py-2 dark:border-zinc-700 dark:bg-zinc-900">
          {WINDOWS.map(([d, label]) => <option key={d} value={d}>{label}</option>)}
        </select>
        <button disabled={busy} className="rounded-lg bg-zinc-900 px-4 py-2 text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900">Search</button>
      </form>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {results && (
        <div className="space-y-3">
          <p className="text-sm text-zinc-500">{results.length} results</p>
          {results.map((r) => (
            <div key={r.doc_id}>
              <DocCard doc={{ ...r.document, title: r.title, url: r.url, type: r.type }} />
              <p className="mt-1 pl-1 text-xs text-zinc-500">
                found by {Object.entries(r.ranks).map(([k, v]) => `${k} #${v}`).join(" · ")}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
