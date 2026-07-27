/**
 * Single source of seeded credentials for the real-auth CI smoke spec.
 *
 * These must line up with what `scripts/local_test_stack.sh seed` writes into
 * Mongo + the Firebase Auth emulator (via `backend/scripts/seed_local.py`).
 * Override via env if the local stack was seeded with non-default passwords.
 */
export const REAL_AUTH_USERS = {
  admin: {
    email: process.env.LOCAL_AUTH_ADMIN_EMAIL ?? "ramchand4685@gmail.com",
    password:
      process.env.LOCAL_AUTH_ADMIN_PASSWORD ??
      process.env.SEED_ADMIN_PASSWORD ??
      "CHANGE_ME",
  },
  parent: {
    email: process.env.LOCAL_AUTH_PARENT_EMAIL ?? "manojedward.btech@gmail.com",
    password:
      process.env.LOCAL_AUTH_PARENT_PASSWORD ??
      process.env.SEED_PARENT_PASSWORD ??
      "CHANGE_ME",
  },
} as const;
