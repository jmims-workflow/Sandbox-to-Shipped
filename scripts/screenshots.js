// Capture the README screenshots with Playwright.
// Start the app in demo mode first (sts serve), then run:
//   node scripts/screenshots.js [base-url]
const { chromium } = require('playwright');
const path = require('path');

const base = process.argv[2] || 'http://localhost:8080';
const out = path.join(__dirname, '..', 'docs', 'screenshots');

// Request a tool with the security questions, both early warnings and the "I need this too" card.
const securityAndNeedToo = async (p) => {
  await p.check('input[name="info"][value="customer_contact"]');
  await p.check('input[name="info"][value="sensitive_personal"]');
  await p.check('input[name="sends_without_check"][value="yes"]');
  await p.waitForSelector('text=I need this too');
};

// "Here's what would happen next" after sending the Auto-reply example.
const submitExample = async (p) => {
  await p.click('button[value="submit"]');
  await p.waitForLoadState('networkidle');
};

// Just the top of the review queue: pilot slots and Needs a decision.
const topOfQueue = async (p) => {
  const box = await p.locator('.slots-card').boundingBox();
  const end = await p.locator('.needs-card').boundingBox();
  return { x: 0, y: Math.max(0, box.y - 24), width: 1280, height: end.y + end.height + 24 - Math.max(0, box.y - 24) };
};

const shots = [
  ['request-a-tool', '/?example=follow-up-emails', 'requester', 1280, false],
  ['request-security-need-too', '/?example=social-posts', 'requester', 1280, true, securityAndNeedToo],
  ['what-happens-next', '/?example=auto-reply', 'requester', 1280, true, submitExample],
  ['review-slots-revisit', '/review', 'reviewer', 1280, false, null, topOfQueue],
  ['not-approved-request', '/requests/r-1044', 'requester', 1280, false],
  ['tool-inventory', '/tools', 'requester', 1280, false],
  ['review-queue', '/review', 'reviewer', 1280, false],
  ['request-page-phone', '/requests/r-1044', 'requester', 390, true],
  ['tool-ready-to-ship', '/tools/translation-helper', 'reviewer', 1280, true],
  ['tool-journey', '/tools/webinar-invite-writer', 'requester', 1280, true],
];

(async () => {
  const browser = await chromium.launch();
  for (const [name, page, role, width, fullPage, prepare, clipper] of shots) {
    const ctx = await browser.newContext({ viewport: { width, height: width < 500 ? 844 : 900 } });
    await ctx.addCookies([{ name: 'sts_viewer', value: role, url: base }]);
    const p = await ctx.newPage();
    await p.goto(base + page, { waitUntil: 'networkidle' });
    if (prepare) await prepare(p);
    const overflow = await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    if (overflow) console.warn(`${name}: page scrolls sideways`);
    const clip = clipper ? await clipper(p) : undefined;
    await p.screenshot({ path: path.join(out, `${name}.png`), fullPage: fullPage || !!clip, clip });
    console.log(`saved ${name}.png`);
    await ctx.close();
  }
  await browser.close();
})();
