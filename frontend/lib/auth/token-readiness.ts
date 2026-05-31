export interface IdTokenUser {
  getIdToken(): Promise<string>;
}

export interface AuthState<User extends IdTokenUser> {
  currentUser: User | null;
}

export type AuthStateSubscriber<User extends IdTokenUser> = (
  callback: (user: User | null) => void
) => () => void;

const DEFAULT_AUTH_READY_TIMEOUT_MS = 3000;

export async function getReadyIdToken<User extends IdTokenUser>(
  authState: AuthState<User>,
  subscribe: AuthStateSubscriber<User>,
  options: { timeoutMs?: number } = {}
): Promise<string | null> {
  if (authState.currentUser) {
    return authState.currentUser.getIdToken();
  }

  const user = await waitForAuthUser(
    subscribe,
    options.timeoutMs ?? DEFAULT_AUTH_READY_TIMEOUT_MS
  );
  return user ? user.getIdToken() : null;
}

function waitForAuthUser<User extends IdTokenUser>(
  subscribe: AuthStateSubscriber<User>,
  timeoutMs: number
): Promise<User | null> {
  return new Promise((resolve) => {
    let settled = false;
    let unsubscribe: (() => void) | null = null;
    const timeout = setTimeout(() => finish(null), timeoutMs);

    function finish(user: User | null) {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      unsubscribe?.();
      resolve(user);
    }

    unsubscribe = subscribe(finish);
    if (settled) unsubscribe();
  });
}
