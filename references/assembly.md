# 阶段 6：合并、封面、PDF

## 合成前检查

```bash
python <skill>/scripts/booktool.py check .
python <skill>/scripts/booktool.py audit-check . --final
```

`build_book.mjs` 还会自己卡几项：每章必须有且只有一个一级标题；注释号要能对上；正文不能残留"校注：""译者注："；`【原文待核】` 的数量要和台账一致。

## 书前书后

按书的需要补上，放进 `zh/`（文件名靠前或靠后排序）：

- 原书的序言、致谢、作者说明都要译；
- 需要时加"译者说明"或"读者说明"：讲清底本版本、术语原则、`【原文待核】` 的含义、暂译人名表；
- 索引：页码变了，原书索引不能直接用，默认不翻。用户要的话再单独做。

`project.json` 的 `build.edition_note` 是版权页（阅读说明页）上的一段话，要如实写：用了什么底本、AI 翻译加哪些人工校对。原书版权归原作者及权利方所有。这个 skill 只负责做书，要不要分发、能不能分发由用户决定，不要替用户公开发布。

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
7. 定稿存为 `cover/cover.png`（或 `.jpg`），提示词留在 `cover/prompt.md`。可选封底 `cover/back.png`。

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

## 合成 PDF

依赖：Node.js 22+，`marked`、`playwright`，Python 的 `pypdf`、`fonttools`、`brotli`，以及本机的 Chrome 或 Edge（不必下载 Playwright 自带的浏览器）。脚本会分别去找装了 `pypdf` 和 `fonttools` 的 Python，两者不必在同一个环境。

```bash
node <skill>/scripts/build_book.mjs .
node <skill>/scripts/build_book.mjs . --reading    # 无引注阅读版
```

**不用预先检查依赖，直接跑。** 脚本自己找：Node 包依次看项目目录、`NODE_PATH`、脚本目录、Codex 运行环境；Python 依次看 `PYTHON`、Codex 运行环境、`py -3`、`python3`、`python`。所以 `py -3` 里没有 `pypdf` 不代表跑不了。真缺什么，脚本会说，这时再装，**装到项目目录，不要写 skill 目录**：

```bash
npm install marked@17.0.5 playwright@1.62.1
python -m pip install -r <skill>/scripts/requirements.txt
```

环境变量：`BROWSER_PATH`（浏览器路径）、`PYTHON`（Python 路径）、`NODE_PATH`、`CODEX_RUNTIME_DIR`（Codex 运行环境目录）、`BOOK_FONT_DIR`（字体目录）。实际用了哪份依赖记录在 `validation.json` 的 `environment`。

输出到 `build/`：PDF、单文件 HTML、`validation.json`。阅读版文件名带"阅读版"。

脚本会做的事：排版、循环到目录页码稳定（最多 4 轮）、加书签和元数据、回读校验（页数、书签、字体是否全部嵌入、有无替换字符和空白页、注释链接是否有效、每章抽 3 段核对是否进了 PDF）。这只是抽样，**不等于逐字核对正文**。校验不过会报错，不要绕过，先解决。

`validation.json` 里：`status` 是总判断；`warnings` 不影响通过，但要看；`sparsePages` 列出字很少的页，只是提示，章末短页和版权页都正常；`pendingMarkersInPdf` 比 `pendingMarkers` 多 1 是因为版权页说明里也写了这个标记。

版式默认 160 × 230 mm、宋体正文、黑体标题，来自《天命》的版式。在 `project.json` 的 `build` 里可以改书眉和页面尺寸；要换样式就把 `assets/book.css` 复制到项目根目录改，脚本会优先用项目里的 `book.css`。

中文字体默认用 Noto Serif SC 和 Noto Sans SC（可从项目的 `fonts/`、`BOOK_FONT_DIR` 或系统字体目录找到），脚本按全书用字生成子集并嵌入 HTML 和 PDF，HTML 因此可离线阅读。**这一步不只是为了好看**：直接用系统里的这两个字体时，Chrome 会把“一”“马”等字写成部首码位，PDF 看着正常，复制和搜索却对不上。

缺 `fonttools` 或字体时脚本仍会出书，退回本机字体，并在 `validation.json` 的 `warnings` 里说明。看到部首码位的警告时，先装好依赖再重建，并告诉用户。

## 目视检查

脚本查不出版面难看的问题。用能把 PDF 转成图片的工具（`pdftoppm`、`pypdfium2`）或直接在浏览器里打开，至少看：封面、目录、版权页、一章的开头、一页正文、一页注释、最后一页。重点看：孤行和孤页、字距被拉散的行（括注外文时常见）、表格溢出、图片、标题落在页底、封面是否铺满。版面问题改 CSS（复制 `book.css` 到项目里调），不要为了版面改译文。

如实把看了哪些页写进交付说明。

## 其他成品

用户要 EPUB、TXT 时按项目写一个脚本，从 `zh/` 生成，去掉锚点，并回读校验正文和注释都进了成品。阅读版去掉注释和待核标记后，版权页要说明省略了什么。

## 完成标准

- `validation.json` 通过；
- 目视检查过，没有明显问题；
- 封面每个字都核过；
- 交付说明写明页数、章数、待核数量、核对范围和还需要用户做的事。
