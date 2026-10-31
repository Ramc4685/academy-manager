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
//
// Lane B4: `POST /api/v2/public/trial-requests` (reached through the Next
// BFF proxy, which forwards the browser's user agent, so the same fixture
// picks the behaviour). It mirrors the real endpoint's shapes: 409
// Public.TrialsClosed when the fixture's trials are closed (or the name is
// "Closed Race", to exercise the page-open-while-switched-off case), 422
// Public.InvalidTrialRequest with details.fields for missing fields, else
// the one acknowledgement. The last accepted body per fixture is readable at
// /__last-trial?fixture=<name>.

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
const lastTrial = new Map();

function readJson(req) {
  return new Promise((resolve) => {
    let raw = "";
    req.on("data", (chunk) => {
      raw += chunk;
    });
    req.on("end", () => {
      try {
        resolve(JSON.parse(raw || "null"));
      } catch {
        resolve(null);
      }
    });
  });
}

function trialError(res, status, code, message, details = {}) {
  send(res, status, { error: { code, message, details } });
}

async function handleTrialRequest(req, res, name) {
  const body = await readJson(req);
  const page = fixtures[name];
  if (!page || page.state !== "published") return send(res, 404, { detail: "Not found" });
  if (page.page.trials_open === false || body?.name === "Closed Race") {
    return trialError(
      res,
      409,
      "Public.TrialsClosed",
      "Free trials are paused right now. You can still register for a class with open places.",
    );
  }
  if (!body || typeof body !== "object") {
    return trialError(res, 422, "Public.InvalidTrialRequest", "Some details need another look.", {
      fields: { form: "The form could not be read. Please try again." },
    });
  }
  const fields = {};
  if (!String(body.name ?? "").trim()) fields.name = "Enter your name.";
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(String(body.email ?? "").trim())) {
    fields.email = "Enter an email address like name@example.com.";
  }
  if (!String(body.player_age ?? "").trim()) fields.player_age = "Enter the player's age.";
  if (body.contact_about_request !== true) {
    fields.contact_about_request =
      "Tick this box so the academy can contact you about your request.";
  }
  if (Object.keys(fields).length > 0) {
    return trialError(res, 422, "Public.InvalidTrialRequest", "Some details need another look.", {
      fields,
    });
  }
  if (!String(body.website ?? "").trim()) lastTrial.set(name, body);
  res.writeHead(200, { "content-type": "application/json", "cache-control": "no-store" });
  res.end(JSON.stringify({ state: "received" }));
}
const FIXTURE_PATTERN = /cm-e2e-public-fixture\/([a-z_]+)/;

function send(res, status, body) {
  res.writeHead(status, { "content-type": "application/json", vary: "Host" });
  res.end(JSON.stringify(body));
}

createServer((req, res) => {
  const url = new URL(req.url ?? "/", "http://stub.local");
  if (url.pathname === "/__health") return send(res, 200, { ok: true });
  if (url.pathname === "/__last-trial") {
    return send(res, 200, lastTrial.get(url.searchParams.get("fixture")) ?? null);
  }
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
  if (req.method === "POST" && url.pathname === "/api/v2/public/trial-requests") {
    const name = FIXTURE_PATTERN.exec(req.headers["user-agent"] ?? "")?.[1] ?? "unknown";
    return void handleTrialRequest(req, res, name);
  }
  return send(res, 502, { detail: "e2e stub: no backend for this path" });
}).listen(port, "127.0.0.1", () => {
  console.log(`public academy stub listening on ${port}`);
});
