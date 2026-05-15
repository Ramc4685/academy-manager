/**
 * Phase 2.2 — auth bootstrap state machine.
 *
 * Goal: stop the login-screen flicker on hard refresh. When Firebase is
 * configured, the very first `/auth/me` call must wait for Firebase to
 * tell us whether a user is restored or not — otherwise we hit the
 * backend without a token, get 401, and briefly render the login page
 * before flipping back to authed.
 */
import { initialAuthState, reduceAuthAction } from "./authState";

describe("auth state machine", () => {
  test("initial state is 'loading' when Firebase is configured", () => {
    expect(initialAuthState({ firebaseConfigured: true })).toMatchObject({
      status: "loading",
      user: null,
    });
  });

  test("initial state is 'loading' even when Firebase is not configured (until /auth/me settles)", () => {
    expect(initialAuthState({ firebaseConfigured: false })).toMatchObject({
      status: "loading",
      user: null,
    });
  });

  test("non-Firebase mode: REFRESH_RESULT with user sets authenticated", () => {
    const next = reduceAuthAction(
      initialAuthState({ firebaseConfigured: false }),
      { type: "REFRESH_RESULT", user: { id: "u1", email: "a@b.com" } }
    );
    expect(next).toMatchObject({
      status: "authenticated",
      user: { id: "u1", email: "a@b.com" },
    });
  });

  test("non-Firebase mode: REFRESH_RESULT with null sets anonymous", () => {
    const next = reduceAuthAction(
      initialAuthState({ firebaseConfigured: false }),
      { type: "REFRESH_RESULT", user: null }
    );
    expect(next).toMatchObject({ status: "anonymous", user: null });
  });

  test("Firebase mode ignores REFRESH_RESULT until FIREBASE_RESOLVED fires", () => {
    // This is the flicker fix: backend says anon, but Firebase hasn't
    // finished hydrating yet — stay in 'loading'.
    const next = reduceAuthAction(
      initialAuthState({ firebaseConfigured: true }),
      { type: "REFRESH_RESULT", user: null }
    );
    expect(next.status).toBe("loading");
  });

  test("Firebase mode: FIREBASE_RESOLVED with null user → anonymous (no /auth/me call)", () => {
    const next = reduceAuthAction(
      initialAuthState({ firebaseConfigured: true }),
      { type: "FIREBASE_RESOLVED", firebaseUser: null }
    );
    expect(next).toMatchObject({ status: "anonymous", user: null });
  });

  test("Firebase mode: FIREBASE_RESOLVED with user keeps loading until REFRESH_RESULT arrives", () => {
    let state = initialAuthState({ firebaseConfigured: true });
    state = reduceAuthAction(state, {
      type: "FIREBASE_RESOLVED",
      firebaseUser: { uid: "x" },
    });
    expect(state.status).toBe("loading");
    state = reduceAuthAction(state, {
      type: "REFRESH_RESULT",
      user: { id: "u1", email: "a@b.com" },
    });
    expect(state).toMatchObject({
      status: "authenticated",
      user: { id: "u1", email: "a@b.com" },
    });
  });

  test("LOGOUT always returns anonymous", () => {
    const next = reduceAuthAction(
      { status: "authenticated", user: { id: "u1" } },
      { type: "LOGOUT" }
    );
    expect(next).toMatchObject({ status: "anonymous", user: null });
  });
});
