import { test as setup } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

// The e2e web server is `next dev`, so every route is compiled on first
// request. A spec that is the first visitor of a route pays that compile
// inside its own assertion timeouts, which under load fails once and then
// passes on retry — tripping failOnFlakyTests. Warming every app route up
// front removes the whole cold-compile flake class.

function collectRoutes(dir: string, url: string, routes: Set<string>): void {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const name = entry.name;
    if (name === "api" || name.startsWith("_")) continue;
    // Route groups add no URL segment; dynamic segments get a dummy value —
    // any value compiles the route module.
    const segment = name.startsWith("(") ? "" : name.startsWith("[") ? "warmup" : name;
    const childUrl = segment ? `${url}/${segment}` : url;
    const childDir = path.join(dir, name);
    if (fs.existsSync(path.join(childDir, "page.tsx"))) {
      routes.add(childUrl || "/");
    }
    collectRoutes(childDir, childUrl, routes);
  }
}

setup("warm all app routes", async ({ request }) => {
  setup.setTimeout(600_000);
  const appDir = path.resolve(__dirname, "../../app");
  const routes = new Set<string>();
  if (fs.existsSync(path.join(appDir, "page.tsx"))) routes.add("/");
  collectRoutes(appDir, "", routes);
  for (const route of routes) {
    // Status doesn't matter (redirects and 404s still compile the module);
    // only a hung request is worth surfacing, and even that shouldn't fail
    // the suite outright.
    await request.get(route, { timeout: 60_000 }).catch(() => {});
  }
});
