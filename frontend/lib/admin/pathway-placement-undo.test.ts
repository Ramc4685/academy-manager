import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PATHWAY_PLACEMENT_UNDO_WINDOW_MS, PathwayPlacementUndoWindow } from "./pathway-placement-undo";

describe("PathwayPlacementUndoWindow", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  const change = { studentId: "st1", programId: "prog1", levelId: "lvl2" };

  it("does not commit the change on the select itself", () => {
    const commit = vi.fn();
    const held = new PathwayPlacementUndoWindow();

    held.schedule(change, commit);

    expect(commit).not.toHaveBeenCalled();
    expect(held.isPending).toBe(true);
    expect(held.pending).toEqual(change);
  });

  it("commits once when the window elapses", () => {
    const commit = vi.fn();
    const held = new PathwayPlacementUndoWindow();

    held.schedule(change, commit);
    vi.advanceTimersByTime(PATHWAY_PLACEMENT_UNDO_WINDOW_MS - 1);
    expect(commit).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1);
    expect(commit).toHaveBeenCalledTimes(1);
    expect(commit).toHaveBeenCalledWith(change);
    expect(held.isPending).toBe(false);
  });

  it("cancel before the window elapses means commit never fires", () => {
    const commit = vi.fn();
    const held = new PathwayPlacementUndoWindow();

    held.schedule(change, commit);
    expect(held.cancel()).toEqual(change);

    vi.advanceTimersByTime(PATHWAY_PLACEMENT_UNDO_WINDOW_MS * 10);
    expect(commit).not.toHaveBeenCalled();
    expect(held.isPending).toBe(false);
    expect(held.pending).toBeNull();
  });

  it("cancel after the window elapsed cannot un-send the change", () => {
    const commit = vi.fn();
    const held = new PathwayPlacementUndoWindow();

    held.schedule(change, commit);
    vi.advanceTimersByTime(PATHWAY_PLACEMENT_UNDO_WINDOW_MS);
    expect(commit).toHaveBeenCalledTimes(1);

    expect(held.cancel()).toBeNull();
    expect(commit).toHaveBeenCalledTimes(1);
  });

  it("a second select for the same student replaces the first without flushing it", () => {
    const first = vi.fn();
    const second = vi.fn();
    const held = new PathwayPlacementUndoWindow();

    held.schedule({ studentId: "st1", levelId: "lvl1" }, first);
    held.schedule({ studentId: "st1", levelId: "lvl2" }, second);

    // The misclick-and-correct flow: the first (now-superseded) pick must
    // never be sent, silently or otherwise.
    expect(first).not.toHaveBeenCalled();
    expect(second).not.toHaveBeenCalled();
    expect(held.pending).toEqual({ studentId: "st1", levelId: "lvl2" });

    vi.advanceTimersByTime(PATHWAY_PLACEMENT_UNDO_WINDOW_MS);
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
    expect(second).toHaveBeenCalledWith({ studentId: "st1", levelId: "lvl2" });
  });

  it("a select for a different student flushes the first rather than dropping it", () => {
    const first = vi.fn();
    const second = vi.fn();
    const held = new PathwayPlacementUndoWindow();

    held.schedule({ studentId: "st1", levelId: "lvl1" }, first);
    held.schedule({ studentId: "st2", levelId: "lvl2" }, second);

    expect(first).toHaveBeenCalledTimes(1);
    expect(first).toHaveBeenCalledWith({ studentId: "st1", levelId: "lvl1" });
    expect(second).not.toHaveBeenCalled();

    vi.advanceTimersByTime(PATHWAY_PLACEMENT_UNDO_WINDOW_MS);
    expect(second).toHaveBeenCalledTimes(1);
  });

  it("flush sends the held change immediately and only once", () => {
    const commit = vi.fn();
    const held = new PathwayPlacementUndoWindow();

    held.schedule(change, commit);
    held.flush();
    expect(commit).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(PATHWAY_PLACEMENT_UNDO_WINDOW_MS * 10);
    held.flush();
    expect(commit).toHaveBeenCalledTimes(1);
  });

  it("honours a custom window length", () => {
    const commit = vi.fn();
    const held = new PathwayPlacementUndoWindow(100);

    held.schedule(change, commit);
    vi.advanceTimersByTime(99);
    expect(commit).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(commit).toHaveBeenCalledTimes(1);
  });
});
