/**
 * Step 1 — Parent profile.
 * PATCHes parent_profile fields, then advances to /child.
 *
 * Phase 5 Slice 5.
 */
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { toast } from "sonner";
import OnboardingLayout from "./OnboardingLayout";

const empty = {
  phone: "",
  address: "",
  emergency_contact: "",
  emergency_phone: "",
};

export default function OnboardingProfile() {
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
          navigate(`/onboarding/${draftId}/profile`, { replace: true });
          return;
        }
        const saved = r.data?.parent_profile || {};
        setForm({
          phone: saved.phone || "",
          address: saved.address || "",
          emergency_contact: saved.emergency_contact || "",
          emergency_phone: saved.emergency_phone || "",
        });
      })
      .catch(() => {});
  }, [id, navigate]);

  const update = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const isValid =
    form.phone.trim() &&
    form.address.trim() &&
    form.emergency_contact.trim() &&
    form.emergency_phone.trim();

  const submit = async () => {
    if (!isValid) {
      toast.error("Please fill in all required fields");
      return;
    }
    setBusy(true);
    try {
      await api.patch(`/onboarding/${id}`, {
        parent_profile: {
          phone: form.phone.trim(),
          address: form.address.trim(),
          emergency_contact: form.emergency_contact.trim(),
          emergency_phone: form.emergency_phone.trim(),
        },
      });
      navigate(`/onboarding/${id}/child`);
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
    <OnboardingLayout step={1}>
      <h1 className="text-2xl sm:text-3xl font-display font-bold tracking-tighter text-slate-900 mb-2">
        Your contact information
      </h1>
      <p className="text-slate-600 text-sm mb-6">
        We need this in case we need to reach you during sessions.
      </p>

      <div
        className="bg-white border border-slate-200 rounded-xl p-5 sm:p-6 space-y-4"
        data-testid="profile-step"
      >
        <div>
          <Label htmlFor="phone">
            Mobile phone <span className="text-red-500">*</span>
          </Label>
          <Input
            id="phone"
            type="tel"
            value={form.phone}
            onChange={update("phone")}
            placeholder="10-digit US phone"
            className="mt-1"
            data-testid="profile-phone"
          />
        </div>

        <div>
          <Label htmlFor="address">
            Home address <span className="text-red-500">*</span>
          </Label>
          <Input
            id="address"
            value={form.address}
            onChange={update("address")}
            placeholder="123 Main St, City, State 12345"
            className="mt-1"
            data-testid="profile-address"
          />
        </div>

        <div>
          <Label htmlFor="emergency_contact">
            Emergency contact name <span className="text-red-500">*</span>
          </Label>
          <Input
            id="emergency_contact"
            value={form.emergency_contact}
            onChange={update("emergency_contact")}
            placeholder="Full name"
            className="mt-1"
            data-testid="profile-emergency-contact"
          />
        </div>

        <div>
          <Label htmlFor="emergency_phone">
            Emergency contact phone <span className="text-red-500">*</span>
          </Label>
          <Input
            id="emergency_phone"
            type="tel"
            value={form.emergency_phone}
            onChange={update("emergency_phone")}
            placeholder="10-digit US phone"
            className="mt-1"
            data-testid="profile-emergency-phone"
          />
        </div>

        <div className="flex justify-end pt-2">
          <Button
            onClick={submit}
            disabled={!isValid || busy}
            className="min-h-[44px] bg-blue-600 hover:bg-blue-500 text-white"
            data-testid="profile-next"
          >
            {busy ? "Saving…" : "Next: Child details"}
          </Button>
        </div>
      </div>
    </OnboardingLayout>
  );
}
