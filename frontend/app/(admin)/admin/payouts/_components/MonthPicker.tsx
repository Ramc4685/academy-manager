"use client";
import { ChevronLeft, ChevronRight } from "lucide-react";

interface MonthPickerProps { value: string; onChange: (month: string) => void; }

function shiftMonth(month: string, delta: 1 | -1): string {
  const [y, m] = month.split("-").map(Number);
  const d = new Date(y, m - 1 + delta);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export function MonthPicker({ value, onChange }: MonthPickerProps) {
  return (
    <div className="flex items-center gap-2">
      <button onClick={() => onChange(shiftMonth(value, -1))} aria-label="Previous month">
        <ChevronLeft className="size-4" />
      </button>
      <input
        type="month"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="border rounded px-2 py-1 text-sm"
      />
      <button onClick={() => onChange(shiftMonth(value, 1))} aria-label="Next month">
        <ChevronRight className="size-4" />
      </button>
    </div>
  );
}
