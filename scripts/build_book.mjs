#!/usr/bin/env node
// 把 zh/*.md 合成单文件 HTML 和带目录、书签的 PDF。
// 用法：node build_book.mjs <项目目录>           出两份 PDF：带注释的完整版和无注释阅读版
//       node build_book.mjs <项目目录> --full    只出完整版（调版面时省时间）
//       node build_book.mjs <项目目录> --reading 只出阅读版
// 环境变量：BROWSER_PATH、PYTHON、NODE_PATH、CODEX_RUNTIME_DIR、BOOK_FONT_DIR、BOOK_NO_FONT_SUBSET。
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const skillDir = path.resolve(scriptDir, '..');
const args = process.argv.slice(2);
const fullOnly = args.includes('--full');
const reading = args.includes('--reading') && !fullOnly;
const projectArg = args.find(a => !a.startsWith('--'));
if (!projectArg) fail('用法：node build_book.mjs <项目目录> [--full | --reading]');
const root = path.resolve(projectArg);
if (!reading && !fullOnly) {
  // 默认交付两份 PDF，各跑一遍，任何一份失败都算失败。
  const results = ['--full', '--reading'].map(flag =>
    spawnSync(process.execPath, [process.argv[1], root, flag], { stdio: 'inherit' }).status);
  if (results.some(code => code !== 0)) {
    console.error(`有版本没有通过：完整版退出码 ${results[0]}，阅读版退出码 ${results[1]}`);
    process.exit(1);
  }
  console.log('两份 PDF 都已生成并通过校验：完整版和阅读版。');
  process.exit(0);
}
const projectPath = path.join(root, 'project.json');
if (!fs.existsSync(projectPath)) fail(`找不到 ${projectPath}`);
const project = JSON.parse(fs.readFileSync(projectPath, 'utf8').replace(/^﻿/, ''));
const build = project.build || {};
const home = process.env.USERPROFILE || process.env.HOME || '';
const codexRuntime = process.env.CODEX_RUNTIME_DIR || path.join(home, '.cache/codex-runtimes/codex-primary-runtime/dependencies');
const require = createRequire(import.meta.url);

function fail(message) {
  console.error(message);
  process.exit(1);
}

const environment = {};
async function dependency(name) {
  // 依次找：项目目录、NODE_PATH、脚本目录、Codex 运行环境。
  const dirs = [root, ...(process.env.NODE_PATH || '').split(path.delimiter).filter(Boolean), scriptDir, path.join(codexRuntime, 'node/node_modules')];
  for (const dir of dirs) {
    try {
      const resolved = require.resolve(name, { paths: [dir] });
      environment[name] = resolved;
      return await import(pathToFileURL(resolved).href);
    } catch { /* 下一个 */ }
  }
  fail(`缺少依赖 ${name}。在项目目录运行 npm install marked@17.0.5 playwright@1.62.1，或设置 NODE_PATH。`);
}

function findPython(modules) {
  const candidates = [process.env.PYTHON, path.join(codexRuntime, 'python/python.exe'), path.join(codexRuntime, 'python/bin/python3')]
    .filter(c => c && fs.existsSync(c)).map(c => [c]);
  for (const c of [...candidates, ['py', '-3'], ['python3'], ['python']]) {
    const r = spawnSync(c[0], [...c.slice(1), '-c', `import ${modules}`], { encoding: 'utf8' });
    if (r.status === 0) return c;
  }
  return null;
}

function findBrowser() {
  if (process.env.BROWSER_PATH) return process.env.BROWSER_PATH;
  const list = [
    path.join(process.env.ProgramFiles || '', 'Google/Chrome/Application/chrome.exe'),
    path.join(process.env['ProgramFiles(x86)'] || '', 'Google/Chrome/Application/chrome.exe'),
    path.join(process.env['ProgramFiles(x86)'] || '', 'Microsoft/Edge/Application/msedge.exe'),
    path.join(process.env.ProgramFiles || '', 'Microsoft/Edge/Application/msedge.exe'),
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser',
  ];
  return list.find(p => p && fs.existsSync(p));
}

const python = findPython('pypdf');
if (!python) fail('找不到装了 pypdf 的 Python。运行 python -m pip install pypdf，或设置 PYTHON。');
environment.pypdfPython = python.join(' ');
function runPython(pyArgs) {
  const r = spawnSync(python[0], [...python.slice(1), path.join(scriptDir, 'pdf_finalize.py'), ...pyArgs],
    { cwd: root, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } });
  if (r.status !== 0) throw new Error(`PDF 处理失败：${r.stdout}\n${r.stderr}`);
  return JSON.parse(r.stdout);
}

const { marked } = await dependency('marked');
const playwrightModule = await dependency('playwright');
const { chromium } = playwrightModule.default || playwrightModule;
marked.setOptions({ gfm: true, breaks: false });

const outDir = path.join(root, 'build');
const tempDir = path.join(outDir, 'tmp');
fs.mkdirSync(tempDir, { recursive: true });

const escapeHtml = s => String(s).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
const PENDING = '【原文待核】';
const NOTES_HEADING = /^##\s+注释与引用\s*$/m;
const NOTE_REF = /\\?\[(\d+)\\?\](?!\()|〔(\d+)〕/g;

// ---------- 读章节 ----------
const zhDir = path.join(root, 'zh');
const removedEchoes = [];
const chapterFiles = fs.readdirSync(zhDir).filter(n => n.endsWith('.md')).sort();
if (!chapterFiles.length) fail(`${zhDir} 里没有章节`);
// 全书中文 MD 随成品保留。合并文件有人工修改还没写回时，merge 会拒绝，这里就停下，免得用旧稿出书。
const mergeRun = spawnSync(python[0], [...python.slice(1), path.join(scriptDir, 'booktool.py'), 'merge', root],
  { encoding: 'utf8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } });
if (mergeRun.status !== 0) fail(`${mergeRun.stdout}${mergeRun.stderr}`);
const titleKey = s => s.replace(/^#{1,6}\s*/, '').replace(/^第\s*[\d一二三四五六七八九十百]+\s*章\s*/, '').replace(/^\d+\s*[.、．]\s*/, '').replace(/\s+/g, '').trim();
const chapters = chapterFiles.map((file, index) => {
  const bytes = fs.readFileSync(path.join(zhDir, file));
  const raw = bytes.toString('utf8').replace(/^﻿/, '').replace(/\r\n?/g, '\n').replace(/^<!--b\d+(?:\s+p\.[^\s>]+)?-->[ \t]*\n?/gm, '');
  const heading = raw.match(/^\s*#\s+([^\n]+)\n?/);
  if (!heading) throw new Error(`${file} 开头没有一级标题`);
  const title = heading[1].trim();
  let body = raw.slice(heading[0].length).trimStart();
  // 只在排版层去掉和主标题重复的旧标题行，不改 MD。
  while (body && titleKey(body.split('\n')[0]) === titleKey(title)) {
    removedEchoes.push({ file, text: body.split('\n')[0] });
    body = body.slice(body.indexOf('\n') < 0 ? body.length : body.indexOf('\n') + 1).trimStart();
  }
  if (/^#\s+/m.test(body)) throw new Error(`${file} 里有多余的一级标题`);
  const cm = title.match(/^第\s*([\d一二三四五六七八九十百]+)\s*章\s*(.*)$/);
  return {
    file, id: `sec-${index + 1}`, title, shortTitle: cm?.[2] || title, number: cm ? `第${cm[1]}章` : '',
    kind: cm ? 'chapter' : 'frontmatter', body, sha256: createHash('sha256').update(bytes).digest('hex'),
  };
});

// ---------- 与台账核对 ----------
const pendingTotal = chapters.reduce((n, c) => n + c.body.split(PENDING).length - 1, 0);
const ledgerPath = path.join(root, 'audit/citations.json');
let audit = null;
if (fs.existsSync(ledgerPath)) {
  const ledger = JSON.parse(fs.readFileSync(ledgerPath, 'utf8').replace(/^﻿/, ''));
  const records = ledger.records || [];
  const expected = records.reduce((n, r) => n + (['partial', 'searched_unresolved'].includes(r.status) || (r.status === 'not_reviewed' && r.has_marker) ? (r.markers ?? 1) : 0), 0);
  if (records.length && expected !== pendingTotal) throw new Error(`台账应有 ${expected} 处待核，正文有 ${pendingTotal} 处。先运行 audit-check。`);
  const counts = {};
  for (const r of records) counts[r.status] = (counts[r.status] || 0) + 1;
  audit = { round: ledger.round, records: records.length, statuses: counts };
}

// ---------- 阅读版去掉译者写的说明 ----------
// 标题要完全相同才算，作者自己的“读者说明”等不受影响。其他文件写进 build.reading_exclude（文件名前缀或标题）。
const TRANSLATOR_TITLE = /^(译者(说明|前言|序|序言|的话|附记|后记|导言|按语)|译后记|译序|译本说明|翻译说明|校译说明|校注说明|校者说明)$/;
const readingExcluded = [];
if (reading) {
  const extra = build.reading_exclude || [];
  for (let i = chapters.length - 1; i >= 0; i--) {
    const c = chapters[i];
    if (TRANSLATOR_TITLE.test(c.title) || extra.some(x => c.file.startsWith(x) || c.title === x)) {
      readingExcluded.unshift(c.file);
      chapters.splice(i, 1);
    }
  }
  if (!chapters.length) throw new Error('阅读版没有剩下任何章节，检查 build.reading_exclude');
}

// ---------- 渲染章节 ----------
const expectBlocks = [];
const noteCrossRefs = [];
function renderChapter(c) {
  const parts = c.body.split(NOTES_HEADING);
  if (parts.length > 2) throw new Error(`${c.file} 有多个注释区`);
  if (/(?:校注|译者注)[：:]/.test(parts[0])) throw new Error(`${c.file} 正文里还有校注，应移入章末注释`);
  let prose = parts[0];
  let notesHtml = '';
  if (reading) {
    // 阅读版只留标了 <!--读者--> 的注释（或用 <!--读者：替代文字--> 给出阅读版的说法），按出现顺序重新编号；其余注号删去。
    const keep = new Map();
    if (parts.length === 2) {
      for (const m of parts[1].matchAll(/^(\d+)\.\s+(.*)$/gm)) {
        const alt = m[2].match(/<!--\s*读者[:：]\s*([\s\S]*?)-->/);
        if (alt || /<!--\s*读者\s*-->/.test(m[2])) keep.set(m[1], (alt ? alt[1] : m[2]).replace(/<!--[\s\S]*?-->/g, '').trim());
      }
    }
    for (const pattern of build.reading_strip || []) prose = prose.replace(new RegExp(pattern, 'g'), '');
    const kept = [];
    prose = prose.replace(NOTE_REF, (match, a, b) => {
      const text = keep.get(a || b);
      if (text === undefined) return '';
      kept.push(text);
      return `⁠<a class="note-ref" id="ref-${c.id}-${kept.length}" href="#note-${c.id}-${kept.length}">[${kept.length}]</a>`;
    }).replaceAll(PENDING, '');
    if (kept.length) notesHtml = `<section class="endnotes" aria-label="注释"><h2>注释</h2><ol>${kept.map((t, i) => `<li id="note-${c.id}-${i + 1}">${marked.parseInline(t)}</li>`).join('')}</ol></section>`;
    for (const m of prose.matchAll(/[见参]注\s*\d+|注释\s*\d+|第\s*\d+\s*条注|译者说明|校注/g)) noteCrossRefs.push(`${c.file}：${m[0]}`);
  } else {
    prose = prose.replace(NOTE_REF, (match, a, b) => `\u2060<a class="note-ref" id="ref-${c.id}-${a || b}" href="#note-${c.id}-${a || b}">[${a || b}]</a>`);
    if (parts.length === 2) {
      let i = 0;
      const notes = marked.parse(parts[1]).replace(/<li>/g, () => `<li id="note-${c.id}-${++i}">`)
        .replaceAll(PENDING, `<span class="editor-note">${PENDING}</span>`);
      notesHtml = `<section class="endnotes" aria-label="注释与引用"><h2>注释与引用</h2>${notes}</section>`;
    }
  }
  let body = marked.parse(prose);
  // 正文插图：相对路径依次在 zh/、source/、项目根目录下找，转成内嵌数据，PDF 和单文件 HTML 都带图
  body = body.replace(/<img src="([^"]+)"/g, (m, src) => {
    if (/^(data:|https?:)/.test(src)) return m;
    const rel = decodeURI(src);
    const file = [zhDir, path.join(root, 'source'), root].map(d => path.join(d, rel)).find(p => fs.existsSync(p));
    if (!file) fail(`${c.file ?? c.id}：找不到正文插图 ${src}（在 zh/、source/、项目根目录下都没有）`);
    return `<img src="${imageData(file)}"`;
  });
  if (!reading) body = body.replaceAll(PENDING, `<span class="editor-note">${PENDING}</span>`);
  body = body.replace(/<p>(?:✦|\*\s*\*\s*\*|\*\*\*)<\/p>/g, '<div class="section-break" aria-hidden="true">✦</div>');
  // 抽样记下正文段，供 PDF 回读比对
  const plain = [...body.matchAll(/<p>(.*?)<\/p>/gs)].map(m => m[1].replace(/<[^>]+>/g, '').replace(/\u2060/g, '').replaceAll('&amp;', '&').replaceAll('&lt;', '<').replaceAll('&gt;', '>').replaceAll('&quot;', '"').replaceAll('&#39;', "'")).filter(t => t.length >= 6);
  for (const t of new Set([plain[0], plain[Math.floor(plain.length / 2)], plain[plain.length - 1]])) if (t) expectBlocks.push(t.slice(0, 30));
  const opener = `<header class="chapter-opener">${c.number ? `<span class="chapter-number">${escapeHtml(c.number)}</span>` : ''}<h1 id="title-${c.id}"><span class="chapter-title">${escapeHtml(c.shortTitle)}</span></h1><div class="opener-rule"></div></header>`;
  return `<section id="${c.id}" class="book-section ${c.kind}">${opener}<div class="chapter-body">${body}</div>${notesHtml}</section>`;
}
const renderedChapters = chapters.map(renderChapter);

// ---------- 封面、版权页、目录 ----------
const coverDir = path.join(root, 'cover');
function imageData(file) {
  const type = { '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp' }[path.extname(file).toLowerCase()];
  return `data:${type};base64,${fs.readFileSync(file).toString('base64')}`;
}
function findCoverImage(stem) {
  for (const ext of ['.png', '.jpg', '.jpeg', '.webp']) {
    const p = path.join(coverDir, stem + ext);
    if (fs.existsSync(p)) return p;
  }
  return null;
}
let coverKind = 'text';
function coverHtml() {
  const html = path.join(coverDir, 'cover.html');
  if (fs.existsSync(html)) { coverKind = 'html'; return fs.readFileSync(html, 'utf8'); }
  const image = findCoverImage('cover');
  if (image) { coverKind = 'image'; return `<section class="cover-page cover-image" id="cover"><img src="${imageData(image)}" alt="封面"></section>`; }
  coverKind = 'text';
  return `<section class="cover-page cover-text" id="cover"><div class="cover-title">${escapeHtml(project.title_zh || project.title_source)}</div>${project.subtitle_zh ? `<div class="cover-subtitle">${escapeHtml(project.subtitle_zh)}</div>` : ''}<div class="cover-author">${escapeHtml(project.author_zh || project.author_source || '')}</div><div class="cover-original">${escapeHtml(project.title_source || '')}</div></section>`;
}
const coverSection = coverHtml();
let backKind = 'none';
function backHtml() {
  const html = path.join(coverDir, 'back.html');
  if (fs.existsSync(html)) {
    const fragment = fs.readFileSync(html, 'utf8');
    if (!fragment.includes('back-cover')) throw new Error('cover/back.html 最外层要写 <section class="cover-page back-cover" id="back-cover">');
    backKind = 'html';
    return fragment;
  }
  const image = findCoverImage('back');
  if (!image) return '';
  backKind = 'image';
  return `<section class="cover-page cover-image back-cover" id="back-cover"><img src="${imageData(image)}" alt="封底"></section>`;
}
const backSection = backHtml();
const title = project.title_zh || project.title_source;
const defaultNote = `正文或注释中的“${PENDING}”表示该处引文或出处尚未落实。`;
const editionSection = `<section class="edition-page" id="edition"><h1>${escapeHtml(title)}</h1>${project.subtitle_zh ? `<p class="edition-meta">${escapeHtml(project.subtitle_zh)}</p>` : ''}<div class="edition-rule"></div>
<p class="edition-meta">${escapeHtml(project.title_source || '')}${project.author_source ? ' · ' + escapeHtml(project.author_source) : ''}</p>
<p>${escapeHtml(build.edition_note || '')}</p>${pendingTotal ? `<p>${escapeHtml(defaultNote)}</p>` : ''}<p>原书版权归原作者及权利方所有。</p></section>`;

function makeHtml(pageMap) {
  const toc = chapters.map(c => `<li><a href="#${c.id}"><span class="toc-title">${c.number ? `<span class="toc-number">${escapeHtml(c.number)}</span>` : ''}${escapeHtml(c.shortTitle)}</span><span class="toc-pg">${pageMap?.[c.id] ?? ''}</span></a></li>`).join('');
  const css = fs.existsSync(path.join(root, 'book.css')) ? fs.readFileSync(path.join(root, 'book.css'), 'utf8') : fs.readFileSync(path.join(skillDir, 'assets/book.css'), 'utf8');
  const w = build.page_width_mm || 160, h = build.page_height_mm || 230;
  const head = (build.running_head || title).replaceAll("'", "\\'");
  const pageCss = `@page{size:${w}mm ${h}mm;@top-center{content:'${head}';font-family:var(--sans,sans-serif);font-size:7pt;color:#666}@bottom-center{content:counter(page);font-size:8pt;color:#666}}
@page cover{size:${w}mm ${h}mm;margin:0;@top-center{content:''}@bottom-center{content:''}}
@page front{@top-center{content:''}@bottom-center{content:''}}
.cover-page{width:${w}mm;height:${h}mm}`;
  return `<!doctype html><html lang="zh-Hans"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escapeHtml(title)}</title><style>${fontCss}\n${css}\n${pageCss}</style></head><body><main id="book">
${coverSection}${reading ? '' : editionSection}
<section class="toc-page" id="book-toc"><h1>目录</h1><ol>${toc}</ol>${reading && build.reading_note ? `<p class="reading-note">${escapeHtml(build.reading_note)}</p>` : ''}</section>
${renderedChapters.join('\n')}
${backSection}</main></body></html>`;
}

// ---------- 字体子集 ----------
const fontNote = { embedded: false, reason: '' };
function findFont(names) {
  const dirs = [path.join(root, 'fonts'), process.env.BOOK_FONT_DIR, 'C:/Windows/Fonts', path.join(home, 'AppData/Local/Microsoft/Windows/Fonts'),
    path.join(home, 'Library/Fonts'), '/Library/Fonts', path.join(home, '.local/share/fonts'), '/usr/share/fonts/truetype/noto', '/usr/share/fonts/opentype/noto'].filter(Boolean);
  for (const d of dirs) for (const n of names) if (fs.existsSync(path.join(d, n))) return path.join(d, n);
  return null;
}
function fontFaces() {
  if (process.env.BOOK_NO_FONT_SUBSET) { fontNote.reason = '已设置 BOOK_NO_FONT_SUBSET'; return ''; }
  const fontPython = findPython('fontTools');
  if (!fontPython) { fontNote.reason = '没有 fontTools'; return ''; }
  environment.fontToolsPython = fontPython.join(' ');
  const sources = [['BookSerif', findFont(['NotoSerifSC-VF.ttf', 'NotoSerifSC[wght].ttf', 'NotoSerifSC-Regular.ttf']), '200 900'],
    ['BookSans', findFont(['NotoSansSC-VF.ttf', 'NotoSansSC[wght].ttf', 'NotoSansSC-Regular.ttf']), '100 900']];
  if (sources.some(s => !s[1])) { fontNote.reason = '找不到 Noto Serif SC / Noto Sans SC'; return ''; }
  const text = [...new Set([project.title_zh, project.subtitle_zh, project.author_zh, project.title_source, project.author_source, build.edition_note, build.running_head, defaultNote,
    '封面目录原书版权归原作者及权利方所有注释与引用第章阅读版', ...chapters.map(c => c.title + c.body), coverKind === 'html' ? coverSection : '', backKind === 'html' ? backSection : ''].filter(Boolean).join(''))].join('');
  const key = createHash('sha256').update(text).digest('hex').slice(0, 16);
  const textPath = path.join(tempDir, `chars-${key}.txt`);
  fs.writeFileSync(textPath, text, 'utf8');
  const faces = [];
  for (const [family, source, weight] of sources) {
    const target = path.join(tempDir, `${family}-${key}.font`);
    if (!fs.existsSync(target)) {
      const r = spawnSync(fontPython[0], [...fontPython.slice(1), path.join(scriptDir, 'subset_fonts.py'), textPath, source, target], { encoding: 'utf8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } });
      if (r.status !== 0) { fontNote.reason = `子集化失败：${r.stderr.slice(-300)}`; return ''; }
    }
    const data = fs.readFileSync(target);
    const isWoff2 = data.subarray(0, 4).toString('latin1') === 'wOF2';
    faces.push(`@font-face{font-family:${family};src:url(data:font/${isWoff2 ? 'woff2' : 'ttf'};base64,${data.toString('base64')}) format('${isWoff2 ? 'woff2' : 'truetype'}');font-weight:${weight};font-display:block}`);
  }
  fontNote.embedded = true;
  return faces.join('\n');
}
const fontCss = fontFaces();

// ---------- 排版循环 ----------
const editionSuffix = reading ? '_阅读版' : '';
const baseName = String(build.output_name || title).replace(/[\\/:*?"<>|]/g, '_') + editionSuffix;
const htmlPath = path.join(outDir, `${baseName}.html`);
const pdfPath = path.join(outDir, `${baseName}.pdf`);
const draftPath = path.join(tempDir, `layout${editionSuffix}.pdf`);
const sectionsPath = path.join(tempDir, 'sections.json');
fs.writeFileSync(sectionsPath, JSON.stringify([{ id: 'book-toc', title: '目录', shortTitle: '目录' }, ...chapters.map(({ id, title, shortTitle }) => ({ id, title, shortTitle }))]));

const executablePath = findBrowser();
if (!executablePath) fail('找不到 Chrome 或 Edge，请设置 BROWSER_PATH。');
const browser = await chromium.launch({ headless: true, executablePath });
let exitCode = 0;
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  let pageMap = null, stable = false, passes = 0;
  let dom = null;
  for (let pass = 1; pass <= 4; pass++) {
    passes = pass;
    fs.writeFileSync(htmlPath, makeHtml(pageMap), 'utf8');
    await page.goto(pathToFileURL(htmlPath).href, { waitUntil: 'load' });
    await page.evaluate(() => document.fonts.ready);
    await page.emulateMedia({ media: 'print' });
    dom = await page.evaluate(() => {
      const errors = [];
      const ids = [...document.querySelectorAll('[id]')].map(e => e.id);
      if (new Set(ids).size !== ids.length) errors.push('HTML id 重复');
      for (const a of document.querySelectorAll('a[href^="#"]')) if (!document.getElementById(a.hash.slice(1))) errors.push(`断开的链接 ${a.hash}`);
      const bodyText = [...document.querySelectorAll('.chapter-body')].map(e => e.textContent).join('');
      return { errors, residualRefs: (bodyText.match(/\[\d+\]|〔\d+〕/g) || []).length, noteRefs: document.querySelectorAll('.note-ref').length, endnotes: document.querySelectorAll('.endnotes ol > li').length, pendingMarkers: document.querySelectorAll('.editor-note').length };
    });
    if (dom.errors.length) throw new Error(`HTML 校验失败：${JSON.stringify(dom.errors.slice(0, 20))}`);
    await page.pdf({ path: draftPath, printBackground: true, preferCSSPageSize: true, tagged: true, outline: true });
    const next = runPython(['page-map', draftPath, sectionsPath]);
    console.log(`排版第 ${pass} 轮：${chapters.length} 章，最后一章在第 ${Object.values(next).at(-1)} 页`);
    if (pageMap && JSON.stringify(next) === JSON.stringify(pageMap)) { stable = true; break; }
    pageMap = next;
  }
  if (!stable) throw new Error('目录页码四轮内没有稳定。');
  const outline = [{ title: '封面', page: 1 }, { title: '目录', page: pageMap['book-toc'] }, ...chapters.map(c => ({ title: c.title, page: pageMap[c.id] })), ...(backKind === 'none' ? [] : [{ title: '封底', page: -1 }])];
  const configPath = path.join(tempDir, 'finalize.json');
  fs.writeFileSync(configPath, JSON.stringify({
    outline,
    metadata: { '/Title': title, '/Author': project.author_zh || project.author_source || '', '/Subject': reading ? '中文译本（阅读版）' : '中文译本', '/Creator': 'book-translation skill' },
    expectBlocks,
    hasBackCover: backKind !== 'none',
  }));
  const report = runPython(['finalize', draftPath, pdfPath, configPath]);
  const problems = [];
  if (report.replacementCharacters) problems.push(`替换字符 ${report.replacementCharacters} 个`);
  if (report.unembeddedFonts.length) problems.push(`未嵌入字体：${report.unembeddedFonts.join(', ')}`);
  if (report.blankPages.length) problems.push(`空白页：${report.blankPages.join(', ')}`);
  if (report.sampleBlocksMissingFromPdf.length) problems.push(`抽样段落未在 PDF 中找到 ${report.sampleBlocksMissingFromPdf.length} 处`);
  if (!reading && dom.noteRefs !== dom.endnotes) problems.push(`注号 ${dom.noteRefs} 个，注释 ${dom.endnotes} 条`);
  if (!reading && dom.pendingMarkers !== pendingTotal) problems.push('HTML 中的待核标记数量不对');
  if (reading && report.pendingMarkersInPdf) problems.push('阅读版里还有待核标记');
  if (reading && dom.noteRefs !== dom.endnotes) problems.push(`阅读版注号 ${dom.noteRefs} 个，注释 ${dom.endnotes} 条`);
  if (reading && dom.residualRefs !== dom.noteRefs) problems.push(`阅读版正文还有 ${dom.residualRefs - dom.noteRefs} 处多余的注号`);
  await page.emulateMedia({ media: 'screen' });
  await page.setViewportSize({ width: 390, height: 844 });
  const mobileOverflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
  if (mobileOverflow) problems.push('HTML 在手机宽度下横向溢出');
  const warnings = [];
  if (backKind === 'none') warnings.push('没有封底（cover/back.html 或 cover/back.png）');
  if (noteCrossRefs.length) warnings.push(`阅读版去掉了注释和译者说明，这些地方还在提到它们，请改写：${noteCrossRefs.slice(0, 10).join('；')}`);
  if (audit?.statuses?.not_reviewed) warnings.push(`台账还有 ${audit.statuses.not_reviewed} 条引文没有核查`);
  if (!fontNote.embedded) warnings.push(`未嵌入字体子集（${fontNote.reason}）：HTML 依赖本机字体`);
  if (report.radicalCharsInPdfText) warnings.push(`PDF 文字层有 ${report.radicalCharsInPdfText} 个部首码位，复制和搜索可能对不上。装 fonttools 和 Noto SC 字体后重建可解决`);
  const validation = {
    status: problems.length ? 'failed' : 'passed', problems, warnings, fontSubset: fontNote, edition: reading ? 'reading' : 'full', ...report,
    chapters: chapters.length, noteRefs: dom.noteRefs, endnotes: dom.endnotes, pendingMarkers: reading ? 0 : pendingTotal,
    readingExcluded, paginationPasses: passes, cover: coverKind, backCover: backKind, environment: { ...environment, browser: executablePath }, citationAudit: audit, removedTitleEchoes: removedEchoes,
    pageMap, chapterHashes: Object.fromEntries(chapters.map(c => [c.file, c.sha256])),
    pdf: path.basename(pdfPath), html: path.basename(htmlPath), mergedMarkdown: 'zh_merged/book_zh.md', builtAt: new Date().toISOString(),
    visualInspection: '脚本不做目视检查，见 references/assembly.md',
  };
  fs.writeFileSync(path.join(outDir, `validation${editionSuffix}.json`), JSON.stringify(validation, null, 2) + '\n');
  console.log(JSON.stringify({ status: validation.status, problems, warnings, pdf: pdfPath, html: htmlPath, mergedMarkdown: path.join(root, 'zh_merged/book_zh.md'), pages: report.pages, chapters: chapters.length, bookmarks: report.bookmarks, noteRefs: dom.noteRefs, pendingMarkers: validation.pendingMarkers, cover: coverKind }, null, 2));
  if (problems.length) exitCode = 1;
} finally {
  await browser.close();
}
process.exit(exitCode);
