/**
 * The undo window behind changing a student's pathway level from the session
 * roster (#859 remainder).
 *
 * The `LevelSelect` in `RosterPanel.tsx` used to fire the placement mutation
 * straight from `onChange` — a misclick on the dropdown silently committed a
 * new pathway placement with no confirm step and no way back short of
 * picking the old level again (and even that re-fires the same
 * fire-and-forget mutation).
 *
 * This follows the same DELAYED SAVE shape `bulk-mark-undo.ts` established
 * for #846: the change is HELD for a few seconds while the UI offers Undo,
 * and only then is the actual `placeStudentInLevel` call made. Undo inside
 * the window means nothing was ever sent, so there is nothing to reverse.
 *
 * Deliberately free of React and of the placement API: the caller supplies
 * the commit, so this stays a node-vitest unit.
 */

/** How long a pathway placement change stays undoable before it is sent. */
export const PATHWAY_PLACEMENT_UNDO_WINDOW_MS = 5_000;

export interface PathwayPlacementChange {
  studentId: string;
  programId?: string | null;
  levelId: string;
}

/** Sends the placement for real — the `placeStudentInLevel` API call. */
export type PathwayPlacementCommit = (change: PathwayPlacementChange) => void;

export class PathwayPlacementUndoWindow {
  private timer: ReturnType<typeof setTimeout> | null = null;
  private held: { change: PathwayPlacementChange; commit: PathwayPlacementCommit } | null = null;

  constructor(private readonly windowMs: number = PATHWAY_PLACEMENT_UNDO_WINDOW_MS) {}

  /** The change waiting out the window, or null once sent or undone. */
  get pending(): PathwayPlacementChange | null {
    return this.held?.change ?? null;
  }

  get isPending(): boolean {
    return this.held !== null;
  }

  /**
   * Hold a placement change for the undo window.
   *
   * A re-pick for the SAME student replaces the held change outright — this
   * is a single-valued field, so a same-student re-pick supersedes the prior
   * pick rather than confirming it. Flushing here (as an earlier version
   * did) would silently commit the now-superseded first pick with no
   * confirm/undo, defeating #859's "no silent save" requirement for the
   * realistic misclick-then-correct flow. A pick for a DIFFERENT student is
   * unrelated and flushes the old one, following `BulkMarkUndoWindow`'s
   * "never lose marks" rule for its accumulating marks.
   */
  schedule(change: PathwayPlacementChange, commit: PathwayPlacementCommit): void {
    if (this.held && this.held.change.studentId === change.studentId) {
      this.cancel();
    } else {
      this.flush();
    }
    this.held = { change: { ...change }, commit };
    this.timer = setTimeout(() => {
      this.timer = null;
      this.flush();
    }, this.windowMs);
  }

  /** Send the held change now (window elapsed, admin navigated away). */
  flush(): void {
    const held = this.take();
    if (held) held.commit(held.change);
  }

  /**
   * Throw the held change away — nothing was sent, so no placement API call
   * ever fired. Returns the change so the row can be reverted to its prior
   * level; null once the change has gone out, which is what makes Undo safe
   * to wire to a button that may be tapped a beat too late.
   */
  cancel(): PathwayPlacementChange | null {
    return this.take()?.change ?? null;
  }

  /** Detach the held change exactly once, cancelling its timer. */
  private take(): { change: PathwayPlacementChange; commit: PathwayPlacementCommit } | null {
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    const held = this.held;
    this.held = null;
    return held;
  }
}
