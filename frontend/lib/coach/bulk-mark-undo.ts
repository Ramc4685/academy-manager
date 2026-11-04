/**
 * The undo window behind "Mark rest present" (issue #846).
 *
 * Bulk-marking a whole class used to commit on the tap: online it POSTed the
 * bulk endpoint, offline it wrote every mark into the IndexedDB queue. Either
 * way a mis-tap courtside was already a server fact — notifications out,
 * billing synced — and the only repair was a per-row correction.
 *
 * The owner's decision (2026-09-21) is a DELAYED SAVE, not a compensating
 * one: the batch is HELD on the phone for a few seconds while a bottom bar
 * offers Undo, and only then goes down the existing path. Undo inside the
 * window means nothing was ever sent, so there is nothing to reverse.
 *
 * The rule the tests pin is "never lose marks": every way out of the window
 * except Undo commits the batch — the timer elapsing, the app backgrounding,
 * the page unmounting, or a second batch replacing this one — and it commits
 * at most once.
 *
 * Deliberately free of React and of the attendance API: the caller supplies
 * the commit, so this stays a node-vitest unit.
 */

/** How long "Mark rest present" stays undoable before it is sent. */
export const MARK_ALL_UNDO_WINDOW_MS = 5_000;

/** Sends the batch for real — the bulk endpoint online, the queue offline. */
export type BulkMarkCommit = (studentIds: string[]) => void;

export class BulkMarkUndoWindow {
  private timer: ReturnType<typeof setTimeout> | null = null;
  private held: { studentIds: string[]; commit: BulkMarkCommit } | null = null;

  constructor(private readonly windowMs: number = MARK_ALL_UNDO_WINDOW_MS) {}

  /** The students whose marks are waiting out the window (never null). */
  get pendingStudentIds(): readonly string[] {
    return this.held?.studentIds ?? [];
  }

  get isPending(): boolean {
    return this.held !== null;
  }

  /**
   * Hold a batch for the undo window.
   *
   * An already-held batch is flushed, not discarded: a coach who somehow
   * starts a second batch is adding marks, never cancelling the first.
   */
  schedule(studentIds: readonly string[], commit: BulkMarkCommit): void {
    this.flush();
    if (studentIds.length === 0) return;
    // Copy: the caller's array is derived from the roster, which refetches.
    this.held = { studentIds: [...studentIds], commit };
    this.timer = setTimeout(() => {
      this.timer = null;
      this.flush();
    }, this.windowMs);
  }

  /** Send the held batch now (window elapsed, app hidden, page left). */
  flush(): void {
    const held = this.take();
    if (held) held.commit(held.studentIds);
  }

  /**
   * Throw the held batch away — nothing was sent, so no notification and no
   * billing sync ever fired. Returns the ids so the rows can be un-styled;
   * empty once the batch has gone out, which is what makes Undo safe to wire
   * to a button that may be tapped a beat too late.
   */
  cancel(): readonly string[] {
    return this.take()?.studentIds ?? [];
  }

  /** Detach the held batch exactly once, cancelling its timer. */
  private take(): { studentIds: string[]; commit: BulkMarkCommit } | null {
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    const held = this.held;
    this.held = null;
    return held;
  }
}
