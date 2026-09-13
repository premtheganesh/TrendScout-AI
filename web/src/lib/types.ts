// Shapes returned by the FastAPI backend (src/api/main.py). Regenerate the
// full OpenAPI types with `npm run gen:api` when the API changes; these are
// the fields the pages use.

export type DocType = "startup" | "article" | "repo" | "launch" | "model" | "paper";

export interface Doc {
  _id: string;
  type: DocType;
  source?: string;
  title: string;
  url: string;
  description?: string;
  name?: string;
  location?: string;
  event_at?: string | null;
  first_seen_at?: string;
  stars?: number;
  likes?: number;
  downloads?: number;
  points?: number;
  upvotes?: number;
  funding?: string;
  yc_batch?: string;
  publisher?: string;
  company_name?: string;
  tags?: string[];
  topics?: string[];
  keywords?: string[];
  [key: string]: unknown;
}

export interface DocumentsResponse {
  items: Doc[];
  count: number;
  total: number;
  offset: number;
  limit: number;
}

export interface Meta {
  documents: { total: number; by_type: Record<string, number> };
  entities: number;
  index: { built_at: string; vectors: number; dimension: number };
  newest_event_at: string | null;
  last_ingested_at: string | null;
  sources: { source: string; type: string; last_run_at: string; status: string; new: number; changed: number; error?: string }[];
  last_pipeline: { started_at: string; status: string; stages: string[] } | null;
}

export interface DigestSource {
  n: number;
  doc_id: string;
  type: DocType;
  title: string;
  url: string;
  event_at?: string | null;
}

export interface DigestSection {
  key: "launches" | "funding" | "open_source";
  title: string;
  markdown: string;
  bullets: number;
  sources: DigestSource[];
}

export interface Digest {
  _id: string;
  week: string;
  week_start: string;
  week_end: string;
  generated_at: string;
  model: string;
  counts: Record<string, number>;
  sections: DigestSection[];
  warnings: { invalid_citations: number; uncited_bullets: number };
}

export interface DigestSummary {
  week: string;
  week_start: string;
  week_end: string;
  generated_at: string;
  counts: Record<string, number>;
  bullets: number;
}

export interface FundingRound {
  _id: string;
  company: string;
  company_key: string;
  amount: number | null;
  currency: string | null;
  amount_usd: number | null;
  round: string | null;
  lead_investors: string[];
  investors: string[];
  valuation: number | null;
  announced_at: string | null;
  confidence: "high" | "medium" | "low";
  source_doc_ids: string[];
  publishers: string[];
}

export interface Company {
  _id: string;
  name: string;
  domain: string;
  website: string;
  yc_slug: string;
  yc_batch: string;
  location: string;
  description: string;
  tags: string[];
  launched_at: string | null;
  doc_ids: Record<string, string[]>;
  document_count: number;
  rounds: FundingRound[] | string[];
  funding_total_usd: number;
  documents?: Doc[];
}

export interface Paged<T> {
  items: T[];
  count: number;
  total: number;
  offset?: number;
  limit?: number;
}

export interface Trends {
  week: string;
  insufficient_history: boolean;
  history_weeks: number;
  rising: { topic: string; count: number; baseline: number; score: number; by_type: Record<string, number> }[];
  top: { topic: string; count: number; by_type: Record<string, number> }[];
}

export interface Velocity {
  type: DocType;
  metric: string;
  days: number;
  insufficient_history: boolean;
  documents_with_history: number;
  items: { doc_id: string; gained: number; now: number; from_date: string; to_date: string; title?: string; url?: string }[];
}

export interface ChatSource {
  n: number;
  doc_id: string;
  type: DocType;
  title: string;
  url: string;
  snippet: string;
  ranks: Record<string, number>;
}

export interface ChatResponse {
  question: string;
  answer: string;
  sources: ChatSource[];
  search_query: string;
  plan: {
    intent?: string;
    type?: string | null;
    location?: string | null;
    since_days?: number | null;
    effective_since_days?: number | null;
    relaxations?: string[];
  };
}

export interface SearchResult {
  doc_id: string;
  type: DocType;
  rrf_score: number | null;
  ranks: Record<string, number>;
  title: string;
  url: string;
  document: Doc;
}
