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
| 6 合成 | 合并全书，翻译封面，生成带目录和书签的 PDF 与 HTML，可加无引注阅读版 |

详细说明见 [SKILL.md](SKILL.md) 和 [references/](references/)。

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

不用提前检查依赖，直接运行即可，缺什么脚本会提示。安装方法见 [references/assembly.md](references/assembly.md)。

## 脚本查不了什么

脚本只保证不漏、不乱、不矛盾：段落对应、注释编号、数字、术语、引文台账和版面基本项。它判断不了译得好不好，也不能替代人工校对。

目前已经用样书和一部 300 多页译稿的合成测试过脚本。还没有用它从头翻译过一整本长书，生图封面和 OCR 输入也没有实际测试。

## 版权

翻译和分发书籍时，请自行确认相关权利。原书版权归原作者及权利方所有。
