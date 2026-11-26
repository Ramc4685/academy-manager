"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ds/button";
import { ConfirmActionDialog } from "@/components/ds/confirm-action-dialog";
import { getCalendarFeedLink, resetCalendarFeedLink } from "@/lib/api/parent";
import { nativePlatform } from "@/lib/auth/native-sign-in";
import { queryKeys } from "@/lib/query/keys";

/** Subscribe URLs for each calendar app, from the parent's https feed link. */
export function calendarSubscribeLinks(feedUrl: string, calendarName: string) {
  const webcal = feedUrl.replace(/^https?:\/\//, "webcal://");
  return {
    apple: webcal,
    google: `https://calendar.google.com/calendar/r?cid=${encodeURIComponent(webcal)}`,
    outlook: `https://outlook.live.com/calendar/0/addfromweb?url=${encodeURIComponent(
      feedUrl,
    )}&name=${encodeURIComponent(calendarName)}`,
  };
}

/**
 * "Add to my calendar": a live subscription, not a one-time download, so a
 * class the academy calls off later is crossed out on the parent's phone by
 * itself. Hidden when the deployment has no calendar link (the API 404s).
 */
export function AddToCalendar({ academyName }: { academyName: string }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [confirmingReset, setConfirmingReset] = useState(false);
  const link = useQuery({
    queryKey: [...queryKeys.parent.calendar(), "feed-link"],
    queryFn: getCalendarFeedLink,
    retry: false,
    staleTime: Infinity,
  });
  const reset = useMutation({
    mutationFn: resetCalendarFeedLink,
    onSuccess: (data) => {
      queryClient.setQueryData([...queryKeys.parent.calendar(), "feed-link"], data);
      setCopied(false);
      setConfirmingReset(false);
    },
  });

  if (!link.data?.url) return null;
  const url = link.data.url;
  const links = calendarSubscribeLinks(url, `${academyName} classes`);

  async function copy() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  if (!open) {
    return (
      <Button type="button" variant="secondary" onClick={() => setOpen(true)} data-testid="add-to-calendar">
        Add to my calendar
      </Button>
    );
  }

  const linkClass =
    "block w-full rounded-lg border border-rally-line bg-white px-3 py-2 text-center text-sm font-semibold text-rally-ink hover:bg-rally-paper";

  return (
    <div className="rounded-2xl border border-rally-line bg-white p-4" data-testid="add-to-calendar-panel">
      <h2 className="text-[15px] font-bold text-rally-ink">Keep classes in your calendar</h2>
      <p className="mt-1 text-sm text-rally-muted">
        Covers all your children. When the academy changes a date, your calendar updates by
        itself. iPhone usually picks it up within an hour; Google can take up to a day, so the
        academy still emails same-day changes.
      </p>
      <div className="mt-3 grid gap-2 sm:grid-cols-3">
        {/* The Android app has nothing that opens webcal: links. */}
        {nativePlatform() !== "android" && (
          <a className={linkClass} href={links.apple}>
            iPhone / Apple Calendar
          </a>
        )}
        <a className={linkClass} href={links.google} target="_blank" rel="noopener noreferrer">
          Google Calendar
        </a>
        <a className={linkClass} href={links.outlook} target="_blank" rel="noopener noreferrer">
          Outlook
        </a>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button type="button" variant="secondary" size="sm" onClick={copy}>
          {copied ? "Copied" : "Copy link"}
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={() => setConfirmingReset(true)} disabled={reset.isPending}>
          Reset link
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={() => setOpen(false)}>
          Close
        </Button>
      </div>
      <p className="mt-2 text-xs text-rally-subtle">
        This link is private to your family. Reset it if you shared it by mistake.
      </p>
      <ConfirmActionDialog
        open={confirmingReset}
        onOpenChange={setConfirmingReset}
        overline="Calendar link"
        title="Make a new link?"
        consequence="Calendars using the old link stop updating, so add the new one again."
        confirmLabel="Make a new link"
        cancelLabel="Keep the old link"
        pending={reset.isPending}
        onConfirm={() => reset.mutate()}
      />
    </div>
  );
}
