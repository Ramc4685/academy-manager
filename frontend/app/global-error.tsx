"use client";

import { useEffect } from "react";

/**
 * Root-layout error boundary. Replaces the whole document when the root layout
 * itself fails, so it renders its own <html>/<body> with inline styles (global
 * CSS may not have loaded). The raw error is logged, never displayed.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100dvh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#f8fafc",
          color: "#0f172a",
          fontFamily: "system-ui, sans-serif",
          padding: "1.5rem",
        }}
      >
        <div
          style={{
            maxWidth: "28rem",
            width: "100%",
            textAlign: "center",
            background: "#fff",
            border: "1px solid #e2e8f0",
            borderRadius: "0.75rem",
            padding: "2rem",
          }}
        >
          <h1 style={{ fontSize: "1.5rem", fontWeight: 700, margin: 0 }}>Something went wrong</h1>
          <p style={{ marginTop: "0.5rem", fontSize: "0.875rem", color: "#475569" }}>
            We hit an unexpected problem. Your data is safe. Try again, and if it
            keeps happening, contact your academy.
          </p>
          <button
            type="button"
            onClick={reset}
            style={{
              marginTop: "1.5rem",
              padding: "0.625rem 1rem",
              fontSize: "0.875rem",
              fontWeight: 500,
              color: "#fff",
              background: "#2563eb",
              border: "none",
              borderRadius: "0.375rem",
              cursor: "pointer",
            }}
          >
            Try again
          </button>
        </div>
      </body>
    </html>
  );
}
