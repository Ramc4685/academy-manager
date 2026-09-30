/**
 * Issue #148 follow-up: the create-session dialog seeds `capacity` from the
 * academy's Class defaults on open, but the academy query can still be
 * loading at that moment, so the seed falls back to EMPTY_FORM.capacity (10).
 * This mirrors the timezone fix (see CreateClassDialog) for capacity: once
 * the academy query resolves for an already-open dialog, adopt its real
 * default_class_size — unless the admin already edited capacity themselves.
 */
export function shouldAdoptAcademyCapacity(params: {
  open: boolean;
  wasOpen: boolean;
  capacityTouched: boolean;
  defaultClassSize: number | null | undefined;
}): boolean {
  return (
    params.open && params.wasOpen && params.defaultClassSize != null && !params.capacityTouched
  );
}
