"use client";

/**
 * People CRM Pipeline board (engineering-spec §3.4, roadmap L3b).
 *
 * `/admin/families?view=pipeline`: five columns (Inquiry, Trial booked,
 * Trial done, Registered, Enrolled) from `GET /admin/crm/pipeline`, which
 * merges `crm_contacts` leads with the family index's trial and lead-only
 * families. On a phone the board is a stage switcher over one list
 * (`?stage=` picks the first stage shown).
 *
 * Moves are never drag-only: each movable card has a "Move to…" button that
 * opens a small panel of radio options and an explicit "Move" button, so
 * nothing commits on change (WCAG 3.2.2). After a card leaves its column,
 * focus goes to the card that took its place, else the column heading
 * (WCAG 2.4.3). Family cards are read-only here: their stage is a system
 * write made on the family record or the Inbox.
 *
 * Quick add lead writes `crm_contacts` through the existing CreateContact
 * (`POST /admin/crm/contacts`) and shows the duplicate warning. No money on
 * the board.
 */
import { useEffect, useId, useMemo, useRef, useState, type FormEvent } from "react";
import type { Route } from "next";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  PIPELINE_COLUMNS,
  PIPELINE_COLUMN_LABELS,
  SOURCE_LABELS,
  fetchPipelineBoard,
  focusAfterLeaving,
  groupByColumn,
  isPipelineColumn,
  movePipelineCard,
  quickAddLead,
  type PipelineCard,
  type PipelineColumn,
  type QuickAddSource,
} from "@/lib/api/admin-crm-pipeline";
import type { ApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/query/keys";
import { useIsPhone } from "@/lib/use-is-phone";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { ErrorNotice } from "@/components/ds/error-notice";
import { FormField } from "@/components/ds/form-field";
import { useToast } from "@/components/ds/toast";
import {
  PossibleDuplicateNotice,
  usePossibleDuplicateCheck,
} from "@/components/admin/possible-duplicate-notice";

const MOVE_REFUSALS: Record<string, string> = {
  stage_skip: "A card moves forward one column at a time.",
  contact_enrolled: "This lead is enrolled, so its column is the system's.",
  needs_system_write: "Enrolling happens when the family registers, not on the board.",
  changed: "Someone else moved this card just now. The board has been refreshed.",
};

const WARNING_COPY: Record<string, string> = {
  families_unavailable:
    "Families could not be read just now, so trial and lead-only families are missing from the board.",
};

const INPUT =
  "h-10 w-full rounded-md border border-neutral-200 bg-white px-2 font-body text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15";

function headingId(column: PipelineColumn): string {
  return `pipeline-column-${column}`;
}

function cardDomId(cardId: string): string {
  return `pipeline-card-${cardId.replace(/[^A-Za-z0-9_-]/g, "-")}`;
}

export function PipelineBoard({ initialStage }: { initialStage?: string | null }) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const isPhone = useIsPhone();
  const [stage, setStage] = useState<PipelineColumn>(
    isPipelineColumn(initialStage) ? initialStage : "inquiry",
  );
  const [pendingFocus, setPendingFocus] = useState<string | null>(null);

  const boardQuery = useQuery({
    queryKey: queryKeys.admin.pipelineBoard(),
    queryFn: fetchPipelineBoard,
    retry: false,
  });
  const groups = useMemo(() => groupByColumn(boardQuery.data?.cards ?? []), [boardQuery.data]);

  // Focus lands once the refreshed board has rendered (WCAG 2.4.3).
  useEffect(() => {
    if (!pendingFocus || boardQuery.isFetching) return;
    const target = document.getElementById(pendingFocus);
    if (target) {
      target.focus();
      setPendingFocus(null);
    }
  }, [pendingFocus, boardQuery.isFetching, groups]);

  const refresh = () => queryClient.invalidateQueries({ queryKey: queryKeys.admin.pipelineBoard() });

  const onMoved = (card: PipelineCard, to: PipelineColumn) => {
    const next = focusAfterLeaving(groups[card.column], card.card_id);
    setPendingFocus(next ? cardDomId(next) : headingId(card.column));
    toast({ kind: "success", title: `Moved to ${PIPELINE_COLUMN_LABELS[to]}` });
    void refresh();
  };

  const onAdded = (card: PipelineCard) => {
    if (isPhone) setStage(card.column);
    setPendingFocus(cardDomId(card.card_id));
    toast({ kind: "success", title: "Lead added" });
    void refresh();
  };

  const columns = isPhone ? [stage] : PIPELINE_COLUMNS;

  return (
    <div className="flex flex-col gap-4" data-testid="admin-pipeline">
      <p className="text-sm text-rally-muted">
        Pipeline · everyone who asked about classes, from first inquiry to enrolled
      </p>

      <QuickAddLead onAdded={onAdded} />

      {(boardQuery.data?.warnings ?? []).map((code) => (
        <p
          key={code}
          role="status"
          data-testid={`admin-pipeline-warning-${code}`}
          className="rounded-md bg-status-amber-50 px-4 py-2 text-sm text-status-amber-800"
        >
          {WARNING_COPY[code] ?? "Part of the board could not be read just now."}
        </p>
      ))}

      {boardQuery.isLoading ? (
        <div className="p-8 text-center text-sm text-rally-muted">Loading…</div>
      ) : boardQuery.isError ? (
        <ErrorNotice
          testId="admin-pipeline-error"
          message="Could not load the pipeline. The board is unknown, not empty."
          onRetry={() => void boardQuery.refetch()}
          retrying={boardQuery.isFetching}
        />
      ) : (
        <>
          {isPhone && (
            <div
              role="group"
              aria-label="Pipeline stage"
              data-testid="admin-pipeline-stage-switcher"
              className="flex gap-2 overflow-x-auto pb-1"
            >
              {PIPELINE_COLUMNS.map((column) => (
                <button
                  key={column}
                  type="button"
                  aria-pressed={stage === column}
                  data-testid={`admin-pipeline-stage-${column}`}
                  onClick={() => setStage(column)}
                  className={`shrink-0 rounded-full border px-3 py-1.5 text-sm font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rally-cobalt-600 ${
                    stage === column
                      ? "border-rally-cobalt-600 bg-rally-cobalt-600 text-white"
                      : "border-rally-line bg-white text-rally-base"
                  }`}
                >
                  {PIPELINE_COLUMN_LABELS[column]} ({groups[column].length})
                </button>
              ))}
            </div>
          )}
          <div
            className={isPhone ? "flex flex-col gap-3" : "grid grid-cols-5 gap-3"}
            data-testid="admin-pipeline-board"
          >
            {columns.map((column) => (
              <section
                key={column}
                aria-labelledby={headingId(column)}
                data-testid={`admin-pipeline-column-${column}`}
                className="flex min-w-0 flex-col gap-2 rounded-lg bg-rally-paper p-2"
              >
                <h2
                  id={headingId(column)}
                  tabIndex={-1}
                  className="px-1 text-sm font-semibold text-rally-base focus:outline-none focus-visible:outline-2 focus-visible:outline-rally-cobalt-600"
                >
                  {PIPELINE_COLUMN_LABELS[column]}{" "}
                  <span className="font-normal text-rally-muted">({groups[column].length})</span>
                </h2>
                {groups[column].length === 0 ? (
                  <p className="px-1 py-3 text-xs text-rally-muted">Nobody here.</p>
                ) : (
                  <ul className="flex flex-col gap-2">
                    {groups[column].map((card) => (
                      <li key={card.card_id}>
                        <PipelineCardView card={card} onMoved={onMoved} onRefresh={refresh} />
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function PipelineCardView({
  card,
  onMoved,
  onRefresh,
}: {
  card: PipelineCard;
  onMoved: (card: PipelineCard, to: PipelineColumn) => void;
  onRefresh: () => void;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const triggerId = `${cardDomId(card.card_id)}-move`;
  const childLine = [card.child, card.child_age ? `age ${card.child_age}` : null]
    .filter(Boolean)
    .join(", ");
  const sourceLabel = card.source ? (SOURCE_LABELS[card.source] ?? "Other") : null;

  const close = () => {
    setOpen(false);
    window.setTimeout(() => document.getElementById(triggerId)?.focus(), 0);
  };

  return (
    <article
      id={cardDomId(card.card_id)}
      tabIndex={-1}
      data-testid={`admin-pipeline-card-${card.card_id}`}
      aria-label={card.name}
      className="rounded-md border border-rally-line bg-white p-3 text-sm focus:outline-none focus-visible:outline-2 focus-visible:outline-rally-cobalt-600"
    >
      <p className="font-semibold text-rally-base">
        {card.family_id ? (
          <Link
            href={`/admin/families/${encodeURIComponent(card.family_id)}` as Route}
            className="underline-offset-2 hover:underline"
          >
            {card.name}
          </Link>
        ) : (
          card.name
        )}
      </p>
      {childLine && <p className="text-rally-muted">{childLine}</p>}
      <p className="mt-1 text-xs text-rally-subtle">
        {[
          sourceLabel,
          card.kind === "family" ? "Family" : null,
          card.lead_age_days != null
            ? card.lead_age_days === 0
              ? "today"
              : `${card.lead_age_days} ${card.lead_age_days === 1 ? "day" : "days"}`
            : null,
        ]
          .filter(Boolean)
          .join(" · ")}
      </p>
      {card.override_column && (
        <p className="mt-1 text-xs text-rally-subtle" data-testid="admin-pipeline-card-moved">
          Moved by staff
          {card.override_set_at ? ` on ${new Date(card.override_set_at).toLocaleDateString()}` : ""}
        </p>
      )}
      {card.move_targets.length > 0 && card.contact_id && (
        <div className="mt-2">
          <Button
            id={triggerId}
            size="sm"
            variant="secondary"
            aria-expanded={open}
            aria-controls={panelId}
            data-testid={`admin-pipeline-move-${card.card_id}`}
            onClick={() => setOpen((value) => !value)}
          >
            Move to…
          </Button>
          {open && (
            <MovePanel
              id={panelId}
              card={card}
              onCancel={close}
              onMoved={(to) => {
                setOpen(false);
                onMoved(card, to);
              }}
              onRefresh={onRefresh}
            />
          )}
        </div>
      )}
    </article>
  );
}

function MovePanel({
  id,
  card,
  onCancel,
  onMoved,
  onRefresh,
}: {
  id: string;
  card: PipelineCard;
  onCancel: () => void;
  onMoved: (to: PipelineColumn) => void;
  onRefresh: () => void;
}) {
  const targets = card.move_targets.filter(
    (target): target is Exclude<PipelineColumn, "enrolled"> => target !== "enrolled",
  );
  const [choice, setChoice] = useState<Exclude<PipelineColumn, "enrolled"> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const firstRef = useRef<HTMLInputElement>(null);
  const name = useId();

  useEffect(() => {
    firstRef.current?.focus();
  }, []);

  const move = useMutation({
    mutationFn: (to: Exclude<PipelineColumn, "enrolled">) =>
      movePipelineCard(card.contact_id as string, to),
    onSuccess: (_result, to) => onMoved(to),
    onError: (err: ApiError) => {
      const reason = (err.details?.reason as string | undefined) ?? "";
      setError(MOVE_REFUSALS[reason] ?? "Could not move this card. Try again.");
      if (reason === "changed") onRefresh();
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (choice) move.mutate(choice);
  };

  return (
    <form
      id={id}
      onSubmit={submit}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.stopPropagation();
          onCancel();
        }
      }}
      className="mt-2 rounded-md border border-rally-line bg-rally-paper p-2"
      data-testid={`admin-pipeline-move-panel-${card.card_id}`}
    >
      <fieldset>
        <legend className="mb-1 text-xs font-semibold text-rally-muted">
          Move {card.name} to
        </legend>
        {targets.map((target, index) => (
          <label key={target} className="flex items-center gap-2 py-1 text-sm">
            <input
              ref={index === 0 ? firstRef : undefined}
              type="radio"
              name={name}
              value={target}
              checked={choice === target}
              onChange={() => setChoice(target)}
              data-testid={`admin-pipeline-move-option-${target}`}
            />
            {PIPELINE_COLUMN_LABELS[target]}
          </label>
        ))}
      </fieldset>
      {error && (
        <p role="alert" className="mt-1 text-xs font-medium text-status-red-800">
          {error}
        </p>
      )}
      <div className="mt-2 flex gap-2">
        <Button
          type="submit"
          size="sm"
          disabled={!choice || move.isPending}
          data-testid={`admin-pipeline-move-confirm-${card.card_id}`}
        >
          {move.isPending ? "Moving…" : "Move"}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

function QuickAddLead({ onAdded }: { onAdded: (card: PipelineCard) => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [child, setChild] = useState("");
  const [childAge, setChildAge] = useState("");
  const [source, setSource] = useState<QuickAddSource>("whatsapp_or_phone");
  const [error, setError] = useState<string | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const duplicates = usePossibleDuplicateCheck();

  useEffect(() => {
    if (open) nameRef.current?.focus();
  }, [open]);

  const reset = () => {
    setName("");
    setPhone("");
    setEmail("");
    setChild("");
    setChildAge("");
    setSource("whatsapp_or_phone");
    setError(null);
    duplicates.reset();
  };

  const add = useMutation({
    mutationFn: () =>
      quickAddLead({
        name: name.trim(),
        phone: phone.trim() || null,
        email: email.trim() || null,
        child_name: child.trim() || null,
        child_age: childAge.trim() || null,
        source,
      }),
    onSuccess: (card) => {
      reset();
      setOpen(false);
      onAdded(card);
    },
    onError: (err: ApiError) => {
      const field = err.details?.field as string | undefined;
      setError(
        err.code === "Crm.InvalidContact" && field
          ? `Check the ${field.replace(/_/g, " ").replace("phone digits", "phone")}. A phone or an email is needed.`
          : "Could not add this lead. Try again.",
      );
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) {
      setError("Enter a name.");
      return;
    }
    if (!phone.trim() && !email.trim()) {
      setError("Enter a phone number or an email.");
      return;
    }
    setError(null);
    add.mutate();
  };

  const probe = () => duplicates.check({ phone, email, name });

  if (!open) {
    return (
      <div>
        <Button
          id="admin-pipeline-add-lead"
          onClick={() => setOpen(true)}
          aria-expanded={false}
          data-testid="admin-pipeline-add-lead"
        >
          Add lead
        </Button>
      </div>
    );
  }

  return (
    <Card p={16}>
      <form onSubmit={submit} data-testid="admin-pipeline-add-lead-form" noValidate>
        <h2 className="mb-3 text-sm font-semibold text-rally-base">Add lead</h2>
        <div className="grid gap-3 sm:grid-cols-3">
          <FormField label="Name" htmlFor="pipeline-lead-name" required>
            <input
              ref={nameRef}
              id="pipeline-lead-name"
              className={INPUT}
              value={name}
              maxLength={120}
              onChange={(e) => setName(e.target.value)}
              autoComplete="off"
            />
          </FormField>
          <FormField label="Phone" htmlFor="pipeline-lead-phone">
            <input
              id="pipeline-lead-phone"
              className={INPUT}
              type="tel"
              value={phone}
              maxLength={40}
              onChange={(e) => setPhone(e.target.value)}
              onBlur={probe}
              autoComplete="off"
            />
          </FormField>
          <FormField label="Email" htmlFor="pipeline-lead-email">
            <input
              id="pipeline-lead-email"
              className={INPUT}
              type="email"
              value={email}
              maxLength={254}
              onChange={(e) => setEmail(e.target.value)}
              onBlur={probe}
              autoComplete="off"
            />
          </FormField>
          <FormField label="Child" htmlFor="pipeline-lead-child">
            <input
              id="pipeline-lead-child"
              className={INPUT}
              value={child}
              maxLength={120}
              onChange={(e) => setChild(e.target.value)}
              autoComplete="off"
            />
          </FormField>
          <FormField label="Child's age" htmlFor="pipeline-lead-age">
            <input
              id="pipeline-lead-age"
              className={INPUT}
              value={childAge}
              maxLength={20}
              onChange={(e) => setChildAge(e.target.value)}
              autoComplete="off"
            />
          </FormField>
          <FormField label="Source" htmlFor="pipeline-lead-source">
            <select
              id="pipeline-lead-source"
              className={INPUT}
              value={source}
              onChange={(e) => setSource(e.target.value as QuickAddSource)}
            >
              <option value="whatsapp_or_phone">WhatsApp or phone</option>
              <option value="referral">Referral</option>
              <option value="other">Other</option>
            </select>
          </FormField>
        </div>
        <div className="mt-3">
          <PossibleDuplicateNotice
            matches={duplicates.matches}
            testId="admin-pipeline-add-lead-duplicate"
          />
        </div>
        {error && (
          <p role="alert" className="mt-2 text-sm font-medium text-status-red-800">
            {error}
          </p>
        )}
        <div className="mt-3 flex gap-2">
          <Button type="submit" disabled={add.isPending} data-testid="admin-pipeline-add-lead-save">
            {add.isPending ? "Adding…" : "Add lead"}
          </Button>
          <Button
            type="button"
            variant="ghost"
            onClick={() => {
              reset();
              setOpen(false);
              window.setTimeout(() => document.getElementById("admin-pipeline-add-lead")?.focus(), 0);
            }}
          >
            Cancel
          </Button>
        </div>
      </form>
    </Card>
  );
}
