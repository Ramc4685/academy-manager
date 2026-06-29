import Link from "next/link";

/**
 * App-wide 404. Friendly copy with a single recovery action — no internal
 * routing details exposed.
 */
export default function NotFound() {
  return (
    <main className="flex min-h-dvh items-center justify-center bg-slate-50 p-6 font-body text-slate-950">
      <div className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-8 text-center shadow-sm">
        <p className="font-display text-sm font-semibold uppercase tracking-wide text-blue-600">
          404
        </p>
        <h1 className="mt-1 font-display text-2xl font-bold text-slate-900">Page not found</h1>
        <p className="mt-2 text-sm text-slate-600">
          The page you are looking for does not exist or may have moved.
        </p>
        <Link
          href="/"
          className="mt-6 inline-flex min-h-touch items-center justify-center rounded-md bg-blue-600 px-4 text-sm font-medium text-white shadow-sm transition hover:bg-blue-500"
        >
          Go home
        </Link>
      </div>
    </main>
  );
}
