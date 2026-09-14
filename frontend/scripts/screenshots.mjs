/**
 * Regenerate the README screenshots from the live demo.
 *
 *   node scripts/screenshots.mjs [site-url] [api-url]
 *
 * Signs in through the real API, plants the token where the app keeps it,
 * and captures each role's main screen at a fixed size. Reproducible on
 * purpose: a screenshot that can be regenerated is one that will be, the
 * next time the UI changes.
 */

import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const SITE = process.argv[2] ?? "https://sukuu-pi.vercel.app";
const API = process.argv[3] ?? "https://sukuu-api.onrender.com";
const OUT = new URL("../../docs/screenshots/", import.meta.url);
const PASSWORD = "sukuu-demo";

async function token(email) {
  const response = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ username: email, password: PASSWORD }),
  });
  if (!response.ok) throw new Error(`login failed for ${email}: ${response.status}`);
  return (await response.json()).access_token;
}

async function firstOutstandingBill(bearer) {
  const response = await fetch(`${API}/fee-assignments?outstanding_only=true&limit=1`, {
    headers: { Authorization: `Bearer ${bearer}` },
  });
  return (await response.json()).items[0];
}

async function main() {
  await mkdir(fileURLToPath(OUT), { recursive: true });
  const browser = await chromium.launch();

  const shoot = async ({ name, path, as, width = 1280, height = 800, before }) => {
    const context = await browser.newContext({
      viewport: { width, height },
      deviceScaleFactor: 2,
      colorScheme: "light",
    });
    if (as) {
      const bearer = await token(as);
      await context.addInitScript((value) => localStorage.setItem("sukuu.token", value), bearer);
    }
    const page = await context.newPage();
    await page.goto(`${SITE}${path}`, { waitUntil: "networkidle" });
    if (before) await before(page);
    // Let skeletons resolve and the chart's entrance animation finish.
    await page.waitForTimeout(1200);
    await page.screenshot({ path: fileURLToPath(new URL(`${name}.png`, OUT)), fullPage: false });
    await context.close();
    console.log(`  ${name}.png`);
  };

  const bursar = await token("bursar@sukuu.demo");
  const bill = await firstOutstandingBill(bursar);

  await shoot({ name: "login", path: "/login" });
  await shoot({ name: "dashboard", path: "/dashboard", as: "admin@sukuu.demo" });
  await shoot({
    name: "parent-fees",
    path: "/my-children/1",
    as: "parent@sukuu.demo",
    before: async (page) => {
      await page.getByRole("button", { name: "Pay" }).first().click();
    },
  });
  await shoot({
    name: "bursar-collections",
    path: "/collections",
    as: "bursar@sukuu.demo",
    before: async (page) => {
      await page.getByRole("button", { name: "Record cash" }).first().click();
    },
  });
  await shoot({
    name: "payment-confirmed",
    // paid_before below the real figure, so the page shows its confirmed
    // state - the same thing a parent sees once the webhook has landed.
    path: `/payments/success?student=${bill.student.id}&fee=${bill.id}&paid_before=0.00`,
    as: "parent@sukuu.demo",
  });
  await shoot({ name: "students", path: "/students", as: "admin@sukuu.demo" });
  await shoot({
    name: "mobile-collections",
    path: "/collections",
    as: "bursar@sukuu.demo",
    width: 390,
    height: 844,
  });

  await browser.close();
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
