import { ageSpan, formatAgeBand, safeHexColor, truncate } from "./format";
import { allClasses } from "./page-model";
import type { PublicPageResult } from "./types";

export const OG_CARD_SIZE = { width: 1200, height: 630 } as const;

export interface OgCardContent {
  title: string;
  subtitle: string;
  lane: string;
}

/** Text and lane colour for the card; brand colours come from the backend. */
export function ogCardContent(result: PublicPageResult): OgCardContent {
  if (result.kind === "published") {
    const page = result.page;
    const classes = allClasses(page);
    const span = formatAgeBand(
      ageSpan([...page.programs.map((p) => p.age_band), ...classes.map((c) => c.age_band)]),
    );
    const parts = [span, page.academy.venue.address].filter(Boolean) as string[];
    return {
      title: truncate(page.academy.name, 40),
      subtitle: truncate(parts.join(" · ") || "Classes and prices", 90),
      lane: safeHexColor(page.academy.brand_fill, "#facc15"),
    };
  }
  if (result.kind === "not_published") {
    return {
      title: truncate(result.page.academy.name, 40),
      subtitle: "Parent sign in",
      lane: safeHexColor(result.page.academy.brand_fill, "#facc15"),
    };
  }
  return { title: "CourtMastr", subtitle: "Academy classes and bookings", lane: "#facc15" };
}

/** The 1200x630 card: academy name on night with the brand lane line. */
export function OgCard({ content }: { content: OgCardContent }) {
  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        background: "#0a0f1c",
        color: "#ffffff",
        padding: "72px 80px 0 80px",
      }}
    >
      <div style={{ display: "flex", flexDirection: "column" }}>
        <div style={{ fontSize: 76, fontWeight: 700, lineHeight: 1.05, letterSpacing: -2 }}>
          {content.title}
        </div>
        <div style={{ marginTop: 28, fontSize: 34, color: "#cbd5e1", lineHeight: 1.3 }}>
          {content.subtitle}
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "column" }}>
        <div style={{ fontSize: 24, color: "#94a3b8", marginBottom: 28 }}>
          Bookings and payments by CourtMastr
        </div>
        <div style={{ height: 18, marginLeft: -80, marginRight: -80, background: content.lane }} />
      </div>
    </div>
  );
}
