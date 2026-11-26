"use client";

/**
 * S65: the four things the front desk does every day, one tap from Today.
 * 64px tall in a 2x2 grid on a phone; md buttons in the header row on desktop.
 */

import { useState } from "react";
import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { recordAdminAbsence, type AdminToday } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { useIsPhone } from "@/lib/use-is-phone";
import { QuickAddFamily } from "@/app/(admin)/admin/families/QuickAddFamily";
import { RecordAbsenceDialog } from "@/components/admin/requests/request-queues";
import { Button } from "@/components/ds/button";
import { Modal } from "@/components/ds/modal";
import { useToast } from "@/components/ds/toast";

import { liveClass } from "./format";
import { RunningLateDialog } from "./running-late-dialog";

type Dialog = "absent" | "late" | "walkin" | null;

const PHONE_BUTTON = { height: 64, minHeight: 64 } as const;

export function QuickActionButtons({
  isPhone,
  onAbsent,
  onLate,
  onSick,
  onWalkIn,
  sickDisabled,
}: {
  isPhone: boolean;
  onAbsent: () => void;
  onLate: () => void;
  onSick: () => void;
  onWalkIn: () => void;
  sickDisabled: boolean;
}) {
  const style = isPhone ? PHONE_BUTTON : undefined;
  return (
    <div
      className={isPhone ? "grid w-full grid-cols-2 gap-2" : "flex flex-wrap gap-2"}
      data-testid="admin-today-quick-actions"
    >
      <Button variant="secondary" style={style} onClick={onAbsent} data-testid="admin-today-action-absent">
        Absent
      </Button>
      <Button variant="secondary" style={style} onClick={onLate} data-testid="admin-today-action-late">
        Running late
      </Button>
      <Button
        variant="secondary"
        style={style}
        onClick={onSick}
        disabled={sickDisabled}
        data-testid="admin-today-action-sick"
      >
        Coach is sick
      </Button>
      <Button variant="secondary" style={style} onClick={onWalkIn} data-testid="admin-today-action-walkin">
        New walk-in
      </Button>
    </div>
  );
}

export function QuickActions({ today }: { today: AdminToday | undefined }) {
  const isPhone = useIsPhone();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [dialog, setDialog] = useState<Dialog>(null);
  const classes = today?.classes ?? [];
  const live = liveClass(classes);

  const absence = useMutation({
    mutationFn: ({ payload }: { payload: Parameters<typeof recordAdminAbsence>[0]; name?: string }) =>
      recordAdminAbsence(payload),
    onSuccess: (_row, { name }) => {
      toast({ kind: "success", title: name ? `Absence recorded for ${name}.` : "Absence recorded." });
      setDialog(null);
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.selfServiceAbsences() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.today() });
    },
  });

  return (
    <>
      <QuickActionButtons
        isPhone={isPhone}
        onAbsent={() => setDialog("absent")}
        onLate={() => setDialog("late")}
        // shortcut: the class page's replacement-coach picker until the S66 cover flow lands.
        onSick={() =>
          live &&
          router.push(
            `/admin/sessions/${encodeURIComponent(live.session_id)}?cover=${encodeURIComponent(live.occurrence_id)}` as Route,
          )
        }
        sickDisabled={!live}
        onWalkIn={() => setDialog("walkin")}
      />
      {dialog === "absent" ? (
        <RecordAbsenceDialog
          pending={absence.isPending}
          error={absence.isError ? absence.error : null}
          initialOccurrenceId={live?.occurrence_id}
          todayClasses={classes.filter((c) => c.phase !== "cancelled")}
          onCancel={() => {
            absence.reset();
            setDialog(null);
          }}
          onConfirm={(payload, name) => absence.mutate({ payload, name })}
        />
      ) : null}
      {dialog === "late" ? <RunningLateDialog today={today} onClose={() => setDialog(null)} /> : null}
      {dialog === "walkin" ? (
        <Modal open onClose={() => setDialog(null)} title="New walk-in" size="lg">
          <div className="max-h-[75vh] overflow-y-auto">
            <QuickAddFamily
              initialOpen
              initialSessionId={live?.session_id}
              onClose={() => setDialog(null)}
              onAdded={() => void queryClient.invalidateQueries({ queryKey: queryKeys.admin.today() })}
            />
          </div>
        </Modal>
      ) : null}
    </>
  );
}
