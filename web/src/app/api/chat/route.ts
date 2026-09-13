import { NextRequest, NextResponse } from "next/server";
import { apiPost } from "@/lib/api";
import type { ChatResponse } from "@/lib/types";

// Proxies /chat so the browser never sees the backend URL and CORS never
// enters the picture. Only the fields the UI needs are forwarded.
export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => null)) as { question?: string; history?: unknown; top_k?: number } | null;
  if (!body || typeof body.question !== "string" || !body.question.trim()) {
    return NextResponse.json({ detail: "question is required" }, { status: 400 });
  }
  const { status, data } = await apiPost<ChatResponse>("/chat", {
    question: body.question.slice(0, 2000),
    history: Array.isArray(body.history) ? body.history.slice(-10) : undefined,
    top_k: Math.min(Math.max(Number(body.top_k) || 8, 1), 12),
  });
  return NextResponse.json(data ?? { detail: "backend unavailable" }, { status: data ? status : 503 });
}
