export default function Unavailable({ what = "The API" }: { what?: string }) {
  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-100">
      {what} is not reachable right now. If the backend is asleep it will wake on the next request; try again in a minute.
    </div>
  );
}
