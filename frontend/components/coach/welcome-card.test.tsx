import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "@/lib/query/keys";

import { markWelcome, readWelcome, WelcomeCard, welcomeStage } from "./welcome-card";

function stubStorage(impl?: Partial<Storage>) {
  const store = new Map<string, string>();
  vi.stubGlobal("window", {
    localStorage: {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      ...impl,
    },
  });
  return store;
}

afterEach(() => vi.unstubAllGlobals());

describe("welcome progress storage", () => {
  it("is kept per coach and merges steps", () => {
    const store = stubStorage();
    markWelcome("casey", { contact: true });
    markWelcome("casey", { pathway: true });
    expect(readWelcome("casey")).toEqual({ contact: true, pathway: true });
    expect(readWelcome("demo")).toEqual({});
    expect([...store.keys()]).toEqual(["coach-welcome:casey"]);
  });

  it("never throws when storage is blocked", () => {
    stubStorage({
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    });
    expect(() => markWelcome("casey", { hidden: true })).not.toThrow();
    expect(readWelcome("casey")).toEqual({});
    markWelcome(undefined, { hidden: true });
  });
});

describe("WelcomeCard", () => {
  it("draws nothing before the device progress is read (no flash on first paint)", () => {
    const client = new QueryClient();
    client.setQueryData(queryKeys.coach.profile(), {
      user_id: "casey",
      display_name: "Casey",
      email: "casey@example.com",
      phone: null,
    });
    const html = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <WelcomeCard />
      </QueryClientProvider>,
    );
    expect(html).toBe("");
  });
});

describe("the checklist disappears once done or hidden", () => {
  it("shows steps until all three are done, then You're set once, then nothing", () => {
    const store = stubStorage();
    expect(welcomeStage({}, false)).toBe("steps");
    expect(welcomeStage({ contact: true, pathway: true }, false)).toBe("steps");
    // The phone row ticks only from a saved phone number.
    expect(welcomeStage({ contact: true, pathway: true }, true)).toBe("set");
    // Finishing stores hidden, so the next visit reads "none".
    markWelcome("casey", { contact: true, pathway: true, hidden: true });
    expect(welcomeStage(readWelcome("casey"), true)).toBe("none");
    expect(store.size).toBe(1);
  });

  it("is gone after Hide this, done or not", () => {
    expect(welcomeStage({ hidden: true }, false)).toBe("none");
    expect(welcomeStage(null, true)).toBe("none");
  });
});
