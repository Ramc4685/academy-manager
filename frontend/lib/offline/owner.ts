"use client";

import { getActiveAcademyId } from "@/lib/api/client";
import { auth } from "@/lib/auth/firebase";

/**
 * Who queued a mark on this device. A shared club tablet changes hands, so a
 * mark queued by one coach must never be replayed under the next one's token.
 */
export interface MutationOwner {
  user_id: string;
  academy_id: string | null;
}

export function currentOwner(): MutationOwner | null {
  try {
    const uid = auth().currentUser?.uid;
    return uid ? { user_id: uid, academy_id: getActiveAcademyId() } : null;
  } catch {
    return null;
  }
}

/**
 * True when a stamped mutation must not be sent now: someone else is signed
 * in, or nobody is yet (auth still restoring). Unstamped mutations predate the
 * stamp and keep the old behaviour.
 */
export function heldForOtherOwner(
  owner: MutationOwner | undefined,
  current: MutationOwner | null,
): boolean {
  if (!owner) return false;
  return (
    !current ||
    owner.user_id !== current.user_id ||
    owner.academy_id !== current.academy_id
  );
}
