// Check the "Try an example" buttons in a real browser, with JavaScript on.
// Start the app in demo mode first, then run:
//   node scripts/check_examples.js [base-url]
// Prints "ok" and exits 0 when every example fills the form; exits 1 otherwise.
const { chromium } = require('playwright');

const base = process.argv[2] || 'http://localhost:8080';
const examples = [
  { label: 'Follow-up emails', task: 'After a discovery call', team: 'Sales', info: ['customer_contact', 'deal_pricing'],
    shows: 'Call Recap Writer' },
  { label: 'Auto-reply to demo requests', task: 'When someone asks for a demo', team: 'Sales', info: ['customer_contact'],
    shows: 'Asked before', sends: 'yes' },
  { label: 'Social posts from case studies', task: 'Turn each new case study', team: 'Marketing', info: ['public_only'],
    shows: 'I need this too' },
];

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const problems = [];
  await page.goto(base + '/', { waitUntil: 'networkidle' });
  if ((await page.inputValue('#task')) !== '') problems.push('the task box should start empty');
  if (await page.locator('input[name="how_often"]:checked').count()) problems.push('how often should start unanswered');
  for (const ex of examples) {
    await page.goto(base + '/', { waitUntil: 'networkidle' });
    await page.getByRole('link', { name: ex.label, exact: true }).click();
    await page.waitForLoadState('networkidle');
    const task = await page.inputValue('#task');
    if (!task.startsWith(ex.task)) problems.push(`${ex.label}: task is "${task}"`);
    if ((await page.inputValue('#team')) !== ex.team) problems.push(`${ex.label}: team not filled`);
    if (!(await page.locator('input[name="how_often"]:checked').count())) problems.push(`${ex.label}: how often not filled`);
    if (!(await page.locator('input[name="who_uses"]:checked').count())) problems.push(`${ex.label}: who uses not filled`);
    const info = await page.$$eval('input[name="info"]:checked', (els) => els.map((e) => e.value));
    if (info.join(',') !== ex.info.join(',')) problems.push(`${ex.label}: information is ${info}`);
    if (ex.sends) {
      const sends = await page.$eval('input[name="sends_without_check"]:checked', (e) => e.value).catch(() => '');
      if (sends !== ex.sends) problems.push(`${ex.label}: security answer not filled`);
      if (!(await page.locator('#warn-sends_without_check').innerText()).includes('Heads up')) {
        problems.push(`${ex.label}: sends warning not shown`);
      }
    }
    if (!(await page.locator('#match-panel').innerText()).includes(ex.shows)) problems.push(`${ex.label}: no "${ex.shows}"`);
  }
  await browser.close();
  if (problems.length) {
    console.log(problems.join('\n'));
    process.exit(1);
  }
  console.log('ok');
})();
