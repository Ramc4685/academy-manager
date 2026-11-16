"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { orderPickerResults, pinnedPickerOptions, studentPickerParams } from "@/lib/admin/student-picker";
import { listAdminStudents, type AdminStudentView } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";

/**
 * Student picker backed by server-side search (L2 A0-2). Replaces selects fed
 * by one unfiltered page, which hid every student past the first 50.
 */
export function StudentSearchPicker({
  value,
  onChange,
  enabled = true,
  selected,
  selectClassName,
  testId,
}: {
  value: string;
  onChange: (student: AdminStudentView) => void;
  enabled?: boolean;
  /** Keeps a prefilled student selectable when the current results miss them. */
  selected?: Pick<AdminStudentView, "student_id" | "full_name">;
  selectClassName: string;
  testId?: string;
}) {
  const [text, setText] = useState("");
  const [picked, setPicked] = useState<AdminStudentView>();
  const [search, setSearch] = useState("");
  useEffect(() => {
    const id = setTimeout(() => setSearch(text.trim()), 300);
    return () => clearTimeout(id);
  }, [text]);

  const params = studentPickerParams(search);
  const query = useQuery({
    queryKey: queryKeys.admin.students({ search: params.search, limit: params.limit }),
    queryFn: () => listAdminStudents(params),
    enabled,
    placeholderData: (prev) => prev,
  });
  const students = orderPickerResults(query.data?.students ?? []);
  const pinned = pinnedPickerOptions(students, value, selected, picked);

  return (
    <div className="space-y-2">
      <input
        type="search"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Search students or parents"
        aria-label="Search students"
        className={selectClassName}
      />
      <select
        required
        value={value}
        onChange={(e) => {
          const choice = students.find((s) => s.student_id === e.target.value);
          if (choice) {
            setPicked(choice);
            onChange(choice);
          }
        }}
        className={selectClassName}
        aria-label="Student"
        data-testid={testId}
      >
        <option value="">
          {query.isLoading
            ? "Loading students…"
            : query.isError
              ? "Could not load students"
              : students.length === 0
                ? "No students found"
                : "Select a student"}
        </option>
        {pinned.map((s) => (
          <option key={s.student_id} value={s.student_id}>
            {s.full_name}
          </option>
        ))}
        {students.map((s) => (
          <option key={s.student_id} value={s.student_id}>
            {s.full_name}
          </option>
        ))}
      </select>
      {query.data?.next_cursor && (
        <p className="text-xs text-rally-subtle">Showing the first {students.length}. Type to search everyone.</p>
      )}
    </div>
  );
}
