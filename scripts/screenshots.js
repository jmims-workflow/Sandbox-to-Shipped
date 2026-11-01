// Capture the README screenshots with Playwright.
// Start the app in demo mode first (sts serve), then run:
//   node scripts/screenshots.js [base-url]
const { chromium } = require('playwright');
const path = require('path');

const base = process.argv[2] || 'http://localhost:8080';
const out = path.join(__dirname, '..', 'docs', 'screenshots');

const shots = [
  ['request-a-tool', '/', 'requester', 1280, false],
  ['not-approved-request', '/requests/r-1044', 'requester', 1280, false],
  ['tool-inventory', '/tools', 'requester', 1280, false],
  ['review-queue', '/review', 'reviewer', 1280, false],
  ['request-page-phone', '/requests/r-1044', 'requester', 390, true],
];

(async () => {
  const browser = await chromium.launch();
  for (const [name, page, role, width, fullPage] of shots) {
    const ctx = await browser.newContext({ viewport: { width, height: width < 500 ? 844 : 900 } });
    await ctx.addCookies([{ name: 'sts_viewer', value: role, url: base }]);
    const p = await ctx.newPage();
    await p.goto(base + page, { waitUntil: 'networkidle' });
    const overflow = await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    if (overflow) console.warn(`${name}: page scrolls sideways`);
    await p.screenshot({ path: path.join(out, `${name}.png`), fullPage });
    console.log(`saved ${name}.png`);
    await ctx.close();
  }
  await browser.close();
})();
