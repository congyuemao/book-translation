# 阶段 6：合并、封面、封底、两份 PDF

## 合成前检查

```bash
python <skill>/scripts/booktool.py check .
python <skill>/scripts/booktool.py audit-check . --final
```

`build_book.mjs` 还会自己卡几项：每章必须有且只有一个一级标题；注释号要能对上；正文不能残留"校注：""译者注："；`【原文待核】` 的数量要和台账一致。

## 中文 MD

合成脚本每次都会先把 `zh/` 合并成 `zh_merged/book_zh.md`，也可以单独运行：

```bash
python <skill>/scripts/booktool.py merge .
```

**逐章的 `zh/*.md` 和合并的 `zh_merged/book_zh.md` 都要保留并交给用户**，以后人工修改靠它们。两个文件夹都要纳入 git，不要放进 `build/`。

书前书后的文件和正文一样，都放在 `zh/` 里。锚点和 `<!--file:...-->` 标记都是 HTML 注释，不会进入成品，人工修改时不要动它们。

## 后续人工修改

1. **改逐章文件**：直接改 `zh/*.md`，然后重新合成。合并文件会自动更新。
2. **改合并文件**：直接改 `zh_merged/book_zh.md`，先写回，再合成：

   ```bash
   python <skill>/scripts/booktool.py unmerge .
   ```

3. 改完跑 `check` 和 `audit-check`，再运行 `build_book.mjs`。不要直接改 PDF 或 HTML，下次合成就没了。

保护规则：合并文件有人工修改还没写回时，`merge` 和合成脚本都会拒绝运行，不会覆盖这些修改。合并文件和逐章文件的同一章都改过时，`unmerge` 会报错，一个文件都不写，这时手工合并。确认以合并文件为准才加 `--force`；确认放弃合并文件的修改时，用 `merge . --force`，它会先备份。

## 书前书后

按书的需要补上，放进 `zh/`（文件名靠前或靠后排序）：

- 原书的序言、致谢、作者说明都要译；
- 需要时加"译者说明"：讲清底本版本、术语原则、`【原文待核】` 的含义、暂译人名表。单独成一个文件，一级标题就写 `# 译者说明`，这样阅读版会自动去掉它；
- 索引：页码变了，原书索引不能直接用，默认不翻。用户要的话再单独做。

`project.json` 的 `build.edition_note` 是完整版版权页（阅读说明页）上的一段话，要如实写：用了什么底本、AI 翻译加哪些人工校对。原书版权归原作者及权利方所有。这个 skill 只负责做书，要不要分发、能不能分发由用户决定，不要替用户公开发布。

## 封面

封面有两种做法，用户指定了就照办：

| 方式 | 做什么 | 用什么做 | 适合 |
| --- | --- | --- | --- |
| **汉化原封面** | 保留原封面的图像、构图和配色，只把文字换成中文 | 生图模型 | 原封面好看、清晰，而且想保留原书的样子 |
| **重新设计** | 按书的内容设计一张新封面，不沿用原封面的图像 | **模型手搓：自己写 HTML、CSS、SVG 画出来，不调用生图模型** | 没有原封面、原封面太糊或太过时、想要新面貌，或者译本要公开分发 |

用户没指定时：有清晰的原封面就汉化，否则重新设计，并把选择记入 `logs/decisions.md`。汉化后的封面仍然用着原封面的图像，版权归原权利人，这一点要告诉用户。译本要公开分发时，建议重新设计。

### 先列好封面文字

不管哪种方式，都先逐字定好要出现的文字：中文书名、副标题、作者署名（以术语表为准，没有中文名就写原文）、是否保留原书名。

### 方式一：汉化原封面（用生图模型）

1. 把原封面放到 `cover/original.*`。扫描件先裁切、拉正。
2. 列一张对照表，写明原封面上的每一处文字怎么处理：翻译成什么，还是删掉。推荐语、丛书名这类要逐条定；图书馆章、出版社标志、条码默认去掉。
3. 把原封面作为参考图或待编辑图传给生图模型。这种方式必须用能接收图片的模型或编辑功能。没有这类工具时，把提示词和对照表写到 `cover/prompt.md`，交给用户去生成。参考提示词：

   ```text
   编辑这张图书封面，把封面上的文字替换成下面的简体中文，其他部分保持不变。
   保留原有的图像、构图、配色、背景质感和文字所在的位置。
   中文字体的气质、字重和颜色要与原文字相近，大小可以按中文的长度调整。
   原文字 → 替换为（必须逐字一致）：
   “The Salt Road” → “盐路”
   “Mara Ellison” → “玛拉·埃利森 著”
   去掉这些内容，并按周围画面自然补全：[出版社标志、条码、馆藏章等]
   不要添加其他任何文字、标志或水印。
   ```

4. 和原封面并排对比：图像有没有被改掉，有没有残留外文，文字有没有挡住重要画面。
5. **逐字检查生成结果。** 生图模型很容易写错汉字，放大看每一个字。有错字就重新生成。两三次还不对，就让模型只去掉文字、补全背景，再用 HTML 把中文排上去（`cover.html` 的写法见方式二）。
6. **核对比例。** 封面图会铺满页面，比例不一致就会被裁掉边缘。原封面的比例常常和默认的 160:230 不同，可以把 `project.json` 里的 `build.page_width_mm`、`page_height_mm` 改成和原书一致，或者生成时按页面比例补足画面。
7. 定稿存为 `cover/cover.png`（或 `.jpg`），提示词留在 `cover/prompt.md`。

### 方式二：重新设计（模型手搓，不用生图模型）

**不要调用生图模型，也不要用外部图片或素材。** 封面由你亲自写代码画出来：版式用 HTML 和 CSS，图形用 SVG 或 CSS 绘制。这样文字是真正排上去的，不会写错字；放大也清晰；哪里不满意都能直接改。用户要求手搓时，即使环境里有生图工具也不要用。

1. 从译稿里提炼设计依据：主题、时代、地域、基调，以及读者一眼应该感受到什么。要用书里具体的意象，不要只堆通用符号。
2. 定下一个能用几何图形、线条、色块和字体表现的构图。字本身就可以是主角。选 2–3 种颜色，留足空白。不要模仿某家出版社、某个丛书或某位设计师的标志性样式。
3. 拟 2–3 个方向不同的方案，各写成 `cover/option-a.html`、`option-b.html` 等，看过效果后请用户选一张。用户说了全自动时，自己选一张，把其他方案留着。选定的方案复制成 `cover/cover.html`。没有原封面（比如只有 TXT）时，也走这种方式。
4. 写法：`cover.html` 是直接嵌入书里的片段，不是完整文档。最外层用 `<section class="cover-page" id="cover">`，样式写在片段内的 `<style>` 里，类名加上前缀以免影响正文。字体用 `var(--serif)` 和 `var(--sans)`，脚本会把封面用到的字一起嵌入。尺寸和定位用百分比，字号用 `cqw`，这样 PDF 和手机上的 HTML 比例一致：

   ```html
   <section class="cover-page" id="cover">
     <style>
       #cover{container-type:inline-size;background:#162e3b;color:#f3ecdf}
       #cover .c-title{position:absolute;z-index:1;left:10%;top:9%;margin:0;color:#f3ecdf;font:800 19cqw/1.1 var(--sans)}
       #cover .c-author{position:absolute;z-index:1;left:10%;bottom:7%;font:500 3.6cqw/1.5 var(--sans)}
       #cover svg{position:absolute;right:-14%;bottom:14%;width:78%}
     </style>
     <h2 class="c-title">盐路</h2>
     <div class="c-author">玛拉·埃利森 著</div>
     <svg viewBox="0 0 600 600" aria-hidden="true"><circle cx="300" cy="300" r="280" fill="#ca533b"/></svg>
   </section>
   ```

   书名用 `h2` 或 `div`，不要用 `h1`，否则 PDF 书签会多出一条。用 `h2` 时要自己写 `color`，否则会被书里的标题颜色盖掉。文字要加 `z-index`，免得被后面的图形压住。

5. **看效果再定稿。** 运行合成脚本，把 PDF 第 1 页转成图片（或者把片段放进一个临时 HTML，把 `.cover-page` 设成页面尺寸后截图），实际看过：文字有没有被图形挡住、有没有溢出、对比度够不够、缩小到目录图大小时书名还认不认得出。文字也要逐字核对。
6. 需要图片文件（比如给 README 用）时，从成品截图导出，不用另外生成。

脚本取封面的优先级：`cover/cover.html` → `cover/cover.png|jpg|jpeg|webp` → 自动排一个纯文字封面。所以封面没好时也能先出 PDF 看版面。自动文字封面会显示 `project.json` 里的书名、副标题和作者。

## 封底

封底和封面一样要做，放在两份 PDF 的最后一页。

**用什么做：**

- 封面是汉化的，并且有原封底（放到 `cover/original-back.*`）：同样用生图模型汉化，步骤同方式一，定稿存为 `cover/back.png`。
- 其他情况（重新设计，或者没有原封底）：模型手搓，不调用生图模型，写成 `cover/back.html`。配色和字体要和封面呼应，看起来是一本书的两面。

**写什么：**

- 内容简介，150–300 字。原封底有简介就翻译它；没有就根据译稿写，只写书里确实有的内容。
- 可选：作者简介（只用查证过的信息）、原书名和原作者。
- 原封底上的推荐语照实翻译，并保留署名。**不要编造推荐语、奖项和销量。**
- 不要放条码、ISBN、定价和出版社标志。这些原书的信息不属于这个译本，也不要编造新的。

写法和封面的 `cover.html` 相同，只是最外层换成下面这样。样式都写在 `#back-cover` 下面：

```html
<section class="cover-page back-cover" id="back-cover">
  <style>
    #back-cover{container-type:inline-size;background:#162e3b;color:#f3ecdf}
    #back-cover .b-text{position:absolute;left:12%;right:12%;top:14%;font:400 3.5cqw/1.9 var(--serif)}
    #back-cover .b-text p{margin:0 0 1em;text-align:justify}
    #back-cover .b-meta{position:absolute;left:12%;right:12%;bottom:8%;font:500 2.8cqw/1.6 var(--sans);opacity:.8}
  </style>
  <div class="b-text"><p>内容简介……</p></div>
  <div class="b-meta">原书名：…… · 原作者：……</div>
</section>
```

脚本取封底的优先级：`cover/back.html` → `cover/back.png|jpg|jpeg|webp`。没有封底也能出书，但 `validation` 的 `warnings` 会提醒。封底的每个字同样要核对，事实要能在书里找到依据。

## 合成两份 PDF

默认交付两份 PDF：

| 版本 | 文件 | 内容 |
| --- | --- | --- |
| 完整版 | `build/<书名>.pdf` | 带版权页、译者说明、注释、注号和 `【原文待核】`，用来查证和校对 |
| 无注释纯阅读版 | `build/<书名>_阅读版.pdf` | 只留封面、目录、作者的正文和封底。版权页、译者说明、注释、注号和待核标记全部去掉，目录页码重排 |

两份都带封面和封底，也各有一份 HTML。

依赖：Node.js 22+，`marked`、`playwright`，Python 的 `pypdf`、`fonttools`、`brotli`，以及本机的 Chrome 或 Edge（不必下载 Playwright 自带的浏览器）。脚本会分别去找装了 `pypdf` 和 `fonttools` 的 Python，两者不必在同一个环境。

```bash
node <skill>/scripts/build_book.mjs .             # 两份都出
node <skill>/scripts/build_book.mjs . --full      # 只出完整版，调版面时省时间
node <skill>/scripts/build_book.mjs . --reading   # 只出阅读版
```

**不用预先检查依赖，直接跑。** 脚本自己找：Node 包依次看项目目录、`NODE_PATH`、脚本目录、Codex 运行环境；Python 依次看 `PYTHON`、Codex 运行环境、`py -3`、`python3`、`python`。所以 `py -3` 里没有 `pypdf` 不代表跑不了。真缺什么，脚本会说，这时再装，**装到项目目录，不要写 skill 目录**：

```bash
npm install marked@17.0.5 playwright@1.62.1
python -m pip install -r <skill>/scripts/requirements.txt
```

环境变量：`BROWSER_PATH`（浏览器路径）、`PYTHON`（Python 路径）、`NODE_PATH`、`CODEX_RUNTIME_DIR`（Codex 运行环境目录）、`BOOK_FONT_DIR`（字体目录）。实际用了哪份依赖记录在 `validation.json` 的 `environment`。

输出到 `build/`：每个版本一份 PDF、一份单文件 HTML 和一个校验文件（`validation.json`、`validation_阅读版.json`）。**两个校验文件都要通过。** 只用 `--full` 或 `--reading` 调试之后，交付前要再跑一遍默认命令。

**阅读版的注意事项：**

- **译者说明怎么去掉：** 标题完全等于“译者说明”“译者前言”“译者的话”“译后记”“翻译说明”“校注说明”等的文件会自动去掉；作者自己写的“读者说明”“序言”不受影响。其他只给校对看的文件（比如暂译人名表），把文件名前缀或标题写进 `project.json` 的 `build.reading_exclude`。实际去掉了哪些，记在 `validation_阅读版.json` 的 `readingExcluded`，要看一眼对不对。
- 正文里提到注释或译者说明的话（比如“见注 3”）在阅读版里会落空。脚本会在 `warnings` 里列出来，要把译文改成不依赖它们的说法。
- 阅读版里完全看不出这是 AI 译本、哪些引文还没落实。所以交付说明里要写明这一点和待核数量，让用户决定是否现在就发阅读版。

脚本会做的事：排版、循环到目录页码稳定（最多 4 轮）、加书签和元数据、回读校验（页数、书签、字体是否全部嵌入、有无替换字符和空白页、注释链接是否有效、每章抽 3 段核对是否进了 PDF）。这只是抽样，**不等于逐字核对正文**。校验不过会报错，不要绕过，先解决。

`validation.json` 里：`status` 是总判断；`warnings` 不影响通过，但要看；`sparsePages` 列出字很少的页，只是提示，章末短页和版权页都正常；`pendingMarkersInPdf` 比 `pendingMarkers` 多 1 是因为版权页说明里也写了这个标记。

版式默认 160 × 230 mm、宋体正文、黑体标题，来自《天命》的版式。在 `project.json` 的 `build` 里可以改书眉和页面尺寸；要换样式就把 `assets/book.css` 复制到项目根目录改，脚本会优先用项目里的 `book.css`。

中文字体默认用 Noto Serif SC 和 Noto Sans SC（可从项目的 `fonts/`、`BOOK_FONT_DIR` 或系统字体目录找到），脚本按全书用字生成子集并嵌入 HTML 和 PDF，HTML 因此可离线阅读。**这一步不只是为了好看**：直接用系统里的这两个字体时，Chrome 会把“一”“马”等字写成部首码位，PDF 看着正常，复制和搜索却对不上。

缺 `fonttools` 或字体时脚本仍会出书，退回本机字体，并在 `validation.json` 的 `warnings` 里说明。看到部首码位的警告时，先装好依赖再重建，并告诉用户。

## 目视检查

脚本查不出版面难看的问题。用能把 PDF 转成图片的工具（`pdftoppm`、`pypdfium2`）或直接在浏览器里打开，两份 PDF 都要看。完整版至少看：封面、目录、版权页、一章的开头、一页正文、一页注释、封底。阅读版至少看：封面后面紧接着是不是目录、一章的开头、一页正文、封底。重点看：孤行和孤页、字距被拉散的行（括注外文时常见）、表格溢出、图片、标题落在页底、封面是否铺满。版面问题改 CSS（复制 `book.css` 到项目里调），不要为了版面改译文。

如实把看了哪些页写进交付说明。

## 其他成品

用户要 EPUB、TXT 时按项目写一个脚本，从 `zh/` 生成，去掉锚点，并回读校验正文和注释都进了成品。阅读版同样去掉版权页、译者说明、注释和待核标记。

## 完成标准

- 完整版和阅读版两份 PDF 都已生成，两个校验文件都通过；
- 目视检查过，没有明显问题；
- 封面和封底每个字都核过，封底的内容能在书里找到依据；
- 交付说明写明两份 PDF 各自的页数、章数、待核数量、核对范围和还需要用户做的事。
