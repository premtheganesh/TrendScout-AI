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
  return NextResponse.json(data ?? { detail: "backend unavailable" }, { status: data ? status : 503 });
}
