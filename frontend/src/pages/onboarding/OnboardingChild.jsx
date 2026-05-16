/**
 * Step 2 — Child profile.
 * PATCHes child_profile fields, then advances to /waiver.
 *
 * Phase 5 Slice 5.
 */
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Textarea } from "../../components/ui/textarea";
import { toast } from "sonner";
import OnboardingLayout from "./OnboardingLayout";

const empty = {
  name: "",
  dob: "",
  medical_notes: "",
  consent_to_treat: false,
};

export default function OnboardingChild() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [form, setForm] = useState(empty);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .post("/onboarding/start", {})
      .then((r) => {
        const draftId = r.data?._id || r.data?.id;
        if (draftId && draftId !== id) {
          navigate(`/onboarding/${draftId}/child`, { replace: true });
          return;
        }
        const saved = r.data?.child_profile || {};
        setForm({
          name: saved.name || "",
          dob: saved.dob || "",
          medical_notes: saved.medical_notes || "",
          consent_to_treat: Boolean(saved.consent_to_treat),
        });
      })
      .catch(() => {});
  }, [id, navigate]);

  const update = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const isValid = form.name.trim() && form.dob.trim();

  const submit = async () => {
    if (!isValid) {
      toast.error("Please fill in all required fields");
      return;
    }
    setBusy(true);
    try {
      await api.patch(`/onboarding/${id}`, {
        child_profile: {
          name: form.name.trim(),
          dob: form.dob,
          medical_notes: form.medical_notes.trim(),
          consent_to_treat: form.consent_to_treat,
        },
      });
      navigate(`/onboarding/${id}/waiver`);
    } catch (e) {
      toast.error(
        e?.response?.data?.detail ||
          e?.response?.data?.error ||
          "Failed to save. Please try again."
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <OnboardingLayout step={2}>
      <h1 className="text-2xl sm:text-3xl font-display font-bold tracking-tighter text-slate-900 mb-2">
        Your child's details
      </h1>
      <p className="text-slate-600 text-sm mb-6">
        Tell us about the child you're enrolling.
      </p>

      <div
        className="bg-white border border-slate-200 rounded-xl p-5 sm:p-6 space-y-4"
        data-testid="child-step"
      >
        <div>
          <Label htmlFor="child-name">
            Child's full name <span className="text-red-500">*</span>
          </Label>
          <Input
            id="child-name"
            value={form.name}
            onChange={update("name")}
            placeholder="First and last name"
            className="mt-1"
            data-testid="child-name"
          />
        </div>

        <div>
          <Label htmlFor="child-dob">
            Date of birth <span className="text-red-500">*</span>
          </Label>
          <Input
            id="child-dob"
            type="date"
            value={form.dob}
            onChange={update("dob")}
            className="mt-1"
            data-testid="child-dob"
          />
        </div>

        <div>
          <Label htmlFor="medical-notes">
            Medical conditions or allergies
          </Label>
          <Textarea
            id="medical-notes"
            rows={3}
            value={form.medical_notes}
            onChange={update("medical_notes")}
            placeholder="None / describe any relevant conditions"
            className="mt-1"
            data-testid="child-medical"
          />
        </div>

        <label className="flex items-start gap-3 p-3 rounded-lg border border-slate-200 cursor-pointer">
          <input
            type="checkbox"
            checked={form.consent_to_treat}
            onChange={(e) =>
              setForm({ ...form, consent_to_treat: e.target.checked })
            }
            className="mt-0.5 h-4 w-4 rounded border-slate-300 text-blue-600"
            data-testid="child-consent"
          />
          <div className="text-sm text-slate-700">
            <div className="font-medium">Consent to treat</div>
            <div className="text-xs text-slate-500 mt-0.5">
              I consent to emergency medical treatment for my child if I cannot
              be reached.
            </div>
          </div>
        </label>

        <div className="flex justify-between pt-2">
          <Button
            variant="outline"
            onClick={() => navigate(`/onboarding/${id}/profile`)}
            className="min-h-[44px]"
            data-testid="child-back"
          >
            Back
          </Button>
          <Button
            onClick={submit}
            disabled={!isValid || busy}
            className="min-h-[44px] bg-blue-600 hover:bg-blue-500 text-white"
            data-testid="child-next"
          >
            {busy ? "Saving…" : "Next: Waiver"}
          </Button>
        </div>
      </div>
    </OnboardingLayout>
  );
}
