/**
 * Pure auth bootstrap state machine.
 *
 * status: "loading" | "anonymous" | "authenticated"
 *
 * The Firebase-configured branch waits for `FIREBASE_RESOLVED` before
 * trusting any `/auth/me` response — that's how we avoid the
 * login-screen flicker on hard refresh.
 */

export function initialAuthState({ firebaseConfigured }) {
  return {
    status: "loading",
    user: null,
    _firebaseConfigured: Boolean(firebaseConfigured),
    _firebaseResolved: false,
    _firebaseUserPresent: false,
  };
}

export function reduceAuthAction(state, action) {
  switch (action.type) {
    case "FIREBASE_RESOLVED": {
      const present = Boolean(action.firebaseUser);
      if (!present) {
        return { status: "anonymous", user: null };
      }
      // User restored — wait for /auth/me to fill in the role/identity.
      return {
        ...state,
        _firebaseResolved: true,
        _firebaseUserPresent: true,
      };
    }
    case "REFRESH_RESULT": {
      if (state._firebaseConfigured && !state._firebaseResolved) {
        // Don't trust the backend's view until Firebase has spoken.
        return state;
      }
      if (action.user) {
        return { status: "authenticated", user: action.user };
      }
      return { status: "anonymous", user: null };
    }
    case "LOGOUT":
      return { status: "anonymous", user: null };
    default:
      return state;
  }
}
