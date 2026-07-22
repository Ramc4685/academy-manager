import type { ReactNode } from "react";

interface FormFieldProps {
  label: ReactNode;
  htmlFor: string;
  error?: string | null;
  hint?: ReactNode;
  required?: boolean;
  className?: string;
  children: ReactNode;
}

/**
 * Build the `aria-describedby` value for a control wrapped by FormField, so
 * inputs can wire hint/error ids without cloneElement magic.
 */
export function fieldDescribedBy(
  htmlFor: string,
  parts: { hint?: unknown; error?: unknown },
): string | undefined {
  const ids: string[] = [];
  if (parts.hint) ids.push(`${htmlFor}-hint`);
  if (parts.error) ids.push(`${htmlFor}-error`);
  return ids.length ? ids.join(" ") : undefined;
}

export function FormField({
  label,
  htmlFor,
  error,
  hint,
  required,
  className,
  children,
}: FormFieldProps) {
  return (
    <div className={`space-y-1 ${className ?? ""}`}>
      <label htmlFor={htmlFor} className="block text-xs font-semibold text-rally-muted">
        {label}
        {required && (
          <span className="ml-0.5 text-status-red-600" aria-hidden="true">
            *
          </span>
        )}
      </label>
      {hint && (
        <p id={`${htmlFor}-hint`} className="text-xs text-rally-subtle">
          {hint}
        </p>
      )}
      {children}
      {error && (
        <p id={`${htmlFor}-error`} role="alert" className="text-xs font-medium text-status-red-800">
          {error}
        </p>
      )}
    </div>
  );
}
