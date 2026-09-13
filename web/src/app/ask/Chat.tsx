"use client";

import { useState } from "react";
import Markdown from "@/components/Markdown";
import TypeBadge from "@/components/TypeBadge";
import type { ChatResponse } from "@/lib/types";

type Turn = { role: "user" | "assistant"; content: string; sources?: ChatResponse["sources"]; plan?: ChatResponse["plan"] };

const EXAMPLES = [
  "Which AI startups launched this week?",
  "Which startups raised the most money this month?",
  "What new RAG frameworks appeared recently?",
  "Which research papers about agents have code on GitHub?",
];

function planLine(plan?: ChatResponse["plan"]): string {
  if (!plan) return "";
  const bits: string[] = [];
  if (plan.intent === "funding_ranking") bits.push("ranked by amount");
  if (plan.type) bits.push(`type ${plan.type}`);
  if (plan.effective_since_days) bits.push(`last ${plan.effective_since_days} days`);
  if (plan.relaxations?.length) bits.push(`relaxed: ${plan.relaxations.join(", ").replace(/_/g, " ")}`);
  return bits.join(" · ");
}

export default function Chat() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function ask(q: string) {
    const text = q.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    const history = turns.map((t) => ({ role: t.role, content: t.content }));
    setTurns((prev) => [...prev, { role: "user", content: text }]);
    setQuestion("");
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: text, history }),
      });
      const data = (await res.json()) as ChatResponse & { detail?: string };
      if (!res.ok) throw new Error(data.detail ?? `HTTP ${res.status}`);
      setTurns((prev) => [...prev, { role: "assistant", content: data.answer, sources: data.sources, plan: data.plan }]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "request failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-6 space-y-6">
      {turns.length === 0 && (
        <div className="flex flex-wrap gap-2">
          {EXAMPLES.map((ex) => (
            <button key={ex} onClick={() => ask(ex)} className="rounded-full border border-zinc-300 px-3 py-1 text-sm hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800">
              {ex}
            </button>
          ))}
        </div>
      )}

      <div className="space-y-4">
        {turns.map((t, i) => (
          <div key={i} className={t.role === "user" ? "text-right" : ""}>
            <div className={`inline-block max-w-[85%] rounded-lg px-4 py-3 text-left ${t.role === "user" ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900" : "border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900"}`}>
              {t.role === "user" ? <p>{t.content}</p> : <Markdown text={t.content} anchorPrefix={`t${i}-`} />}
              {t.role === "assistant" && t.plan && planLine(t.plan) && (
                <p className="mt-2 text-xs text-zinc-500">{planLine(t.plan)}</p>
              )}
              {t.role === "assistant" && t.sources && t.sources.length > 0 && (
                <details className="mt-3 text-sm">
                  <summary className="cursor-pointer text-zinc-500">Sources ({t.sources.length})</summary>
                  <ol className="mt-2 space-y-1">
                    {t.sources.map((s) => (
                      <li key={s.n} id={`t${i}-src-${s.n}`} className="flex items-start gap-2">
                        <span className="w-7 shrink-0 font-mono text-xs text-zinc-500">[{s.n}]</span>
                        <TypeBadge type={s.type} />
                        <span>
                          {s.url ? <a href={s.url} target="_blank" rel="noreferrer" className="hover:underline">{s.title}</a> : s.title}
                          {Object.keys(s.ranks ?? {}).length > 0 && (
                            <span className="ml-2 text-xs text-zinc-500">
                              {Object.entries(s.ranks).map(([k, v]) => `${k} #${v}`).join(" · ")}
                            </span>
                          )}
                        </span>
                      </li>
                    ))}
                  </ol>
                </details>
              )}
            </div>
          </div>
        ))}
        {busy && <p className="text-sm text-zinc-500">Retrieving and reasoning…</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          ask(question);
        }}
        className="flex gap-2"
      >
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask about AI startups, launches, funding, repos, models, papers…"
          className="flex-1 rounded-lg border border-zinc-300 bg-white px-3 py-2 dark:border-zinc-700 dark:bg-zinc-900"
          maxLength={2000}
        />
        <button disabled={busy || !question.trim()} className="rounded-lg bg-zinc-900 px-4 py-2 text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900">
          Ask
        </button>
        {turns.length > 0 && (
          <button type="button" onClick={() => setTurns([])} className="rounded-lg border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700">
            Clear
          </button>
        )}
      </form>
    </div>
  );
}
