// Screenshot every *.html in DIR at phone width. Run from frontend/:
//   node scripts/email-previews.mjs /path/to/dir
// Pair with backend/v2/tests/fixtures/email_previews/render_previews.py.
import { chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const dir = path.resolve(process.argv[2]);
const browser = await chromium.launch();
for (const f of fs.readdirSync(dir).filter((f) => f.endsWith(".html"))) {
  const page = await browser.newPage({ viewport: { width: 390, height: 800 }, deviceScaleFactor: 2 });
  await page.goto("file://" + path.join(dir, f));
  await page.screenshot({ path: path.join(dir, f.replace(".html", ".png")), fullPage: true });
  console.log("shot", f);
}
await browser.close();
