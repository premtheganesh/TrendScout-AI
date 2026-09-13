export function money(usd: number | null | undefined): string {
  if (usd == null) return "undisclosed";
  if (usd >= 1e9) return `$${(usd / 1e9).toFixed(usd >= 1e10 ? 0 : 1)}B`;
  if (usd >= 1e6) return `$${(usd / 1e6).toFixed(usd >= 1e8 ? 0 : 1)}M`;
  if (usd >= 1e3) return `$${(usd / 1e3).toFixed(0)}K`;
  return `$${usd.toFixed(0)}`;
}

export function day(iso: string | null | undefined): string {
  if (!iso) return "";
  return iso.slice(0, 10);
}

export function num(n: number | null | undefined): string {
  if (n == null) return "";
  return n.toLocaleString("en-US");
}

export const TYPE_LABEL: Record<string, string> = {
  startup: "Startup",
  article: "News",
  repo: "Repo",
  launch: "Launch",
  model: "Model",
  paper: "Paper",
};

export const TYPE_COLOR: Record<string, string> = {
  startup: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200",
  article: "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-200",
  repo: "bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-200",
  launch: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200",
  model: "bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-200",
  paper: "bg-indigo-100 text-indigo-800 dark:bg-indigo-900/40 dark:text-indigo-200",
};

export function docSubtitle(d: { type: string; stars?: number; likes?: number; points?: number; upvotes?: number; funding?: string; location?: string; yc_batch?: string; publisher?: string; source?: string }): string {
  const bits: string[] = [];
  if (d.type === "repo" && d.stars != null) bits.push(`${num(d.stars)} stars`);
  if (d.type === "model" && d.likes != null) bits.push(`${num(d.likes)} likes`);
  if (d.type === "launch" && d.points != null) bits.push(`${num(d.points)} points`);
  if (d.type === "paper" && d.upvotes != null) bits.push(`${num(d.upvotes)} upvotes`);
  if (d.type === "startup") {
    if (d.yc_batch && d.yc_batch !== "Unknown") bits.push(`YC ${d.yc_batch}`);
    if (d.location && d.location !== "Unknown") bits.push(d.location);
    if (d.funding && d.funding !== "Unknown") bits.push(d.funding);
  }
  if (d.type === "article") bits.push(d.publisher || d.source || "");
  return bits.filter(Boolean).join(" · ");
}
