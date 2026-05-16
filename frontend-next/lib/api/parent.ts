import { apiFetch } from "./client";

export interface ParentProfile {
  first_name: string;
  last_name: string;
  email?: string | null;
  phone: string;
}

export interface ChildProfile {
  first_name: string;
  last_name: string;
  date_of_birth: string;
  skill_level: "beginner" | "intermediate" | "advanced" | "";
}

export interface OnboardingApplication {
  application_id: string;
  status:
    | "DRAFT"
    | "CHECKOUT_PENDING"
    | "CHECKOUT_EXPIRED"
    | "PENDING_APPROVAL"
    | "CAPACITY_FAILED_REFUNDING"
    | "REFUNDED"
    | "CAPACITY_FAILED_REFUND_FAILED"
    | "ABANDONED";
  parent_profile: ParentProfile;
  child_profile: ChildProfile;
  selected_session_id: string | null;
  waiver_accepted: boolean;
  expires_at: string;
}

export interface ParentPayment {
  payment_id: string;
  amount_cents: number;
  currency: string;
  status: string;
  refunded_cents: number;
  created_at: string;
  session_id: string | null;
}

export function startOnboarding(): Promise<OnboardingApplication> {
  return apiFetch("/parent/onboarding/start", { method: "POST", body: "{}" });
}

export function patchOnboarding(
  application_id: string,
  patch: {
    parent_profile?: Partial<ParentProfile>;
    child_profile?: Partial<ChildProfile>;
    selected_session_id?: string;
    accept_waiver?: boolean;
  }
): Promise<OnboardingApplication> {
  return apiFetch(`/parent/onboarding/${application_id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function getOnboardingStatus(application_id: string): Promise<OnboardingApplication> {
  return apiFetch(`/parent/onboarding/${application_id}/status`, { method: "GET" });
}

export function startCheckout(payload: {
  application_id: string;
  amount_cents: number;
  success_url: string;
  cancel_url: string;
}): Promise<{ payment_id: string; redirect_url: string }> {
  return apiFetch("/parent/checkout/start", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listParentPayments(): Promise<{ payments: ParentPayment[] }> {
  return apiFetch("/parent/payments", { method: "GET" });
}
