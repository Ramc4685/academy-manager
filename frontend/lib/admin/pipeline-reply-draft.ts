/**
 * B3: the AI-drafted reply panel on a pipeline card. Pure helpers, pinned by
 * vitest: the draft -> editable form mapping and the error copy per status
 * and code (backend/v2/interfaces/admin/ai_pipeline_routes.py).
 */
import type { ApiError } from "@/lib/api/client";
import type { ReplyDraft } from "@/lib/api/admin-crm-pipeline";

export interface ReplyForm {
  subject: string;
  body: string;
  /** The facts the draft relies on, shown as a hint list. */
  keyPoints: string[];
}

export function draftToForm(draft: ReplyDraft): ReplyForm {
  return {
    subject: draft.subject.trim(),
    body: draft.body.trim(),
    keyPoints: draft.key_points.map((p) => p.trim()).filter(Boolean),
  };
}

export const REPLY_ERROR_COPY = {
  disabled: "AI drafting is not enabled for this academy yet",
  notEntitled: "AI replies are part of the Growth plan",
  cap: "This academy has used its AI drafts for the month",
  unreadable: "The draft could not be read, try again",
  draftFailed: "Could not draft a reply. Try again.",
  sendFailed: "Could not send the reply. Try again.",
} as const;

/** A plain sentence for a failed draft or send; never a crash. */
export function replyErrorMessage(
  err: Pick<ApiError, "status" | "code" | "message"> | null | undefined,
  action: "draft" | "send",
): string {
  const fallback = action === "draft" ? REPLY_ERROR_COPY.draftFailed : REPLY_ERROR_COPY.sendFailed;
  if (!err) return fallback;
  if (err.status === 503) return REPLY_ERROR_COPY.disabled;
  if (err.status === 403 && err.code === "Ai.NotEntitled") return REPLY_ERROR_COPY.notEntitled;
  if (err.status === 429) return REPLY_ERROR_COPY.cap;
  if (err.status === 502 && action === "draft") return REPLY_ERROR_COPY.unreadable;
  if (err.status === 409) return err.message || fallback;
  return fallback;
}
