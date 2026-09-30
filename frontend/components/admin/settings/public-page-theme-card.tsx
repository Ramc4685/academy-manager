"use client";

import { useQuery } from "@tanstack/react-query";

import { getAdminAcademy } from "@/lib/api/admin";
import { monogram, safeHttpsUrl } from "@/lib/public-page/format";
import {
  PUBLIC_PAGE_THEMES,
  THEME_HINT,
  THEME_LABEL,
  themePreview,
  type PublicPageTheme,
} from "@/lib/public-page/theme";
import { queryKeys } from "@/lib/query/keys";

/**
 * Settings -> Public page -> Theme (Settings overhaul Phase 6). Three presets
 * shown as swatches previewing the academy's own brand colour and logo. The
 * choice is part of the page form's draft (one Save), so this card holds no
 * state of its own.
 */
export function PublicPageThemeCard({
  value,
  onChange,
}: {
  value: PublicPageTheme;
  onChange: (theme: PublicPageTheme) => void;
}) {
  const academy = useQuery({
    queryKey: queryKeys.admin.academy(),
    queryFn: () => getAdminAcademy(),
  });
  const brandColor = academy.data?.brand_color ?? null;
  const logo = safeHttpsUrl(academy.data?.logo_url);
  const name = academy.data?.display_name?.trim() || "Your academy";

  return (
    <fieldset className="mt-1" data-testid="public-page-theme-card">
      <legend className="text-sm font-semibold text-rally-ink">Theme</legend>
      <p className="mt-1 text-sm text-rally-muted">
        Every theme uses your logo and brand colour from Academy profile, adjusted so text is
        always readable.
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        {PUBLIC_PAGE_THEMES.map((theme) => {
          const selected = value === theme;
          const p = themePreview(theme, brandColor);
          return (
            <label
              key={theme}
              data-testid={`public-page-theme-${theme}`}
              className={`block cursor-pointer rounded-md border p-2 text-sm has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-rally-cobalt-600 ${
                selected ? "border-rally-cobalt-600 ring-2 ring-rally-cobalt-600" : "border-rally-line"
              }`}
            >
              <input
                type="radio"
                name="public-page-theme"
                value={theme}
                checked={selected}
                onChange={() => onChange(theme)}
                className="sr-only"
              />
              <span
                aria-hidden="true"
                data-testid={`public-page-theme-swatch-${theme}`}
                className="block overflow-hidden rounded border border-rally-line"
                style={{ background: p.page }}
              >
                <span
                  className="flex items-center gap-2 px-2 py-2"
                  style={{
                    background: p.photo
                      ? `linear-gradient(rgba(10,15,28,0.68), rgba(10,15,28,0.68)), linear-gradient(135deg, #64748b, #94a3b8)`
                      : p.band,
                    color: p.text,
                  }}
                >
                  {logo ? (
                    <img
                      src={logo}
                      alt=""
                      width={20}
                      height={20}
                      className="size-5 rounded bg-white object-contain p-px"
                    />
                  ) : (
                    <span
                      className="grid size-5 place-items-center rounded text-[9px] font-bold"
                      style={{ background: p.fill, color: p.on }}
                    >
                      {monogram(name)}
                    </span>
                  )}
                  <span className="truncate text-xs font-semibold">{name}</span>
                </span>
                <span
                  className="flex items-center justify-between gap-2 px-2 py-2"
                  style={{ background: p.page }}
                >
                  <span
                    className="text-xs font-semibold"
                    style={{ color: p.accent ?? "#0f172a" }}
                  >
                    Classes
                  </span>
                  <span
                    className="rounded px-2 py-1 text-xs font-bold"
                    style={{ background: p.fill, color: p.on }}
                  >
                    Book a trial
                  </span>
                </span>
              </span>
              <span className="mt-2 block font-semibold text-rally-ink">
                {THEME_LABEL[theme]}
              </span>
              <span className="block text-xs text-rally-subtle">{THEME_HINT[theme]}</span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
