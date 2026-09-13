import { NextRequest, NextResponse } from "next/server";
import { apiPost } from "@/lib/api";
import type { SearchResult } from "@/lib/types";

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => null)) as Record<string, unknown> | null;
  if (!body || typeof body.query !== "string" || !body.query.trim()) {
    return NextResponse.json({ detail: "query is required" }, { status: 400 });
  }
  const payload: Record<string, unknown> = { query: (body.query as string).slice(0, 500), top_k: 20 };
  if (typeof body.type === "string" && body.type) payload.type = body.type;
  if (typeof body.since_days === "number" && body.since_days > 0) payload.since_days = body.since_days;
  if (typeof body.location === "string" && body.location) payload.location = body.location.slice(0, 100);
  const { status, data } = await apiPost<SearchResult[]>("/search", payload);
  if (!data) return NextResponse.json({ detail: "backend unavailable" }, { status: 503 });
  if (!Array.isArray(data)) return NextResponse.json(data, { status });
  // Forward what the UI renders, not the document's processing metadata.
  const slim = data.map((r) => ({
    doc_id: r.doc_id,
    type: r.type,
    rrf_score: r.rrf_score,
    ranks: r.ranks,
    title: r.title,
    url: r.url,
    document: publicFields(r.document),
  }));
  return NextResponse.json(slim, { status });
}

const INTERNAL = new Set(["entities", "content_hash", "embedding_hash", "entities_hash", "funding_hash",
  "funding_extraction_version", "doc_key", "title_key", "embedding_generated_at", "entities_extracted_at",
  "inserted_at", "updated_at", "scraped_at"]);

function publicFields(doc: SearchResult["document"]): SearchResult["document"] {
  return Object.fromEntries(Object.entries(doc).filter(([k]) => !INTERNAL.has(k))) as SearchResult["document"];
}
