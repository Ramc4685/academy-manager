"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getAdminPublicPageSettings,
  listAdminClassPublicProfiles,
  updateAdminClassPublicFields,
  type AdminClassPublicProfileView,
} from "@/lib/api/admin";
import { viewPageHref } from "@/lib/public-page/admin-settings";
import { queryKeys } from "@/lib/query/keys";
import { Card } from "@/components/ds/card";

const SETTINGS_HREF = "/admin/settings?panel=public-page";

/** S55 / D-22: a new class starts shown only once the academy page is published. */
export function defaultShowOnPublicPage(pagePublished: boolean | undefined): boolean {
  return pagePublished === true;
}

export function showOnPublicPageHint(pagePublished: boolean | undefined): string {
  return pagePublished
    ? "Anyone visiting your public page sees its days, times and price."
    : "Your public page is not published yet, so nobody sees this class until you publish it in Settings.";
}

/** "Preview as a parent": the academy's own public page, at its classes. */
export function parentPreviewHref(
  publicUrl: string | null | undefined,
  location: { origin: string; host: string } | null,
): string | null {
  const href = viewPageHref(publicUrl, location);
  return href ? `${href.replace(/#.*$/, "")}#classes` : null;
}

function useBrowserLocation(): { origin: string; host: string } | null {
  const [location, setLocation] = useState<{ origin: string; host: string } | null>(null);
  useEffect(() => {
    setLocation({ origin: window.location.origin, host: window.location.host });
  }, []);
  return location;
}

export function ShowOnPublicPageSwitch({
  checked,
  onChange,
  pagePublished,
  disabled = false,
  testId = "class-show-on-public-page",
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  pagePublished: boolean | undefined;
  disabled?: boolean;
  testId?: string;
}) {
  return (
    <label className="flex min-h-12 items-center justify-between gap-4 rounded-md border border-rally-line px-4 py-2 text-sm font-medium text-rally-ink">
      <span>
        Show on public page
        <span className="block text-xs font-normal text-rally-subtle">
          {showOnPublicPageHint(pagePublished)}
        </span>
      </span>
      <input
        type="checkbox"
        role="switch"
        data-testid={testId}
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        className="size-4 shrink-0 accent-blue-600"
      />
    </label>
  );
}

/**
 * Class page: publish this class and preview what a logged-out parent sees,
 * without leaving the class (S55). Reads and writes the same per-class
 * public fields as Settings > Public page, so both stay in step.
 */
export function ClassPublicPageCard({ sessionId }: { sessionId: string }) {
  const queryClient = useQueryClient();
  const location = useBrowserLocation();
  const settings = useQuery({
    queryKey: queryKeys.admin.publicPage(),
    queryFn: getAdminPublicPageSettings,
  });
  const classes = useQuery({
    queryKey: queryKeys.admin.classPublicProfiles(),
    queryFn: listAdminClassPublicProfiles,
  });
  const row = classes.data?.classes?.find((c) => c.session_id === sessionId);

  const toggle = useMutation({
    mutationFn: (published: boolean) => updateAdminClassPublicFields(sessionId, { published }),
    onSuccess: (saved) =>
      queryClient.setQueryData<{ classes: AdminClassPublicProfileView[] }>(
        queryKeys.admin.classPublicProfiles(),
        (prev) =>
          prev && {
            classes: prev.classes.map((c) => (c.session_id === saved.session_id ? saved : c)),
          },
      ),
    meta: { success: "Public page updated" },
  });

  const pagePublished = settings.data?.published;
  const preview = parentPreviewHref(settings.data?.public_url, location);
  const checked = toggle.isPending ? toggle.variables === true : row?.published === true;

  return (
    <Card p={16} data-testid="class-public-page">
      {classes.isError || settings.isError ? (
        <p role="alert" className="text-sm text-status-red-800">
          Could not load the public page setting.
        </p>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-[16rem] flex-1">
            <ShowOnPublicPageSwitch
              checked={checked}
              disabled={!row || toggle.isPending}
              pagePublished={pagePublished}
              onChange={(next) => toggle.mutate(next)}
            />
          </div>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            {preview && pagePublished ? (
              <a
                href={preview}
                target="_blank"
                rel="noopener noreferrer"
                data-testid="class-preview-as-parent"
                className="inline-flex min-h-11 items-center rounded-md border border-rally-line px-4 font-semibold text-rally-cobalt-700 underline-offset-2 hover:underline"
              >
                Preview as a parent<span className="sr-only"> (opens in a new tab)</span>
              </a>
            ) : null}
            <Link href={SETTINGS_HREF} className="font-medium text-rally-cobalt underline">
              Public page settings
            </Link>
          </div>
        </div>
      )}
    </Card>
  );
}
