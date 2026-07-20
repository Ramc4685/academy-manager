// Collector for Content-Security-Policy report-uri (QW5 report-only rollout).
// Browsers POST violation reports here; we log them server-side so the
// staging/prod bake is observable in request logs, then discard.
export async function POST(request: Request): Promise<Response> {
  try {
    const report = await request.text();
    if (report) {
      console.warn("[csp-report]", report.slice(0, 4000));
    }
  } catch {
    // A malformed or aborted report body is not worth a 5xx to the browser.
  }
  return new Response(null, { status: 204 });
}
