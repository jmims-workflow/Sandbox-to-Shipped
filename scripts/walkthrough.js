// Record the full journey the public site can't show, because it saves nothing.
//
//   node scripts/walkthrough.js
//
// It starts the app on a local copy in live mode with STS_FAKE_CLAUDE=1 (a stand-in for Claude, so the run
// is repeatable and needs no key), a fresh temporary DATA_DIR loaded with the demo data, and STS_PILOT_SLOTS=4
// so one pilot slot is free. It saves docs/walkthrough.mp4 and docs/walkthrough.gif (with ffmpeg) or, without
// ffmpeg, docs/walkthrough.webm. The caption bar at the top of each page is added here, not by the app.
// Development only: this is never run in GitHub Actions.
const { chromium } = require('playwright');
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const net = require('net');

const ROOT = path.join(__dirname, '..');
const DOCS = path.join(ROOT, 'docs');
const PYTHON = process.env.PYTHON || 'python3';
const SIZE = { width: 1280, height: 800 };
const GIF_LIMIT = 10 * 1024 * 1024;

const REQUESTER = 'Jordan Lee';
const TOOL_NAME = 'Discovery Follow-up Writer';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function freePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
    srv.on('error', reject);
  });
}

function appEnv(dataDir, port) {
  const env = { ...process.env, STS_MODE: 'live', STS_FAKE_CLAUDE: '1', DATA_DIR: dataDir, STS_PILOT_SLOTS: '4',
    PORT: String(port) };
  delete env.ANTHROPIC_API_KEY; // The app refuses to start with a real key next to the stand-in.
  return env;
}

async function waitForApp(base, server) {
  for (let i = 0; i < 100; i++) {
    if (server.exitCode !== null) throw new Error('The app stopped before it started. See the output above.');
    try {
      const r = await fetch(base + '/health');
      if (r.ok) return;
    } catch (e) { /* not up yet */ }
    await sleep(200);
  }
  throw new Error('The app did not start in time.');
}

// A caption bar at the top of every page. It is kept in sessionStorage so it survives page loads.
const CAPTION_SCRIPT = () => {
  const show = () => {
    const text = sessionStorage.getItem('wt-caption');
    if (!text || !document.body) return;
    let bar = document.getElementById('wt-caption');
    if (!bar) {
      bar = document.createElement('div');
      bar.id = 'wt-caption';
      bar.setAttribute('aria-hidden', 'true');
      bar.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99999;background:#14213d;color:#fff;'
        + 'font:600 20px/1.35 system-ui,sans-serif;padding:14px 24px;box-shadow:0 2px 8px rgba(0,0,0,.25)';
      document.body.appendChild(bar);
      document.body.style.paddingTop = '64px';
    }
    bar.textContent = text;
  };
  window.__wtShow = show;
  document.addEventListener('DOMContentLoaded', show);
};

async function caption(page, text, hold = 2600) {
  await page.evaluate((t) => { sessionStorage.setItem('wt-caption', t); window.__wtShow(); }, text);
  await sleep(hold);
}

async function show(page, selector, hold = 2600) {
  const el = page.locator(selector).first();
  await el.scrollIntoViewIfNeeded();
  // Leave room under the caption bar.
  await page.evaluate(() => window.scrollBy(0, -120));
  await sleep(hold);
}

async function type(page, selector, text) {
  const el = page.locator(selector);
  await el.scrollIntoViewIfNeeded();
  await el.fill('');
  await el.pressSequentially(text, { delay: 12 });
}

async function switchTo(page, role) {
  await page.locator(`button[name="role"][value="${role}"]:visible`).first().click();
  await page.waitForLoadState('networkidle');
}

async function expectText(page, text) {
  if (!(await page.getByText(text, { exact: false }).count())) {
    throw new Error(`Expected to see: ${text}`);
  }
}

async function record(base, videoDir) {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: SIZE, recordVideo: { dir: videoDir, size: SIZE } });
  await ctx.addInitScript(CAPTION_SCRIPT);
  const page = await ctx.newPage();
  page.setDefaultTimeout(15000);

  // 1. A requester sends a request that uses customer details, unsure which AI service.
  await page.goto(base + '/welcome?next=/', { waitUntil: 'networkidle' });
  await caption(page, `This is a local copy that saves. First, a requester: ${REQUESTER} from Sales.`, 1500);
  await type(page, 'input[name="name"]', REQUESTER);
  await page.locator('form[action="/welcome"] button[type="submit"]').click();
  await page.waitForLoadState('networkidle');
  await switchTo(page, 'requester');
  await caption(page, '1. The requester fills the form from an example: follow-up emails after a discovery call.');
  await page.goto(base + '/?example=follow-up-emails', { waitUntil: 'networkidle' });
  await caption(page, '1. It uses customer details and deal pricing, so security asks a few questions.', 1200);
  await show(page, '#security-questions', 1200);
  await page.selectOption('#ai_service', 'not_sure');
  await caption(page, '1. Which AI service? The requester answers "Not sure".', 2200);
  await page.locator('button[name="action"][value="submit"]').click();
  await page.waitForLoadState('networkidle');
  await expectText(page, 'a person from security will review this');
  await caption(page, '1. Sent. Security screening goes to a person, because the requester was not sure.', 1000);
  await show(page, '#steps-h', 3200);
  const requestUrl = page.url().split('?')[0];
  const requestId = requestUrl.split('/requests/')[1];

  // 2. A reviewer tries to approve before the security screening is done.
  await switchTo(page, 'reviewer');
  await page.goto(`${base}/review/${requestId}`, { waitUntil: 'networkidle' });
  await caption(page, '2. Now the same person switches to Reviewer and opens the request.', 2600);
  await show(page, 'legend#security_check', 1200);
  await caption(page, '2. Security screening is still Needed. The reviewer chooses Approve anyway.', 1200);
  await page.check('input[name="already_exists"][value="no"]');
  await page.check('input[name="sends_without_check"][value="no"]');
  await page.check('input[name="outcome"][value="approve"]');
  await type(page, '#tool_name', TOOL_NAME);
  await type(page, '#tool_purpose', 'Turns discovery call notes into a follow-up email a rep checks and sends.');
  await type(page, '#tool_owner', 'Priya Shah');
  await type(page, '#tool_owner_team', 'Sales');
  await page.check('#owner_agreed');
  await type(page, '#reason', 'Approved as a pilot for Sales. A rep checks every email before it goes out, '
    + 'and Call Recap Writer does not cover discovery calls.');
  await type(page, '#what_would_change', 'If reps stop checking emails before sending, we would look again.');
  await page.locator('button[name="action"][value="send"]').click();
  await page.waitForLoadState('networkidle');
  await expectText(page, 'Finish the security screening before approving.');
  await caption(page, '2. The server refuses: "Finish the security screening before approving."', 600);
  await show(page, '.notice-error', 3600);

  // 3. Security screening done, then approve as a pilot with an owner who agreed.
  await caption(page, '3. Security has screened it. The reviewer records the screening as Done.', 800);
  await show(page, 'legend#security_check', 800);
  await page.check('input[name="security_check"][value="done"]');
  await sleep(1400);
  if (!(await page.locator('#owner_agreed').isChecked())) await page.check('#owner_agreed');
  await caption(page, '3. Approve, with an owner who has agreed. Every new tool starts as a pilot.', 800);
  await show(page, '#owner_agreed', 1800);
  await page.locator('button[name="action"][value="send"]').click();
  await page.waitForLoadState('networkidle');
  await expectText(page, 'Decision sent.');
  await caption(page, '3. Decision sent.', 2000);
  await page.goto(base + '/tools?status=being_tried', { waitUntil: 'networkidle' });
  await expectText(page, TOOL_NAME);
  await caption(page, `3. ${TOOL_NAME} is in the tool inventory, In pilot.`, 600);
  await show(page, `text=${TOOL_NAME}`, 3200);

  // 4. Ship it before the ready to ship check is complete.
  await page.locator(`a:has-text("${TOOL_NAME}")`).first().click();
  await page.waitForLoadState('networkidle');
  const toolUrl = page.url();
  await caption(page, '4. Ready to ship? Two of the four items are still open, so Ship it is turned off.', 600);
  await show(page, 'text=Ready to ship?', 3000);
  await caption(page, '4. The recording turns the button back on and presses it, to show the server checks too.', 600);
  const ship = page.locator(`form[action$="/ship"] button[type="submit"]`);
  await ship.scrollIntoViewIfNeeded();
  await page.evaluate(() => window.scrollBy(0, -200));
  await sleep(1200);
  await ship.evaluate((b) => b.removeAttribute('disabled'));
  await sleep(600);
  await ship.click();
  await page.waitForLoadState('networkidle');
  await caption(page, '4. Refused: the ready to ship check isn\'t complete.', 600);
  await show(page, '.notice-error', 3600);

  // 5. Complete the check and ship it.
  await page.goto(toolUrl, { waitUntil: 'networkidle' });
  await caption(page, '5. After the pilot, the reviewer answers the ready to ship questions.', 800);
  await show(page, 'input[name="kept_using"]', 600);
  await page.check('input[name="kept_using"][value="regularly"]');
  await type(page, '#went_wrong', 'Nothing. Two drafts needed a pricing fix before sending.');
  await type(page, '#how_tested', 'Five reps used it on 40 discovery calls and checked every email before sending.');
  await sleep(800);
  await page.locator('form[action$="/check"] button[type="submit"]').click();
  await page.waitForLoadState('networkidle');
  await caption(page, '5. 4 of 4 ready. Now Ship it is on.', 600);
  await show(page, 'text=Ready to ship?', 2600);
  await page.locator('form[action$="/ship"] input[name="to_status"][value="approved"]').check();
  await page.locator('form[action$="/ship"] button[type="submit"]').click();
  await page.waitForLoadState('networkidle');
  await page.goto(toolUrl, { waitUntil: 'networkidle' });
  await expectText(page, 'Approved');
  await caption(page, `5. Shipped. ${TOOL_NAME} is Approved, with its journey and how it earned approval.`, 3000);
  await page.mouse.wheel(0, 500);
  await sleep(2600);
  await page.mouse.wheel(0, 600);
  await sleep(2600);

  // 6. The requester sees the decision.
  await switchTo(page, 'requester');
  await page.goto(base + '/requests', { waitUntil: 'networkidle' });
  await caption(page, '6. Back as the requester: My requests shows the decision.', 2400);
  await page.goto(requestUrl, { waitUntil: 'networkidle' });
  await expectText(page, 'If reps stop checking emails before sending');
  await caption(page, '6. The decision, its reason and what would change the answer.', 800);
  await show(page, 'text=If reps stop checking emails before sending', 4200);

  await page.close();
  const video = await page.video().path();
  await ctx.close();
  await browser.close();
  return video;
}

function haveFfmpeg() {
  return spawnSync('ffmpeg', ['-version'], { stdio: 'ignore' }).status === 0;
}

function ffmpeg(args) {
  const r = spawnSync('ffmpeg', ['-y', '-loglevel', 'error', ...args], { stdio: 'inherit' });
  if (r.status !== 0) throw new Error('ffmpeg failed');
}

function save(video) {
  if (!haveFfmpeg()) {
    const out = path.join(DOCS, 'walkthrough.webm');
    fs.copyFileSync(video, out);
    console.log(`ffmpeg is not installed, so the Playwright video is kept as ${out}`);
    return;
  }
  const mp4 = path.join(DOCS, 'walkthrough.mp4');
  const gif = path.join(DOCS, 'walkthrough.gif');
  ffmpeg(['-i', video, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '26', '-movflags', '+faststart', mp4]);
  // Try smaller settings until the GIF fits under the limit.
  for (const [fps, width] of [[6, 960], [5, 800], [4, 720], [4, 640]]) {
    const filter = `fps=${fps},scale=${width}:-1:flags=lanczos,split[a][b];`
      + '[a]palettegen=max_colors=96:stats_mode=diff[p];[b][p]paletteuse=dither=none:diff_mode=rectangle';
    ffmpeg(['-i', video, '-vf', filter, '-loop', '0', gif]);
    const size = fs.statSync(gif).size;
    console.log(`walkthrough.gif: ${(size / 1024 / 1024).toFixed(1)} MB at ${fps} fps, ${width}px`);
    if (size < GIF_LIMIT) break;
  }
  if (fs.statSync(gif).size >= GIF_LIMIT) throw new Error('walkthrough.gif is still 10 MB or more');
  console.log(`saved ${mp4} and ${gif}`);
}

(async () => {
  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'sts-walkthrough-'));
  const dataDir = path.join(work, 'data');
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const env = appEnv(dataDir, port);
  const seed = spawnSync(PYTHON, ['-m', 'sts.cli', 'seed', '--reset', '--yes'], { cwd: ROOT, env, stdio: 'inherit' });
  if (seed.status !== 0) throw new Error('Could not load the demo data.');
  const server = spawn(PYTHON, ['-m', 'sts.cli', 'serve', '--host', '127.0.0.1', '--port', String(port)],
    { cwd: ROOT, env, stdio: 'inherit' });
  let failed = false;
  try {
    await waitForApp(base, server);
    const video = await record(base, path.join(work, 'video'));
    save(video);
  } catch (e) {
    failed = true;
    console.error(e);
  } finally {
    server.kill();
    fs.rmSync(work, { recursive: true, force: true });
  }
  process.exit(failed ? 1 : 0);
})();
