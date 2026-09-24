import { describe, expect, it, vi } from "vitest";

import { overflowEdges, watchStripContent } from "./overflow-cue";

describe("overflowEdges", () => {
  it("reports nothing when the strip fits", () => {
    expect(overflowEdges({ scrollLeft: 0, clientWidth: 400, scrollWidth: 400 })).toEqual({
      left: false,
      right: false,
    });
  });

  it("shows the right cue at the start of an overflowing strip", () => {
    expect(overflowEdges({ scrollLeft: 0, clientWidth: 400, scrollWidth: 900 })).toEqual({
      left: false,
      right: true,
    });
  });

  it("shows both cues mid-scroll and only the left one at the end", () => {
    expect(overflowEdges({ scrollLeft: 200, clientWidth: 400, scrollWidth: 900 })).toEqual({
      left: true,
      right: true,
    });
    expect(overflowEdges({ scrollLeft: 500, clientWidth: 400, scrollWidth: 900 })).toEqual({
      left: true,
      right: false,
    });
  });

  it("ignores sub-pixel slack", () => {
    expect(overflowEdges({ scrollLeft: 0.5, clientWidth: 400, scrollWidth: 400.6 })).toEqual({
      left: false,
      right: false,
    });
  });
});

/** Fakes mirroring the DOM observer contracts the hook relies on. */
function fakeObservers() {
  const resizers: FakeResize[] = [];
  const mutators: FakeMutation[] = [];
  class FakeResize {
    observed = new Set<unknown>();
    constructor(public cb: () => void) {
      resizers.push(this);
    }
    observe(target: unknown) {
      this.observed.add(target);
    }
    unobserve(target: unknown) {
      this.observed.delete(target);
    }
    disconnect() {
      this.observed.clear();
    }
    fire() {
      this.cb();
    }
  }
  class FakeMutation {
    target: unknown = null;
    constructor(public cb: () => void) {
      mutators.push(this);
    }
    observe(target: unknown) {
      this.target = target;
    }
    disconnect() {
      this.target = null;
    }
    takeRecords() {
      return [];
    }
    fire() {
      this.cb();
    }
  }
  return {
    resizers,
    mutators,
    ctors: {
      ResizeObserver: FakeResize as unknown as typeof ResizeObserver,
      MutationObserver: FakeMutation as unknown as typeof MutationObserver,
    },
  };
}

describe("watchStripContent", () => {
  it("observes the strip and every chip, not just the first", () => {
    const chips = [{ id: "a" }, { id: "b" }, { id: "c" }];
    const el = { children: chips } as unknown as Element;
    const { resizers, ctors } = fakeObservers();
    watchStripContent(el, () => {}, ctors);
    expect(resizers[0].observed.has(el)).toBe(true);
    for (const chip of chips) expect(resizers[0].observed.has(chip)).toBe(true);
  });

  it("re-observes chips added later and re-syncs on add/remove", () => {
    const chips: object[] = [{ id: "a" }];
    const el = { children: chips } as unknown as Element;
    const onChange = vi.fn();
    const { resizers, mutators, ctors } = fakeObservers();
    watchStripContent(el, onChange, ctors);
    const late = { id: "late" };
    chips.push(late);
    mutators[0].fire();
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(resizers[0].observed.has(late)).toBe(true);
    // A later chip's own width change (count badge filling in) re-syncs.
    resizers[0].fire();
    expect(onChange).toHaveBeenCalledTimes(2);
  });

  it("disconnects both observers on cleanup", () => {
    const el = { children: [{ id: "a" }] } as unknown as Element;
    const { resizers, mutators, ctors } = fakeObservers();
    const unwatch = watchStripContent(el, () => {}, ctors);
    unwatch();
    expect(resizers[0].observed.size).toBe(0);
    expect(mutators[0].target).toBeNull();
  });

  it("is a no-op without observer support", () => {
    const el = { children: [] } as unknown as Element;
    expect(() => watchStripContent(el, () => {}, {})()).not.toThrow();
  });
});
