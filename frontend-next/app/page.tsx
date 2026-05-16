import Link from "next/link";

export default function LandingPage() {
  return (
    <div className="text-center space-y-6">
      <h1 className="text-3xl font-semibold">Academy Manager</h1>
      <p className="text-neutral-600 dark:text-neutral-400">
        Badminton academy management for coaches, parents, and admins.
      </p>
      <Link
        href="/login"
        className="inline-flex min-h-touch min-w-touch items-center justify-center rounded-md bg-neutral-900 px-6 text-white hover:bg-neutral-800 dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-200"
      >
        Sign in
      </Link>
    </div>
  );
}
