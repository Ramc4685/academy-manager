import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BulkMarkUndoWindow, MARK_ALL_UNDO_WINDOW_MS } from "./bulk-mark-undo";

describe("BulkMarkUndoWindow", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not commit the batch on the tap itself", () => {
    const commit = vi.fn();
    const held = new BulkMarkUndoWindow();

    held.schedule(["st1", "st2"], commit);

    // The whole point of #846: nothing reaches the server (or the offline
    // queue) while the coach can still undo.
    expect(commit).not.toHaveBeenCalled();
    expect(held.isPending).toBe(true);
    expect(held.pendingStudentIds).toEqual(["st1", "st2"]);
  });

  it("commits once when the window elapses", () => {
    const commit = vi.fn();
    const held = new BulkMarkUndoWindow();

    held.schedule(["st1", "st2"], commit);
    vi.advanceTimersByTime(MARK_ALL_UNDO_WINDOW_MS - 1);
    expect(commit).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1);
    expect(commit).toHaveBeenCalledTimes(1);
    expect(commit).toHaveBeenCalledWith(["st1", "st2"]);
    expect(held.isPending).toBe(false);
  });

  it("cancel keeps the batch from ever being committed", () => {
    const commit = vi.fn();
    const held = new BulkMarkUndoWindow();

    held.schedule(["st1", "st2"], commit);
    expect(held.cancel()).toEqual(["st1", "st2"]);

    vi.advanceTimersByTime(MARK_ALL_UNDO_WINDOW_MS * 10);
    expect(commit).not.toHaveBeenCalled();
    expect(held.isPending).toBe(false);
    expect(held.pendingStudentIds).toEqual([]);
  });

  it("cancel after the window elapsed cannot un-send the batch", () => {
    const commit = vi.fn();
    const held = new BulkMarkUndoWindow();

    held.schedule(["st1"], commit);
    vi.advanceTimersByTime(MARK_ALL_UNDO_WINDOW_MS);
    expect(commit).toHaveBeenCalledTimes(1);

    expect(held.cancel()).toEqual([]);
    expect(commit).toHaveBeenCalledTimes(1);
  });

  it("flush sends the held batch immediately and only once", () => {
    const commit = vi.fn();
    const held = new BulkMarkUndoWindow();

    held.schedule(["st1", "st2"], commit);
    held.flush();
    expect(commit).toHaveBeenCalledTimes(1);
    expect(commit).toHaveBeenCalledWith(["st1", "st2"]);

    // The pending timer must not fire a second copy of the same batch —
    // a phone that backgrounds and comes back would double-mark the class.
    vi.advanceTimersByTime(MARK_ALL_UNDO_WINDOW_MS * 10);
    held.flush();
    expect(commit).toHaveBeenCalledTimes(1);
  });

  it("flush with nothing held is a no-op", () => {
    const commit = vi.fn();
    const held = new BulkMarkUndoWindow();

    held.flush();
    held.schedule(["st1"], commit);
    held.cancel();
    held.flush();

    expect(commit).not.toHaveBeenCalled();
  });

  it("a second batch flushes the first rather than dropping it", () => {
    const first = vi.fn();
    const second = vi.fn();
    const held = new BulkMarkUndoWindow();

    held.schedule(["st1"], first);
    held.schedule(["st2"], second);

    // Marks are never lost: replacing the held batch sends the old one.
    expect(first).toHaveBeenCalledTimes(1);
    expect(first).toHaveBeenCalledWith(["st1"]);
    expect(second).not.toHaveBeenCalled();

    vi.advanceTimersByTime(MARK_ALL_UNDO_WINDOW_MS);
    expect(second).toHaveBeenCalledTimes(1);
  });

  it("scheduling an empty batch holds nothing", () => {
    const commit = vi.fn();
    const held = new BulkMarkUndoWindow();

    held.schedule([], commit);
    expect(held.isPending).toBe(false);

    vi.advanceTimersByTime(MARK_ALL_UNDO_WINDOW_MS);
    expect(commit).not.toHaveBeenCalled();
  });

  it("copies the ids so a later roster change cannot rewrite the held batch", () => {
    const commit = vi.fn();
    const held = new BulkMarkUndoWindow();
    const ids = ["st1"];

    held.schedule(ids, commit);
    ids.push("st2");

    vi.advanceTimersByTime(MARK_ALL_UNDO_WINDOW_MS);
    expect(commit).toHaveBeenCalledWith(["st1"]);
  });

  it("honours a custom window length", () => {
    const commit = vi.fn();
    const held = new BulkMarkUndoWindow(100);

    held.schedule(["st1"], commit);
    vi.advanceTimersByTime(99);
    expect(commit).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(commit).toHaveBeenCalledTimes(1);
  });
});
