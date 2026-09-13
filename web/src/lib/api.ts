// Server-side access to the FastAPI backend. Pages call these from server
// components; the browser only ever talks to this app's own /api routes.
import "server-only";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

export const REVALIDATE_SECONDS = 600;

// Thrown when the backend is unreachable or failing. Pages are rendered
// per request, but each fetch below is cached for REVALIDATE_SECONDS in
// Next's data cache, which keeps serving the last good data when a
// refresh fails — so an outage only surfaces (via app/error.tsx) for data
// nobody has fetched before.
export class ApiUnavailable extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ApiUnavailable";
  }
}

/** GET a JSON endpoint. Returns null only for a genuine 404; any other
 *  failure throws ApiUnavailable. */
export async function apiGet<T>(path: string, revalidate: number = REVALIDATE_SECONDS): Promise<T | null> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { next: { revalidate } });
  } catch (e) {
    throw new ApiUnavailable(`backend unreachable: ${e instanceof Error ? e.message : String(e)}`);
  }
  if (res.status === 404) return null;
  if (!res.ok) throw new ApiUnavailable(`backend returned ${res.status} for ${path}`);
  return (await res.json()) as T;
}

export async function apiPost<T>(path: string, body: unknown): Promise<{ status: number; data: T | null }> {
  try {
    const res = await fetch(`${API_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    const data = (await res.json().catch(() => null)) as T | null;
    return { status: res.status, data };
  } catch {
    return { status: 503, data: null };
  }
}
