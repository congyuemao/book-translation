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

用户的做法是**用生图模型把封面重新生成一张中文版**。

1. 把原封面放到 `cover/original.*`，描述它的版式、配色、图像和字体气质。没有原封面（比如只有 TXT）时，按书的内容另拟构图，提示词里去掉"保留原封面"那句。
2. 要出现的文字逐字列好：中文书名、副标题、作者署名（以术语表为准，没有中文名就写原文）、是否保留原书名。
3. 调用环境里的生图工具。没有生图工具时，把提示词写到 `cover/prompt.md`，交给用户去生成。参考提示词：

   ```text
   为一本中文图书设计封面，竖版，宽高比 160:230。保留原封面的构图与视觉气质：[版式、配色、主要图像的具体描述]。
   封面文字（必须逐字一致，简体中文）：
   书名：《……》
   副标题：……
   作者：[中文名] 著
   不要添加其他任何文字、标志或水印。
   ```

   如果模型支持参考图，把原封面传进去。原封面上的图书馆章、出版社标志、条码都不要带上。

4. **逐字检查生成结果。** 生图模型很容易写错汉字，放大看每一个字。有错字就重新生成。两三次还不对，就改成"只生成无字的背景图"，再用 HTML 排字（把 `cover/cover.html` 写好，脚本会用它），这样文字一定是对的。`cover.html` 是直接嵌入书里的片段，不是完整文档，最外层写 `<section class="cover-page" id="cover">`，样式写在片段内的 `<style>` 里。
5. 定稿存为 `cover/cover.png`（或 `.jpg`）。可选封底 `cover/back.png`。

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
