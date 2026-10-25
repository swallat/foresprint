// Regenerates the README screenshots from the frontend's mock data (invented team "Atlas").
//   cd go/internal/desktop/frontend && npx vite build --mode mock --outDir /tmp/mockdist
//   (cd /tmp/mockdist && python3 -m http.server 4173 &)
//   PLAYWRIGHT=<path to playwright-core> CHROME=<path to chrome> node scripts/screenshots.cjs
const { chromium } = require(process.env.PLAYWRIGHT || 'playwright-core');
const out = 'docs/assets/screenshots';
const pages = [
  { name: 'today', hash: '/today' },
  { name: 'preplan', hash: '/sprint/preplan' },
  { name: 'forecast', hash: '/forecast', height: 790 },
  { name: 'analysis', hash: '/forecast?tab=when', click: 'text=Calculate', height: 910 },
  { name: 'projects', hash: '/projects' },
  { name: 'backlog', hash: '/backlog' },
  { name: 'plan', hash: '/sprint/plan' },
  { name: 'storage', hash: '/settings/storage' },
  { name: 'browser', hash: '/settings/browser', height: 440 },
];
(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROME });
  for (const scheme of ['light', 'dark']) {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 940 }, colorScheme: scheme });
    const p = await ctx.newPage();
    for (const pg of pages) {
      await p.goto('http://localhost:4173/#' + pg.hash);
      await p.reload();
      await p.waitForTimeout(1500);
      if (pg.click) { await p.click(pg.click); await p.waitForTimeout(1500); }
      const path = `${out}/${pg.name}-${scheme}.png`;
      if (pg.full) await p.screenshot({ path, fullPage: true });
      else await p.screenshot({ path, clip: { x: 0, y: 0, width: 1440, height: pg.height || 940 } });
    }
    await ctx.close();
  }
  await browser.close();
})();
