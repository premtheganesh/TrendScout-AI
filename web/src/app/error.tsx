"use client";

// Rendered when a server component throws (ApiUnavailable, for instance).
// Because the page threw, Next.js keeps the previously cached version for
// visitors who had one; this is what first-time visitors see meanwhile.
export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const unavailable = error.name === "ApiUnavailable" || /backend/i.test(error.message);
  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 p-5 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-100">
      <p className="font-medium">{unavailable ? "The data service is not reachable right now." : "Something went wrong rendering this page."}</p>
      <p className="mt-1">
        {unavailable
          ? "If the backend was asleep it is waking up now; this usually takes under a minute."
          : error.message}
      </p>
      <button onClick={reset} className="mt-3 rounded bg-amber-900 px-3 py-1 text-white dark:bg-amber-100 dark:text-amber-900">
        Try again
      </button>
    </div>
  );
}
