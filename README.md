# book-translation

把一本外文书用 AI 翻译成中文版的 Agent Skill，适用于 Claude Code、Codex 等能读取 skill 目录的工具。它覆盖从原文整理到 PDF 成品的全流程，长篇可以跨多个会话接力。

## 流程

| 阶段 | 做什么 |
| --- | --- |
| 0 准备 | 提醒备好原书、扫描件和 OCR 结果。这些不是硬性要求，缺了也能继续 |
| 1 原文 MD | 整理全书原文 Markdown，与原书核对，按章拆分 |
| 2 名词总表 | 查证人名、地名、著作、机构、术语。英语用英中两语，其他语言用原文、英文、中文三语 |
| 3 逐章翻译 | 先试译定调，再逐章翻译，原文和译文按段对应 |
| 4 引文核查 | 有中译本的直接取中译原文，没有的回查原文再译，查不到的标【原文待核】并记入台账 |
| 5 润色 | 拆长从句，去翻译腔，换成中文的说法，不丢信息 |
| 6 合成 | 合并全书，做封面（生图模型汉化原封面，或模型用代码手搓重新设计），做封底，生成带目录和书签的两份 PDF（带注释完整版、无注释纯阅读版）及 HTML |

详细说明见 [SKILL.md](SKILL.md) 和 [references/](references/)。

成品除了两份 PDF 和 HTML，还保留逐章的 `zh/*.md` 和全书的 `zh_merged/book_zh.md`，方便以后人工修改后重新合成。

## 安装

把仓库克隆到工具的 skill 目录：

```bash
# Claude Code
git clone https://github.com/congyuemao/book-translation.git ~/.claude/skills/book-translation

# Codex
git clone https://github.com/congyuemao/book-translation.git ~/.codex/skills/book-translation
```

然后直接说“帮我把这本书翻成中文，做成 PDF”，或者只要其中一段，比如“把这份译稿润色一下”“把这些章节合成 PDF”。

## 依赖

- `scripts/booktool.py`（校验、台账、进度）：Python 3 标准库。其中 `inspect` 需要 `pypdf`。
- `scripts/build_book.mjs`（合成 PDF）：Node.js 22+、`marked`、`playwright`、Python 的 `pypdf`，以及本机的 Chrome 或 Edge。
- 字体子集（可选，建议安装）：`fonttools`、`brotli`，以及 Noto Serif SC 和 Noto Sans SC。没有的话也能出书，但 PDF 里部分汉字的复制和搜索可能对不上。
- `scripts/epub2md.py`（EPUB 转 MD）、`scripts/polish_tool.py`（逐段润色）、`scripts/notes_tool.py`（插注删注）、`scripts/diff_review.py`（改动对照页）、`scripts/md_export.py`（导出全书 MD）、`scripts/corpus.py`（本地引文语料）：Python 3 标准库；`corpus.py pdf` 需要 `pypdf`。
- `scripts/index_tool.py`（重做索引）：`pypdf`。`scripts/pdf_sheet.py`（缩略图拼页）：`pypdfium2`、`Pillow`。`scripts/halftone.py`（封面照片网点化）：`numpy`、`Pillow`。`scripts/cover_preview.mjs`（封面预览）：`playwright` 和本机的 Chrome 或 Edge。

不用提前检查依赖，直接运行即可，缺什么脚本会提示。安装方法见 [references/assembly.md](references/assembly.md)。

## 脚本查不了什么

脚本只保证不漏、不乱、不矛盾：段落对应、注释编号、数字、术语、引文台账和版面基本项。它判断不了译得好不好，也不能替代人工校对。

生图模型汉化封面和 OCR 输入还没有实际测试。

## 版权

翻译和分发书籍时，请自行确认相关权利。原书版权归原作者及权利方所有。
