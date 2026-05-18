import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Academy Manager",
};

export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
