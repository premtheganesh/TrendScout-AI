// Server-side access to the FastAPI backend. Pages call these from server
// components; the browser only ever talks to this app's own /api routes.

const API_URL = process.env.API_URL ?? "http://localhost:8000";

export const REVALIDATE_SECONDS = 600;

export class ApiUnavailable extends Error {}

export async function apiGet<T>(path: string, revalidate: number = REVALIDATE_SECONDS): Promise<T | null> {
  try {
    const res = await fetch(`${API_URL}${path}`, { next: { revalidate } });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    // The backend may be asleep or unreachable; pages render an honest
    // "unavailable" state instead of failing the build or the request.
    return null;
  }
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

export function apiBase(): string {
  return API_URL;
}
