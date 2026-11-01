// Capture the README screenshots with Playwright.
// Start the app in demo mode first (sts serve), then run:
//   node scripts/screenshots.js [base-url]
const { chromium } = require('playwright');
const path = require('path');

const base = process.argv[2] || 'http://localhost:8080';
const out = path.join(__dirname, '..', 'docs', 'screenshots');

// Request a tool with the security questions, both early warnings and the "I need this too" card.
const securityAndNeedToo = async (p) => {
  await p.fill('#task', 'posts for social media from our case studies');
  await p.locator('#task').blur();
  await p.check('input[name="info"][value="customer_contact"]');
  await p.check('input[name="info"][value="sensitive_personal"]');
  await p.check('input[name="sends_without_check"][value="yes"]');
  await p.waitForSelector('text=I need this too');
};

const shots = [
  ['request-a-tool', '/', 'requester', 1280, false],
  ['request-security-need-too', '/', 'requester', 1280, true, securityAndNeedToo],
  ['not-approved-request', '/requests/r-1044', 'requester', 1280, false],
  ['tool-inventory', '/tools', 'requester', 1280, false],
  ['review-queue', '/review', 'reviewer', 1280, false],
  ['request-page-phone', '/requests/r-1044', 'requester', 390, true],
  ['tool-ready-to-ship', '/tools/translation-helper', 'reviewer', 1280, true],
  ['tool-journey', '/tools/webinar-invite-writer', 'requester', 1280, true],
];

(async () => {
  const browser = await chromium.launch();
  for (const [name, page, role, width, fullPage, prepare] of shots) {
    const ctx = await browser.newContext({ viewport: { width, height: width < 500 ? 844 : 900 } });
    await ctx.addCookies([{ name: 'sts_viewer', value: role, url: base }]);
    const p = await ctx.newPage();
    await p.goto(base + page, { waitUntil: 'networkidle' });
    if (prepare) await prepare(p);
    const overflow = await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    if (overflow) console.warn(`${name}: page scrolls sideways`);
    await p.screenshot({ path: path.join(out, `${name}.png`), fullPage });
    console.log(`saved ${name}.png`);
    await ctx.close();
  }
  await browser.close();
})();
