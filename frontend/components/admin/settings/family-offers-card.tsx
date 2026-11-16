"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getFamilyOffers,
  updateFamilyOffers,
  type FamilyOffersView,
  type UpdateFamilyOffersPayload,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";
import { useReportSettingsDirty } from "@/components/admin/settings/settings-dirty-context";

type Referral = FamilyOffersView["referral_program"];
type Sibling = FamilyOffersView["sibling_discount"];
type FullPriceChild = NonNullable<Sibling["full_price_child"]>;
type AppliesTo = NonNullable<Sibling["applies_to"]>;
type Trigger = NonNullable<Referral["trigger"]>;

/**
 * The form's starting values, used only where the academy has stored nothing.
 * The backend holds no business values; every number here is the owner's to
 * change before saving. The sibling percentage deliberately has none.
 */
export const STARTING_VALUES = {
  referrerCreditDollars: "25",
  referredCreditDollars: "25",
  holdDays: "7",
  maxRewards: "10",
  expiryDays: "", // blank = credits never expire
  trigger: "first_paid_invoice" as Trigger,
  fullPriceChild: "highest_tuition" as FullPriceChild,
  appliesTo: "all_classes" as AppliesTo,
};

export interface SiblingForm {
  enabled: boolean;
  percent: string;
  fullPriceChild: FullPriceChild;
  appliesTo: AppliesTo;
}

export interface ReferralForm {
  referrerCreditDollars: string;
  referredCreditDollars: string;
  holdDays: string;
  maxRewards: string;
  expiryDays: string;
  trigger: Trigger;
}

const dollars = (cents: number | null | undefined, fallback: string) =>
  cents == null ? fallback : (cents / 100).toFixed(2).replace(/\.00$/, "");
const whole = (value: number | null | undefined, fallback: string) =>
  value == null ? fallback : String(value);

export function siblingFormFrom(view: Sibling): SiblingForm {
  return {
    enabled: view.enabled,
    percent: view.percent_bps == null ? "" : String(view.percent_bps / 100),
    fullPriceChild: view.full_price_child ?? STARTING_VALUES.fullPriceChild,
    appliesTo: view.applies_to ?? STARTING_VALUES.appliesTo,
  };
}

export function referralFormFrom(view: Referral): ReferralForm {
  return {
    referrerCreditDollars: dollars(
      view.referrer_credit_cents,
      STARTING_VALUES.referrerCreditDollars,
    ),
    referredCreditDollars: dollars(
      view.referred_credit_cents,
      STARTING_VALUES.referredCreditDollars,
    ),
    holdDays: whole(view.hold_days, STARTING_VALUES.holdDays),
    maxRewards: whole(
      view.max_rewards_per_referrer_per_year,
      STARTING_VALUES.maxRewards,
    ),
    expiryDays: whole(view.credit_expiry_days, STARTING_VALUES.expiryDays),
    trigger: view.trigger ?? STARTING_VALUES.trigger,
  };
}

/** Blank -> null; anything not a number -> NaN so the server's 422 names it. */
const toNumber = (text: string): number | null =>
  text.trim() === "" ? null : Number(text);
const toCents = (text: string): number | null => {
  const value = toNumber(text);
  return value == null ? null : Math.round(value * 100);
};

/** Only the blocks the owner changed, so untouched starting values are never stored. */
export function familyOffersPayload(
  view: FamilyOffersView,
  sibling: SiblingForm,
  referral: ReferralForm,
): UpdateFamilyOffersPayload {
  const payload: UpdateFamilyOffersPayload = {};
  if (
    JSON.stringify(sibling) !==
    JSON.stringify(siblingFormFrom(view.sibling_discount))
  ) {
    payload.sibling_discount = {
      enabled: sibling.enabled,
      percent_bps: toCents(sibling.percent),
      full_price_child: sibling.fullPriceChild,
      applies_to: sibling.appliesTo,
    };
  }
  if (
    JSON.stringify(referral) !==
    JSON.stringify(referralFormFrom(view.referral_program))
  ) {
    payload.referral_program = {
      referrer_credit_cents: toCents(referral.referrerCreditDollars),
      referred_credit_cents: toCents(referral.referredCreditDollars),
      hold_days: toNumber(referral.holdDays),
      max_rewards_per_referrer_per_year: toNumber(referral.maxRewards),
      credit_expiry_days: toNumber(referral.expiryDays),
      trigger: referral.trigger,
    };
  }
  return payload;
}

/** The client-side check the save button waits on; the server re-checks every bound. */
export function siblingError(form: SiblingForm): string | null {
  if (form.percent.trim() === "") {
    return form.enabled
      ? "Enter the sibling discount percentage to switch it on."
      : null;
  }
  const value = Number(form.percent);
  if (!Number.isFinite(value) || value < 0.01 || value > 100) {
    return "The sibling discount must be between 0.01% and 100%.";
  }
  return null;
}

const FULL_PRICE_LABELS: Record<FullPriceChild, string> = {
  highest_tuition: "The child with the highest tuition",
  lowest_tuition: "The child with the lowest tuition",
  first_enrolled: "The child who enrolled first",
};
const APPLIES_TO_LABELS: Record<AppliesTo, string> = {
  all_classes: "Every class of each other child",
  one_class_per_child: "One class per other child (the most expensive)",
};
const TRIGGER_LABELS: Record<Trigger, string> = {
  first_paid_invoice: "Their first paid invoice",
  first_paid_monthly_invoice: "Their first paid monthly invoice",
};

const INPUT =
  "h-10 w-28 rounded-lg border border-rally-line bg-white px-3 font-mono text-sm tabular-nums outline-none focus:border-blue-500";
const SELECT =
  "h-10 rounded-lg border border-rally-line bg-white px-3 text-sm outline-none focus:border-blue-500";

/**
 * Settings -> Billing rules -> Family offers (L9 C1). Owner only, like the
 * panel it sits in; the save is audited server side and applies to invoices
 * generated afterwards only. The referral programme stores its values now and
 * can be switched on once its logic ships (C2).
 */
export function FamilyOffersCard() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: queryKeys.admin.familyOffers(),
    queryFn: getFamilyOffers,
  });
  const view = query.data;
  const [sibling, setSibling] = useState<SiblingForm | null>(() =>
    view ? siblingFormFrom(view.sibling_discount) : null,
  );
  const [referral, setReferral] = useState<ReferralForm | null>(() =>
    view ? referralFormFrom(view.referral_program) : null,
  );
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!view) return;
    setSibling(siblingFormFrom(view.sibling_discount));
    setReferral(referralFormFrom(view.referral_program));
  }, [view]);

  const payload =
    view && sibling && referral
      ? familyOffersPayload(view, sibling, referral)
      : {};
  const dirty = Object.keys(payload).length > 0;
  const error = sibling ? siblingError(sibling) : null;
  useReportSettingsDirty("family-offers", dirty);

  const mutation = useMutation({
    mutationFn: () => updateFamilyOffers(payload),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.admin.familyOffers(), data);
      setSaved(true);
    },
  });

  const editSibling = (patch: Partial<SiblingForm>) => {
    setSaved(false);
    setSibling((prev) => (prev ? { ...prev, ...patch } : prev));
  };
  const editReferral = (patch: Partial<ReferralForm>) => {
    setSaved(false);
    setReferral((prev) => (prev ? { ...prev, ...patch } : prev));
  };

  return (
    <Card p={24} className="max-w-3xl" data-testid="family-offers-card">
      <Overline>Family offers</Overline>
      <p className="mt-2 text-sm text-rally-muted">
        Optional offers for families. Changes apply to invoices generated after
        you save; invoices already issued keep their amounts.
      </p>
      {query.isError && (
        <p className="mt-3 text-sm text-red-700" role="alert">
          Could not load the family offers.
        </p>
      )}
      {sibling && referral && (
        <>
          <fieldset
            className="mt-5 space-y-3"
            data-testid="family-offers-sibling"
          >
            <legend className="text-sm font-semibold text-rally-ink">
              Sibling discount
            </legend>
            <p className="text-xs text-rally-muted">
              One child in a family pays full price; each other child&apos;s
              monthly tuition is discounted. A manual discount on a class wins
              when it is larger; the two never add up.
            </p>
            <label className="flex items-center gap-2 text-sm text-rally-ink">
              <input
                type="checkbox"
                checked={sibling.enabled}
                onChange={(event) =>
                  editSibling({ enabled: event.target.checked })
                }
                data-testid="family-offers-sibling-enabled"
              />
              Use the sibling discount
            </label>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="grid gap-1.5 text-sm font-medium text-rally-ink">
                <span>Discount</span>
                <span className="flex items-center gap-2">
                  <input
                    type="number"
                    min={0.01}
                    max={100}
                    step="0.01"
                    inputMode="decimal"
                    value={sibling.percent}
                    onChange={(event) =>
                      editSibling({ percent: event.target.value })
                    }
                    aria-invalid={error ? true : undefined}
                    className={INPUT}
                    data-testid="family-offers-sibling-percent"
                  />
                  <span>%</span>
                </span>
              </label>
              <label className="grid gap-1.5 text-sm font-medium text-rally-ink">
                <span>Who pays full price</span>
                <select
                  value={sibling.fullPriceChild}
                  onChange={(event) =>
                    editSibling({
                      fullPriceChild: event.target.value as FullPriceChild,
                    })
                  }
                  className={SELECT}
                  data-testid="family-offers-sibling-full-price"
                >
                  {Object.entries(FULL_PRICE_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="grid gap-1.5 text-sm font-medium text-rally-ink sm:col-span-2">
                <span>Discount applies to</span>
                <select
                  value={sibling.appliesTo}
                  onChange={(event) =>
                    editSibling({ appliesTo: event.target.value as AppliesTo })
                  }
                  className={SELECT}
                  data-testid="family-offers-sibling-applies-to"
                >
                  {Object.entries(APPLIES_TO_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {error && (
              <p
                className="text-xs text-red-700"
                role="alert"
                data-testid="family-offers-sibling-error"
              >
                {error}
              </p>
            )}
          </fieldset>

          <fieldset
            className="mt-8 space-y-3"
            data-testid="family-offers-referral"
          >
            <legend className="text-sm font-semibold text-rally-ink">
              Referral programme{" "}
              <span className="ml-1 rounded bg-rally-paper px-1.5 py-0.5 text-xs font-medium text-rally-muted">
                Coming soon
              </span>
            </legend>
            <p className="text-xs text-rally-muted">
              Both families get an account credit once the referred family pays.
              You can set the values now; switching the programme on arrives in
              a later update.
            </p>
            <label className="flex items-center gap-2 text-sm text-rally-muted">
              <input
                type="checkbox"
                checked={view?.referral_program.enabled ?? false}
                disabled
                data-testid="family-offers-referral-enabled"
              />
              Use the referral programme
            </label>
            <div className="grid gap-3 sm:grid-cols-2">
              <NumberField
                label="Credit for the referring family ($)"
                value={referral.referrerCreditDollars}
                onChange={(value) =>
                  editReferral({ referrerCreditDollars: value })
                }
                testId="family-offers-referrer-credit"
                step="0.01"
              />
              <NumberField
                label="Credit for the new family ($)"
                value={referral.referredCreditDollars}
                onChange={(value) =>
                  editReferral({ referredCreditDollars: value })
                }
                testId="family-offers-referred-credit"
                step="0.01"
              />
              <NumberField
                label="Days to hold the credit"
                value={referral.holdDays}
                onChange={(value) => editReferral({ holdDays: value })}
                testId="family-offers-hold-days"
              />
              <NumberField
                label="Most rewards per family per year"
                value={referral.maxRewards}
                onChange={(value) => editReferral({ maxRewards: value })}
                testId="family-offers-max-rewards"
              />
              <NumberField
                label="Credits expire after (days; blank = never)"
                value={referral.expiryDays}
                onChange={(value) => editReferral({ expiryDays: value })}
                testId="family-offers-expiry-days"
              />
              <label className="grid gap-1.5 text-sm font-medium text-rally-ink">
                <span>Reward when the new family pays</span>
                <select
                  value={referral.trigger}
                  onChange={(event) =>
                    editReferral({ trigger: event.target.value as Trigger })
                  }
                  className={SELECT}
                  data-testid="family-offers-referral-trigger"
                >
                  {Object.entries(TRIGGER_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </fieldset>

          <div className="mt-6 flex flex-wrap items-center gap-3">
            <Button
              variant={dirty && !error ? "volt" : "secondary"}
              size="sm"
              disabled={!dirty || Boolean(error) || mutation.isPending}
              onClick={() => mutation.mutate()}
              data-testid="family-offers-save"
            >
              {mutation.isPending ? "Saving…" : "Save family offers"}
            </Button>
            {saved && !mutation.isPending && !dirty && (
              <span
                className="text-sm text-rally-muted"
                data-testid="family-offers-saved"
              >
                Saved.
              </span>
            )}
            {mutation.isError && (
              <span className="text-sm text-red-700" role="alert">
                {mutation.error instanceof Error
                  ? mutation.error.message
                  : "Could not save the family offers."}
              </span>
            )}
          </div>
        </>
      )}
    </Card>
  );
}

function NumberField({
  label,
  value,
  onChange,
  testId,
  step = "1",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  testId: string;
  step?: string;
}) {
  return (
    <label className="grid gap-1.5 text-sm font-medium text-rally-ink">
      <span>{label}</span>
      <input
        type="number"
        min={0}
        step={step}
        inputMode={step === "1" ? "numeric" : "decimal"}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={INPUT}
        data-testid={testId}
      />
    </label>
  );
}
