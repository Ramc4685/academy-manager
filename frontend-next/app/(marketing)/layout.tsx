import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Academy Manager",
};

export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return (
    <main className="min-h-screen flex items-center justify-center px-4 py-10">
      <div className="w-full max-w-md">{children}</div>
    </main>
  );
}
