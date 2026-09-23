// Tiny stand-in for the backend's anonymous `GET /api/v2/public/academy`
// during Playwright runs (Lane B3).
//
// The public academy page is server-rendered: Next fetches the page data on
// the server, so Playwright's browser-side `page.route` stubs (mock-api.ts)
// never see that request. playwright.config.ts starts this server and points
// the Next dev server's BFF_API_ORIGIN at it.
//
// A spec picks a fixture from e2e/fixtures/public-academy-pages.json by
// appending `cm-e2e-public-fixture/<name>` to its user agent (the server
// fetch forwards the visitor's user agent). `unknown` answers the backend's
// bare 404; `down` answers 503. The last request headers per fixture are
// readable at /__last-request?fixture=<name> so a spec can check what the
// server fetch forwarded. Every other path answers 502, like a dead backend.

import { readFileSync } from "node:fs";
import { createServer } from "node:http";

const port = Number(process.env.PUBLIC_ACADEMY_STUB_PORT ?? "0");
if (!port) {
  console.error("PUBLIC_ACADEMY_STUB_PORT is required");
  process.exit(1);
}

const fixtures = JSON.parse(
  readFileSync(new URL("./public-academy-pages.json", import.meta.url), "utf8"),
);
const lastRequest = new Map();
const FIXTURE_PATTERN = /cm-e2e-public-fixture\/([a-z_]+)/;

function send(res, status, body) {
  res.writeHead(status, { "content-type": "application/json", vary: "Host" });
  res.end(JSON.stringify(body));
}

createServer((req, res) => {
  const url = new URL(req.url ?? "/", "http://stub.local");
  if (url.pathname === "/__health") return send(res, 200, { ok: true });
  if (url.pathname === "/__last-request") {
    return send(res, 200, lastRequest.get(url.searchParams.get("fixture")) ?? null);
  }
  if (req.method === "GET" && url.pathname === "/api/v2/public/academy") {
    const name = FIXTURE_PATTERN.exec(req.headers["user-agent"] ?? "")?.[1] ?? "unknown";
    lastRequest.set(name, req.headers);
    if (name === "down") return send(res, 503, { detail: "Service unavailable" });
    const body = fixtures[name];
    if (!body) return send(res, 404, { detail: "Not found" });
    return send(res, 200, body);
  }
  return send(res, 502, { detail: "e2e stub: no backend for this path" });
}).listen(port, "127.0.0.1", () => {
  console.log(`public academy stub listening on ${port}`);
});
