// 封面、封底并排预览：改 cover/cover.html 或 cover/back.html 之后，用它看版式和断行，不必整本合成。
// 用法：node cover_preview.mjs <项目目录> [输出.png]
// 默认输出到 <项目目录>/build/cover_preview.png。页面按 640×920 像素（160:230）渲染，
// 同时报告每个文字块的上下边界，方便判断有没有压到图形或溢出页面。
// 依赖 playwright（先找项目目录的 node_modules，再找 NODE_PATH），浏览器用本机 Chrome 或 Edge，
// 也可以用 BROWSER_PATH 指定。
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';

const [projectArg, outArg] = process.argv.slice(2);
if (!projectArg) { console.error('用法：node cover_preview.mjs <项目目录> [输出.png]'); process.exit(2); }
const root = path.resolve(projectArg);
let playwright;
for (const base of [root, ...(process.env.NODE_PATH || '').split(path.delimiter).filter(Boolean), path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'))]) {
  try { playwright = createRequire(path.join(base, 'noop.js'))('playwright'); break; } catch { /* 下一个 */ }
}
if (!playwright) { console.error('找不到 playwright：在项目目录 npm install playwright'); process.exit(2); }
const browserPath = process.env.BROWSER_PATH || [
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/usr/bin/google-chrome', '/usr/bin/chromium',
].find(p => fs.existsSync(p));

const read = name => { const p = path.join(root, 'cover', name); return fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : ''; };
const front = read('cover.html');
const back = read('back.html');
if (!front && !back) { console.error('cover/ 里没有 cover.html 或 back.html'); process.exit(2); }
const html = `<!doctype html><meta charset="utf-8"><style>
:root{--serif:"Noto Serif SC","Source Han Serif SC","Songti SC",serif;--sans:"Noto Sans SC","Source Han Sans SC","PingFang SC","Microsoft YaHei",sans-serif}
body{margin:0;background:#888;display:flex;gap:20px;padding:20px}
.cover-page{position:relative;overflow:hidden;width:640px;height:920px;flex:none}</style>${front}${back}`;

const out = path.resolve(outArg || path.join(root, 'build', 'cover_preview.png'));
fs.mkdirSync(path.dirname(out), { recursive: true });
const browser = await playwright.chromium.launch(browserPath ? { executablePath: browserPath } : {});
const page = await browser.newPage({ viewport: { width: 1340, height: 960 }, deviceScaleFactor: 1.3 });
await page.setContent(html);
await page.evaluate(() => document.fonts.ready);
await page.waitForTimeout(300);
await page.screenshot({ path: out });
const boxes = await page.evaluate(() => [...document.querySelectorAll('.cover-page')].map(sec => {
  const top = sec.getBoundingClientRect().top;
  return { id: sec.id, blocks: [...sec.querySelectorAll('h1,h2,h3,p,div')].filter(e => e.textContent.trim()).slice(0, 12)
    .map(e => { const r = e.getBoundingClientRect(); return `${e.className || e.tagName}: ${Math.round(r.top - top)}–${Math.round(r.bottom - top)}`; }) };
}));
await browser.close();
for (const b of boxes) console.log(`${b.id}（页面高 920）`, b.blocks.join('；'));
console.log(`预览：${out}`);
