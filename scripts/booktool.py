#!/usr/bin/env python3
"""书籍翻译流程的机械工具：建项目、拆章、校验译文、引文台账、润色校验、进度。

只依赖标准库（inspect 子命令需要 pypdf）。用法见 python booktool.py -h。
退出码：0 无错误（可能有警告），1 有错误，2 用法或环境问题。
"""
from __future__ import annotations

import argparse
import csv
import errno
import hashlib
import json
import os
import re
import statistics
import sys
import unicodedata
import zipfile
from collections import Counter, OrderedDict
from datetime import datetime
from pathlib import Path

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

ANCHOR_RE = re.compile(r"^<!--b(\d+)(?:\s+p\.([^\s>]+))?-->[ \t]*$", re.M)
PAGE_RE = re.compile(r"^<!--p\.([^\s>]+?)-->[ \t]*$")
NOTES_RE = re.compile(r"^##\s+(注释与引用|注释|注|Notes?|Endnotes|Footnotes|Anmerkungen|Fußnoten|Références|Примечания|Notas|주|注釈)\s*$", re.M | re.I)
NOTE_REF_RE = re.compile(r"\\?\[(\d+)\\?\](?!\()|〔(\d+)〕")
NOTE_ITEM_RE = re.compile(r"^(\d+)\.\s+", re.M)
PENDING = "【原文待核】"
HAN_RE = re.compile(r"[\u3400-\u9fff]")
GLOSSARY_COLUMNS = ["type", "source", "en", "zh", "aliases_source", "aliases_zh",
                    "forbidden_zh", "status", "basis", "url", "note"]
GLOSSARY_TYPES = {"person", "place", "work", "org", "event", "term", "other"}
GLOSSARY_STATUS = {"verified", "provisional", "keep_original", "conflict"}
AUDIT_STATUS = {"not_reviewed", "restored", "verified_original", "back_translated",
                "partial", "searched_unresolved", "not_applicable"}
AUDIT_DONE = {"restored", "verified_original", "back_translated"}
AUDIT_MARKED = {"partial", "searched_unresolved"}
AUDIT_LEVELS = {"scan_original", "published_translation", "contemporary_reprint", "later_compilation",
                "digital_typeset", "web_transcript", "translated_anthology", "secondary_quote", "other"}
AI_WORDS = ["赋能", "深耕", "聚焦", "助力", "打造", "引领", "全方位", "多维度", "沉浸式", "一站式", "闭环",
            "抓手", "底层逻辑", "顶层设计", "值得一提", "值得注意的是", "不言而喻", "众所周知", "毫无疑问",
            "综上所述", "未来可期", "拭目以待", "里程碑", "新篇章"]
STYLE_PATTERNS = {
    "进行+动词": r"进行了?[\u4e00-\u9fff]{2}",
    "对于……来说": r"对于[^，。；]{1,15}(?:来说|而言)",
    "在……方面": r"在[^，。；]{1,12}方面",
    "通过……方式": r"通过[^，。；]{1,12}(?:方式|方法|途径)",
    "句首连接词": r"(?:^|[。！？]\s*)(?:然而|此外|因此|另外|与此同时|事实上|总之|综上所述)",
    "“被”字": r"被",
}
PLACEHOLDER_RE = re.compile(r"此处略|（略）|\(略\)|以下省略|待翻译|未翻译|TODO|TBD")
OCR_RE = re.compile(r"\b(?:tbe|tlie|wbich|witb|bave|tbat|ofthe|inthe|tothe|andthe)\b|[a-z][0-9][a-z]")


class Report:
    def __init__(self):
        self.errors, self.warnings = [], []

    def error(self, where, message):
        self.errors.append({"where": where, "message": message})

    def warn(self, where, message):
        self.warnings.append({"where": where, "message": message})

    def show(self, limit=40, json_path=None):
        for label, items in (("错误", self.errors), ("警告", self.warnings)):
            if items:
                print(f"\n{label}（{len(items)}）：")
                for item in items[:limit]:
                    print(f"  [{item['where']}] {item['message']}")
                if len(items) > limit:
                    print(f"  ……另有 {len(items) - limit} 条，用 --json 导出全部")
        print(f"\n结果：{len(self.errors)} 个错误，{len(self.warnings)} 个警告")
        if json_path:
            Path(json_path).write_text(json.dumps({"errors": self.errors, "warnings": self.warnings},
                                                  ensure_ascii=False, indent=2), encoding="utf-8")
        return 1 if self.errors else 0


def read_text(path):
    return Path(path).read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_project(root):
    path = Path(root) / "project.json"
    if not path.exists():
        print(f"找不到 {path}，请先运行 init", file=sys.stderr)
        raise SystemExit(2)
    return json.loads(read_text(path))


def chapter_files(folder, chapter=None):
    files = sorted(Path(folder).glob("*.md"))
    if chapter:
        files = [f for f in files if f.name.startswith(chapter)]
    return files


def split_notes(text):
    match = NOTES_RE.search(text)
    return (text[:match.start()], text[match.end():]) if match else (text, "")


def parse_notes(notes_text):
    items = list(NOTE_ITEM_RE.finditer(notes_text))
    notes = OrderedDict()
    for i, item in enumerate(items):
        end = items[i + 1].start() if i + 1 < len(items) else len(notes_text)
        notes[int(item.group(1))] = notes_text[item.end():end].strip()
    return notes


def parse_chapter(text):
    """按锚点切块。返回块（id→正文）、页码、注释。"""
    body, notes_text = split_notes(text)
    anchors = list(ANCHOR_RE.finditer(body))
    blocks, pages = OrderedDict(), {}
    for i, anchor in enumerate(anchors):
        end = anchors[i + 1].start() if i + 1 < len(anchors) else len(body)
        key = anchor.group(1)
        blocks[key] = body[anchor.end():end].strip()
        if anchor.group(2):
            pages[key] = anchor.group(2)
    head = body[:anchors[0].start()].strip() if anchors else body.strip()
    return {"blocks": blocks, "pages": pages, "notes": parse_notes(notes_text), "head": head, "body": body}


def blocks_or_paragraphs(chapter):
    """没有锚点的已有译稿，退回按空行分段，编号形如 p001。"""
    if chapter["blocks"]:
        return chapter["blocks"]
    body = re.sub(r"^#\s+.*$", "", chapter["body"], count=1, flags=re.M)
    parts = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    return OrderedDict((f"p{i:03d}", p) for i, p in enumerate(parts, 1))


def note_refs(text):
    return [int(a or b) for a, b in NOTE_REF_RE.findall(text)]


def strip_refs(text):
    return NOTE_REF_RE.sub("", text)


def numbers(text):
    tokens = re.findall(r"\d[\d,.]*\d|\d", strip_refs(text))
    # 1,000、1.000 都按千分位处理，这样 20.000 和 20,000 视为同一个数。
    return Counter(re.sub(r"(?<=\d)[.,](?=\d{3}(?!\d))", "", t).replace(",", "").rstrip(".") for t in tokens)


def units(text):
    """语言无关的长度：词数加汉字、假名数。"""
    words = re.findall(r"[^\W\d_\u3040-\u30ff\u3400-\u9fff]+", strip_refs(text))
    chars = re.findall(r"[\u3040-\u30ff\u3400-\u9fff]", text)
    return len(words) + len(chars)


def split_alt(value):
    return [v.strip() for v in (value or "").split("|") if v.strip()]


def load_glossary(path):
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def term_pattern(terms):
    parts = []
    for term in terms:
        escaped = re.escape(term)
        parts.append(rf"(?<!\w){escaped}(?!\w)" if re.match(r"^\w", term, re.A) else escaped)
    return re.compile("|".join(parts), re.I) if parts else None


# ---------- 0 准备 ----------

def cmd_init(args):
    root = Path(args.dir)
    if (root / "project.json").exists():
        print(f"{root} 已有 project.json，没有改动。", file=sys.stderr)
        return 2
    for sub in ["source/original", "source/chapters", "source/images", "glossary", "zh", "zh_merged", "audit/rounds",
                "audit/sources", "polish", "cover", "build", "logs"]:
        (root / sub).mkdir(parents=True, exist_ok=True)
    write_json(root / "project.json", {
        "title_source": args.title, "title_zh": args.title_zh or "", "subtitle_source": "", "subtitle_zh": "",
        "author_source": args.author or "",
        "author_zh": "", "source_lang": args.source_lang, "target_lang": "zh-CN", "genre": args.genre,
        "edition": "", "user_preferences": [], "editorial_rules": [],
        "progress": {"stage": "source", "translated_chapters": [], "polished_chapters": [], "next": ""},
        "build": {"running_head": args.title_zh or args.title, "page_width_mm": 160, "page_height_mm": 230,
                  "edition_note": "", "reading_exclude": [], "output_name": args.title_zh or args.title},
    })
    with open(root / "glossary" / "glossary.csv", "w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerow(GLOSSARY_COLUMNS)
    write_json(root / "audit" / "citations.json", {
        "round": 0, "date": "", "access_limits": [], "acceptances": [], "requests": [], "records": []})
    (root / "logs" / "decisions.md").write_text(
        "# 翻译决定记录\n\n记录用户的决定和非显而易见的处理，以便跨会话接力。\n", encoding="utf-8")
    (root / "source" / "collation.md").write_text(
        "# 原文核对记录\n\n底本：\n\n", encoding="utf-8")
    (root / ".gitignore").write_text("build/\nnode_modules/\n__pycache__/\n", encoding="utf-8")
    (root / ".gitattributes").write_text(
        "*.md text eol=lf\n*.csv text eol=lf\n*.json text eol=lf\n*.pdf binary\n"
        "source/original/** -text\naudit/sources/** -text\n", encoding="utf-8")
    print(f"已建立项目：{root}")
    return 0


def cmd_inspect(args):
    try:
        from pypdf import PdfReader
    except ImportError:
        print("需要 pypdf：python -m pip install pypdf。也可以不查，直接开工。", file=sys.stderr)
        return 2
    reader = PdfReader(args.pdf)
    counts = []
    for page in reader.pages:
        try:
            counts.append(len(re.sub(r"\s+", "", page.extract_text() or "")))
        except Exception:
            counts.append(0)
    total = len(counts)
    with_text = sum(1 for c in counts if c >= 50)
    share = with_text / total if total else 0
    print(f"页数：{total}\n有文字的页：{with_text}（{share:.0%}）\n平均每页字符：{sum(counts) / max(total, 1):.0f}")
    low = [i + 1 for i, c in enumerate(counts) if c < 50]
    if low:
        print("几乎没有文字的页（前 30）：" + ", ".join(map(str, low[:30])))
    if share >= 0.9:
        print("判断：有文字层，可以抽取后整理。文字质量仍要抽样看，OCR 层可能很差。")
    elif share >= 0.2:
        print("判断：部分有文字层，缺的页要读图或补 OCR。")
    else:
        print("判断：基本是扫描图。有 OCR 结果最好；没有就读页面图片整理，会慢一些。")
    return 0


# ---------- 1 原文 ----------

def slugify(title):
    ascii_title = unicodedata.normalize("NFKD", title.replace("ß", "ss"))
    ascii_title = "".join(c for c in ascii_title if not unicodedata.combining(c))
    slug = re.sub(r"[^A-Za-z0-9]+", "_", ascii_title).strip("_").lower()
    return slug[:48].strip("_") or "chapter"


def blocks_from_lines(lines):
    """把一章正文切成段（空行分隔，代码块不切）；返回 (页码, 段落文本)。"""
    result, current, page, start_page, fenced = [], [], None, None, False

    def flush():
        nonlocal current, start_page
        text = "\n".join(current).strip()
        if text:
            result.append((start_page, text))
        current, start_page = [], None

    for line in lines:
        marker = PAGE_RE.match(line.strip())
        if marker:
            page = marker.group(1)
            continue
        if line.strip().startswith("```"):
            fenced = not fenced
        if not line.strip() and not fenced:
            flush()
            continue
        if not current:
            start_page = page
        current.append(line)
    flush()
    return result


def cmd_split(args):
    text = read_text(args.book)
    out = Path(args.out)
    if chapter_files(out) and not args.force:
        print(f"{out} 里已有章节。重新拆章会打乱锚点；确认要覆盖请加 --force。", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    lines = text.split("\n")
    heads = [i for i, line in enumerate(lines) if re.match(r"^#\s+\S", line)]
    if not heads:
        print("没有找到一级标题（# 标题），无法拆章。", file=sys.stderr)
        return 2
    leading = [l for l in lines[:heads[0]] if l.strip() and not PAGE_RE.match(l.strip())]
    if leading:
        print(f"第一个一级标题之前还有文字（如：{leading[0][:40]}）。书名页信息写进 project.json 后从 MD 删掉；真正的正文请给它一个标题。", file=sys.stderr)
        return 2
    page = None
    for l in lines[:heads[0]]:
        m = PAGE_RE.match(l.strip())
        if m:
            page = m.group(1)
    written = []
    for number, start in enumerate(heads, 1):
        end = heads[number] if number < len(heads) else len(lines)
        chunk = "\n".join(lines[start:end])
        body, notes = split_notes(chunk)
        blocks = blocks_from_lines(body.split("\n"))
        parts = []
        for index, (block_page, block) in enumerate(blocks, 1):
            effective = block_page or page
            if effective:
                page = effective
            label = f"b{index:03d}" + (f" p.{effective}" if effective else "")
            parts.append(f"<!--{label}-->\n{block}")
        for m in re.finditer(r"^<!--p\.([^\s>]+?)-->[ \t]*$", chunk, re.M):
            page = m.group(1)
        content = "\n\n".join(parts) + "\n"
        match = NOTES_RE.search(chunk)
        if match:
            clean = "\n".join(l for l in notes.split("\n") if not PAGE_RE.match(l.strip()))
            content += f"\n{match.group(0)}\n{clean.rstrip()}\n"
        title = lines[start].lstrip("#").strip()
        name = f"{number:02d}_{slugify(title)}.md"
        (out / name).write_text(content, encoding="utf-8")
        written.append((name, len(blocks)))
    for name, count in written:
        print(f"  {name}：{count} 段")
    print(f"共 {len(written)} 章。拆章后不要再重新编号锚点。")
    return 0


def cmd_source_check(args):
    report = Report()
    files = chapter_files(args.chapters)
    if not files:
        print(f"{args.chapters} 里没有章节文件。", file=sys.stderr)
        return 2
    short_lines, line_where = Counter(), {}
    previous_page = None
    for path in files:
        where = path.name
        chapter = parse_chapter(read_text(path))
        if not chapter["blocks"]:
            report.error(where, "没有锚点，先运行 split")
            continue
        keys = list(chapter["blocks"])
        for i, key in enumerate(keys):
            block = chapter["blocks"][key]
            at = f"{where} b{key}"
            if not block:
                report.error(at, "空段落")
            if "\ufffd" in block:
                report.error(at, "含替换字符（编码或 OCR 问题）")
            if re.search(r"[A-Za-z]-\s*$", block) or re.search(r"[a-z]-\n[a-z]", block):
                report.warn(at, f"行末连字符未修复：{block[:50]}")
            if re.fullmatch(r"[\divxlcIVXLC\s.\-–—]+", block):
                report.warn(at, f"疑似孤立页码：{block}")
            if OCR_RE.search(block):
                report.warn(at, f"疑似 OCR 错字：{OCR_RE.search(block).group(0)}")
            if i + 1 < len(keys):
                following = chapter["blocks"][keys[i + 1]]
                if len(block) >= 40 and re.search(r"[A-Za-z,;]$", block) and re.match(r"[a-z]", following) and not block.startswith("#"):
                    report.warn(at, f"段落可能被断开：……{block[-30:]} / {following[:30]}……")
            for line in block.split("\n"):
                norm = re.sub(r"\d+", "#", line.strip()).casefold()
                if 3 <= len(norm) <= 60 and not norm.startswith(("#", ">", "|")):
                    short_lines[norm] += 1
                    line_where.setdefault(norm, at)
            page = chapter["pages"].get(key)
            if page and page.isdigit():
                if previous_page is not None and int(page) < previous_page:
                    report.warn(at, f"页码倒退：{previous_page} → {page}")
                elif previous_page is not None and int(page) > previous_page + 2:
                    report.warn(at, f"页码跳号：{previous_page} → {page}，确认没有缺页")
                previous_page = int(page)
        refs = note_refs(chapter["body"])
        for n in sorted(set(refs) - set(chapter["notes"])):
            report.warn(where, f"正文注号 [{n}] 没有对应的注释（也可能是正文里的方括号）")
        for n in sorted(set(chapter["notes"]) - set(refs)):
            report.warn(where, f"注释 {n} 在正文里没有注号")
    for line, count in short_lines.most_common():
        if count >= 3:
            report.warn(line_where[line], f"短行重复 {count} 次，可能是页眉页脚：{line}")
    print(f"检查了 {len(files)} 章。")
    return report.show(args.limit, args.json)


# ---------- 2 术语 ----------

def cmd_terms(args):
    stop = {"The", "A", "An", "In", "On", "At", "But", "And", "Or", "If", "It", "He", "She", "They", "We", "I",
            "This", "That", "These", "Those", "There", "Then", "When", "While", "As", "For", "From", "With",
            "By", "To", "Of", "Not", "His", "Her", "Their", "Its", "What", "Who", "How", "Why", "Yet", "So",
            "Mr", "Mrs", "Ms", "Dr", "Chapter", "Part", "See", "Ibid", "After", "Before", "Although", "Thus"}
    upper = "A-ZÀ-ÖØ-ÞА-ЯЁ"
    word = rf"[{upper}][\w'’\-]+"
    pattern = re.compile(rf"(?<![\w'’\-])({word}(?:\s+(?:of|de|la|le|del|van|von|der|du|di|al|the|and|for)\s+{word}|\s+{word})*)")
    total, mid, first = Counter(), Counter(), {}
    for path in chapter_files(args.chapters):
        for block in parse_chapter(read_text(path))["blocks"].values():
            for m in pattern.finditer(block):
                term = m.group(1).rstrip("'’-")
                if term in stop:
                    continue
                before = block[:m.start()].rstrip()
                starts = not before or before[-1] in ".!?:;\"“”‘*#>"
                total[term] += 1
                mid[term] += 0 if starts else 1
                first.setdefault(term, path.name)
    known = set()
    for row in load_glossary(args.glossary) if args.glossary else []:
        known |= {t.casefold() for t in [row.get("source", ""), row.get("en", "")] + split_alt(row.get("aliases_source"))}
    rows = [(t, c, mid[t], first[t]) for t, c in total.most_common()
            if c >= args.min_count and (mid[t] > 0 or " " in t) and t.casefold() not in known]
    lines = ["term\tcount\tmid_sentence\tfirst_chapter"] + ["\t".join(map(str, r)) for r in rows]
    if args.out:
        Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"写入 {args.out}：{len(rows)} 个候选")
    else:
        print("\n".join(lines[:args.limit + 1]))
    if not rows:
        print("没有候选。非拉丁、非西里尔文字（中日韩、阿拉伯文等）脚本提取不了，请通读提取。")
    print("候选只是起点：概念术语、简称和罕见专名要靠通读补上。")
    return 0


def check_glossary(path, source_lang, report):
    rows = load_glossary(path)
    if not Path(path).exists():
        report.error(str(path), "文件不存在")
        return rows
    if rows and (missing := [c for c in GLOSSARY_COLUMNS if c not in rows[0]]):
        report.error(str(path), "缺少列：" + ", ".join(missing))
        return rows
    seen, by_zh = {}, {}
    for number, row in enumerate(rows, 2):
        where = f"第 {number} 行"
        source, zh, status = row["source"].strip(), row["zh"].strip(), row["status"].strip()
        if not source:
            report.error(where, "source 为空")
        if row["type"].strip() not in GLOSSARY_TYPES:
            report.error(where, f"type 不合法：{row['type']}")
        if status not in GLOSSARY_STATUS:
            report.error(where, f"status 不合法：{status}")
        if not zh and status != "keep_original":
            report.error(where, f"{source} 没有中文译名")
        if status == "verified" and not row["basis"].strip():
            report.error(where, f"{source} 标为 verified 但没有依据（basis）")
        if status == "conflict":
            report.warn(where, f"{source} 仍有冲突待定")
        if source_lang != "en" and not row["en"].strip():
            report.warn(where, f"{source} 没有英文写法（原文不是英语时应是三语表）")
        if zh and zh in split_alt(row["forbidden_zh"]):
            report.error(where, f"{source} 的译名同时被列为禁用：{zh}")
        key = source.casefold()
        if key in seen and seen[key] != zh:
            target = report.warn if row["note"].strip() else report.error
            target(where, f"{source} 有不同译名：{seen[key]} / {zh}（同名不同指请在 note 说明）")
        seen.setdefault(key, zh)
        if zh and row["type"].strip() == "person":
            by_zh.setdefault(zh, set()).add(key)
    for zh, sources in by_zh.items():
        if len(sources) > 1:
            report.warn("人名", f"{zh} 对应多个原文写法：{', '.join(sorted(sources))}。同一人请用 aliases_source")
    return rows


def cmd_glossary_check(args):
    report = Report()
    source_lang = args.source_lang
    project_file = Path(args.glossary).resolve().parent.parent / "project.json"
    if not source_lang and project_file.exists():
        source_lang = json.loads(read_text(project_file)).get("source_lang")
    rows = check_glossary(args.glossary, source_lang or "en", report)
    counts = Counter(r.get("status", "") for r in rows)
    print(f"共 {len(rows)} 条：" + "，".join(f"{k} {v}" for k, v in counts.items()))
    return report.show(args.limit, args.json)


# ---------- 3 译文校验 ----------

def check_chapter(path, zh_path, glossary, source_lang, report):
    where = zh_path.name
    source = parse_chapter(read_text(path))
    text = read_text(zh_path)
    zh = parse_chapter(text)
    src_keys, zh_keys = list(source["blocks"]), list(zh["blocks"])
    if not zh_keys:
        report.error(where, "译文没有锚点")
        return
    for key in src_keys:
        if key not in zh["blocks"]:
            report.error(f"{where} b{key}", "缺少这一段（锚点不存在）")
    for key in zh_keys:
        if key not in source["blocks"]:
            report.error(f"{where} b{key}", "多出原文没有的锚点")
    shared_src = [k for k in src_keys if k in zh["blocks"]]
    shared_zh = [k for k in zh_keys if k in source["blocks"]]
    if shared_src != shared_zh:
        report.error(where, "段落顺序和原文不一致")
    if len(zh_keys) != len(set(zh_keys)):
        report.error(where, "锚点重复")
    if zh["head"]:
        report.warn(where, f"第一个锚点之前还有文字：{zh['head'][:40]}")
    h1 = re.findall(r"^#\s+\S.*$", zh["body"], re.M)
    if len(h1) != 1:
        report.error(where, f"应有且只有一个一级标题，现有 {len(h1)} 个")

    ratios = {}
    for key in shared_src:
        size = units(source["blocks"][key])
        if size >= 20:
            ratios[key] = units(zh["blocks"][key]) / size
    median = statistics.median(ratios.values()) if ratios else None

    forbidden = []
    for row in glossary:
        for term in split_alt(row.get("forbidden_zh")):
            forbidden.append((term, row.get("zh", "")))
    for term, preferred in forbidden:
        if term in text:
            report.error(where, f"用了禁用译法“{term}”，应为“{preferred}”")

    terms = []
    joined_source = "\n".join(source["blocks"].values())
    for row in glossary:
        names = [row.get("source", "")] + split_alt(row.get("aliases_source"))
        pattern = term_pattern([n for n in names if n.strip()])
        if pattern and row.get("status") != "conflict" and pattern.search(joined_source):
            wanted = [row.get("zh", "")] + split_alt(row.get("aliases_zh"))
            if row.get("status") == "keep_original":
                wanted += names
            terms.append((pattern, [w for w in wanted if w], row.get("source", "")))

    for key in zh_keys:
        block = zh["blocks"][key]
        at = f"{where} b{key}"
        if not block:
            report.error(at, "译文为空")
            continue
        if "\ufffd" in block:
            report.error(at, "含替换字符")
        if m := PLACEHOLDER_RE.search(block):
            report.error(at, f"疑似占位或省略：{m.group(0)}")
        if re.search(r"(?:校注|译者注)[：:]", block):
            report.error(at, "校注和译者注应放进章末注释，不要留在正文")
        for left, right in (("“", "”"), ("《", "》"), ("（", "）")):
            if block.count(left) != block.count(right):
                report.warn(at, f"{left}{right} 数量不配对：{block[:40]}")
        if source_lang != "zh":
            for m in re.finditer(r"(?:[A-Za-z][A-Za-z'’\-]*[\s,;:]+){6,}[A-Za-z]+", strip_refs(block)):
                report.warn(at, f"残留长串外文：{m.group(0)[:60]}")
        source_block = source["blocks"].get(key)
        if source_block is None:
            continue
        if median and key in ratios:
            floor = 0.35 if re.search(r"[぀-ヿ㐀-鿿]", source_block) else 0.7
            if ratios[key] < max(0.45 * median, floor):
                report.warn(at, f"译文明显偏短（{ratios[key]:.2f}，本章中位 {median:.2f}），对照原文查漏译：{source_block[:50]}")
            elif ratios[key] > 2.5 * median:
                report.warn(at, f"译文明显偏长（{ratios[key]:.2f}，本章中位 {median:.2f}），查是否添加了内容")
        missing = numbers(source_block) - numbers(block)
        if missing:
            report.warn(at, "原文数字未在译文中原样出现（如已换算成万、亿，请核对换算结果）：" + ", ".join(list(missing)[:6]))
        for pattern, wanted, name in terms:
            if pattern.search(source_block) and wanted and not any(w in block for w in wanted):
                report.warn(at, f"术语 {name} 在原文出现，译文没有 {wanted[0]}")

    refs = note_refs(zh["body"])
    notes = zh["notes"]
    source_refs_total = len(source["notes"])
    if source_refs_total and len(notes) < source_refs_total:
        report.error(where, f"注释变少：原文 {source_refs_total} 条，译文 {len(notes)} 条")
    if refs or notes:
        if not NOTES_RE.search(text) and notes:
            report.error(where, "缺少“## 注释与引用”标题")
        if list(notes) != list(range(1, len(notes) + 1)):
            report.error(where, "注释没有从 1 连续编号")
        for n in sorted(set(refs) - set(notes)):
            report.error(where, f"正文注号 [{n}] 没有对应的注释")
        for n in sorted(set(notes) - set(refs)):
            report.error(where, f"注释 {n} 在正文里没有注号")
        firsts = list(OrderedDict.fromkeys(refs))
        if firsts != sorted(firsts):
            report.warn(where, "注号不是按出现顺序递增")
    if len(source["notes"]) == len(notes):
        for n, note in notes.items():
            original = source["notes"].get(n)
            if original is not None and (missing := numbers(original) - numbers(note)):
                report.warn(f"{where} 注{n}", "注释里的数字有变化：" + ", ".join(list(missing)[:6]))


def cmd_check(args):
    root = Path(args.project)
    project = load_project(root)
    report = Report()
    glossary = load_glossary(root / "glossary" / "glossary.csv")
    sources = chapter_files(root / "source" / "chapters", args.chapter)
    if not sources:
        print("没有匹配的原文章节。", file=sys.stderr)
        return 2
    done, todo, han = 0, [], 0
    for path in sources:
        zh_path = root / "zh" / path.name
        if not zh_path.exists():
            todo.append(path.name)
            continue
        check_chapter(path, zh_path, glossary, project.get("source_lang", "en"), report)
        han += len(HAN_RE.findall(read_text(zh_path)))
        done += 1
    print(f"已译 {done} / {len(sources)} 章，共 {han} 个汉字。")
    if todo:
        print("未译：" + ", ".join(todo[:12]) + (" ……" if len(todo) > 12 else ""))
        if args.chapter:
            report.error(args.chapter, "这一章还没有译文")
    extra = {p.name for p in chapter_files(root / "zh", args.chapter)} - {p.name for p in sources}
    if extra:
        print("zh/ 里没有原文对应的文件（译者说明等可忽略）：" + ", ".join(sorted(extra)))
    return report.show(args.limit, args.json)


def cmd_style(args):
    root = Path(args.project)
    files = chapter_files(root / "zh", args.chapter)
    if not files:
        print("没有匹配的译文。", file=sys.stderr)
        return 2
    for path in files:
        chapter = parse_chapter(read_text(path))
        text = "\n".join(strip_refs(b) for b in blocks_or_paragraphs(chapter).values())
        size = max(len(HAN_RE.findall(text)), 1)
        sentences = [s.strip() for s in re.split(r"[。！？!?]+|\n+", text) if len(s.strip()) > 1]
        lengths = [len(s) for s in sentences]
        spread = statistics.pstdev(lengths) / statistics.mean(lengths) if lengths else 0
        long_ones = sorted((s for s in sentences if len(s) >= args.long), key=len, reverse=True)
        de_chains = [c for s in sentences for c in re.split(r"[，,；;：:]", s) if c.count("的") >= 4]
        print(f"\n{path.name}：{size} 字，{len(sentences)} 句，句长变异系数 {spread:.2f}")
        for name, pattern in STYLE_PATTERNS.items():
            found = re.findall(pattern, text, re.M)
            if found:
                print(f"  {name}：{len(found)}（每千字 {len(found) * 1000 / size:.1f}）")
        words = [w for w in AI_WORDS if w in text]
        if words:
            print("  AI 腔词汇：" + "、".join(f"{w}×{text.count(w)}" for w in words))
        print(f"  ≥{args.long} 字的长句：{len(long_ones)}")
        for s in long_ones[:args.samples]:
            print(f"    · {s[:90]}{'……' if len(s) > 90 else ''}")
        print(f"  “的”字串（一小句 ≥4 个）：{len(de_chains)}")
        for c in de_chains[:args.samples]:
            print(f"    · {c[:90]}")
    print("\n以上只是定位信号，要不要改看语境。")
    return 0


# ---------- 4 引文台账 ----------

QUOTE_RE = re.compile(r"“[^”]{4,}”")
REF_PATTERN = r"(?:\\?\[(\d+)\\?\](?!\()|〔(\d+)〕)"
QUOTE_TAIL_RE = re.compile(rf"(【原文待核】)?[^“”\n。！？]{{0,16}}?[。！？，；]?(【原文待核】)?\s*{REF_PATTERN}")
MARKER_TAIL_RE = re.compile(r"[。，；：、]?【原文待核】")
MARKER_NOTE_RE = re.compile(rf"[。！？，；”]*\s*{REF_PATTERN}")


def find_citations(block):
    """找出带注号或待核标记的引文，以及引号之外的待核标记。返回 (摘录, 注号, 是否有标记)。"""
    if block.startswith(">") and (note_refs(block) or PENDING in block):
        refs = note_refs(block)
        return [(block, str(refs[0]) if refs else "", PENDING in block)]
    found, covered = [], []
    for m in QUOTE_RE.finditer(block):
        tail = block[m.end():m.end() + 40]
        hit = QUOTE_TAIL_RE.match(tail)
        if hit:
            marked = bool(hit.group(1) or hit.group(2))
            found.append((m.group(0), hit.group(3) or hit.group(4), marked))
            if marked:
                covered.append(block.find(PENDING, m.end()))
        else:
            marker = MARKER_TAIL_RE.match(tail)
            if marker:
                found.append((m.group(0), "", True))
                covered.append(m.end() + marker.end() - len(PENDING))
    for m in re.finditer(PENDING, block):
        if m.start() in covered:
            continue
        note = MARKER_NOTE_RE.match(block[m.end():m.end() + 12])
        found.append((block[max(0, m.start() - 40):m.start()] + PENDING,
                      (note.group(1) or note.group(2)) if note else "", True))
    return found


def norm_space(text):
    return re.sub(r"\s+", "", text)


def load_ledger(root):
    path = Path(root) / "audit" / "citations.json"
    if not path.exists():
        return path, {"round": 0, "date": "", "access_limits": [], "acceptances": [], "requests": [], "records": []}
    return path, json.loads(read_text(path))


def cmd_audit_scan(args):
    root = Path(args.project)
    path, ledger = load_ledger(root)
    records = ledger.setdefault("records", [])
    known = set()
    for record in records:
        known.add((record["file"], record.get("anchor"), norm_space(record.get("excerpt", ""))))
        if record.get("replacement"):
            known.add((record["file"], record.get("anchor"), norm_space(record["replacement"])))
    added = 0
    for zh_path in chapter_files(root / "zh", args.chapter):
        chapter = parse_chapter(read_text(zh_path))
        prefix = zh_path.name.split("_")[0]
        used = [int(r["id"].rsplit("-", 1)[1]) for r in records
                if r.get("file") == zh_path.name and re.fullmatch(r".+-\d+", r.get("id", ""))]
        sequence = max(used, default=0)
        items = [(k if k.startswith("p") else f"b{k}", v) for k, v in blocks_or_paragraphs(chapter).items()]
        items += [(f"note-{n}", text) for n, text in chapter["notes"].items() if PENDING in text]
        for anchor, block in items:
            is_note = anchor.startswith("note-")
            for excerpt, note, marked in find_citations(block):
                key = (zh_path.name, anchor, norm_space(excerpt))
                if key in known or (is_note and not marked):
                    continue
                known.add(key)
                sequence += 1
                added += 1
                note = anchor[5:] if is_note else note
                records.append({
                    "id": f"{prefix}-{sequence:02d}", "file": zh_path.name, "anchor": anchor, "note": note,
                    "excerpt": excerpt, "note_text": chapter["notes"].get(int(note), "") if note else "",
                    "has_marker": marked, "status": "not_reviewed", "sources": [], "replacement": "",
                    "research_note": "", "next_action": ""})
    write_json(path, ledger)
    print(f"新增 {added} 条，台账共 {len(records)} 条。没有注号的引文和间接转述要通读时手工补。")
    return 0


def expected_markers(records):
    total = Counter()
    for record in records:
        if record.get("status") in AUDIT_MARKED or (record.get("status") == "not_reviewed" and record.get("has_marker")):
            total[record.get("file")] += int(record.get("markers", 1))
    return total


def cmd_audit_check(args):
    root = Path(args.project)
    report = Report()
    _, ledger = load_ledger(root)
    records = ledger.get("records", [])
    seen = set()
    texts = {p.name: read_text(p) for p in chapter_files(root / "zh")}
    for record in records:
        rid = record.get("id", "?")
        if rid in seen:
            report.error(rid, "编号重复")
        seen.add(rid)
        status = record.get("status")
        if status not in AUDIT_STATUS:
            report.error(rid, f"状态不合法：{status}")
            continue
        if record.get("file") not in texts and status != "not_applicable":
            report.error(rid, f"章节文件不存在：{record.get('file')}")
            continue
        if status in AUDIT_DONE:
            sources = record.get("sources") or []
            if not sources:
                report.error(rid, f"{status} 需要来源")
            for source in sources:
                if not source.get("title") or not (source.get("url") or source.get("localPath") or source.get("page")):
                    report.error(rid, "来源要有题名，以及链接、本地路径或页码之一")
                if source.get("level") not in AUDIT_LEVELS:
                    report.error(rid, f"证据级别不合法：{source.get('level')}")
                if source.get("level") in ("published_translation", "scan_original") and not source.get("page"):
                    report.warn(rid, "用了印本或页图，应写明页码")
        if status in ("restored", "verified_original"):
            replacement = record.get("replacement", "")
            if status == "restored" and not replacement:
                report.error(rid, "restored 需要写明替换后的文字（replacement）")
            if replacement and norm_space(replacement) not in norm_space(texts[record["file"]]):
                report.error(rid, f"replacement 没有出现在 {record['file']}：{replacement[:40]}")
        if status == "back_translated" and not (record.get("acceptance") or ledger.get("acceptances")):
            report.error(rid, "回译需要用户授权，请记入 acceptance 或 acceptances")
        if status in AUDIT_MARKED and not (record.get("research_note") or record.get("next_action")):
            report.warn(rid, "待核条目应写明查过什么、下一步是什么")
        if args.final and status == "not_reviewed":
            report.error(rid, "尚未核查")
    expected = expected_markers(records)
    for name, text in texts.items():
        actual = text.count(PENDING)
        if actual != expected.get(name, 0):
            report.error(name, f"{PENDING} 正文有 {actual} 处，台账应为 {expected.get(name, 0)} 处")
    counts = Counter(r.get("status") for r in records)
    print(f"台账共 {len(records)} 条：" + ("，".join(f"{k} {v}" for k, v in counts.items()) or "无"))
    print(f"正文待核标记：{sum(t.count(PENDING) for t in texts.values())} 处")
    return report.show(args.limit, args.json)


# ---------- 5 润色 ----------

def cmd_polish_start(args):
    root = Path(args.project)
    pointer = root / "polish" / "baseline.txt"
    if pointer.exists() and not args.new_round:
        print(f"已有基线：{read_text(pointer).strip()}。开始新一轮润色请加 --new-round。", file=sys.stderr)
        return 2
    (root / "polish").mkdir(exist_ok=True)
    name = f"baseline-{datetime.now():%Y%m%d-%H%M%S}.zip"
    with zipfile.ZipFile(root / "polish" / name, "w", zipfile.ZIP_DEFLATED) as archive:
        files = chapter_files(root / "zh")
        for path in files:
            archive.write(path, path.name)
    pointer.write_text(name + "\n", encoding="utf-8")
    print(f"已备份 {len(files)} 章到 polish/{name}")
    return 0


def quotes_in(block):
    return Counter(norm_space(q) for q in re.findall(r"“([^”]*)”", strip_refs(block)))


def cmd_polish_check(args):
    root = Path(args.project)
    pointer = root / "polish" / "baseline.txt"
    if not pointer.exists():
        print("还没有基线，先运行 polish-start。", file=sys.stderr)
        return 2
    report = Report()
    baseline = read_text(pointer).strip()
    edits, note_edits = [], []
    with zipfile.ZipFile(root / "polish" / baseline) as archive:
        names = set(archive.namelist())
        for path in chapter_files(root / "zh", args.chapter):
            if path.name not in names:
                report.warn(path.name, "基线里没有这个文件")
                continue
            old = parse_chapter(archive.read(path.name).decode("utf-8").replace("\r\n", "\n"))
            new = parse_chapter(read_text(path))
            old_blocks, new_blocks = blocks_or_paragraphs(old), blocks_or_paragraphs(new)
            if list(old_blocks) != list(new_blocks):
                report.error(path.name, "润色改变了段落或顺序")
            if list(old["notes"]) != list(new["notes"]):
                report.error(path.name, "润色改变了注释数量或编号")
            for n, note in new["notes"].items():
                if n in old["notes"] and norm_space(old["notes"][n]) != norm_space(note):
                    note_edits.append({"file": path.name, "note": n, "before": old["notes"][n], "after": note})
            for key, block in new_blocks.items():
                before = old_blocks.get(key)
                if before is None or norm_space(before) == norm_space(block):
                    continue
                label = key if key.startswith("p") else f"b{key}"
                at = f"{path.name} {label}"
                edits.append({"file": path.name, "anchor": label, "before": before, "after": block})
                if numbers(before) != numbers(block):
                    report.warn(at, "数字有变化，确认是在修错而不是改坏")
                if note_refs(before) != note_refs(block):
                    report.error(at, "注号有变化")
                if args.protect_quotes and quotes_in(before) != quotes_in(block):
                    report.error(at, "引号内文字有变化（如确系纠错，回原文确认后记入 logs/decisions.md）")
    _, ledger = load_ledger(root)
    for record in ledger.get("records", []):
        if record.get("status") in ("restored", "verified_original") and record.get("replacement"):
            target = root / "zh" / record.get("file", "")
            if target.exists() and norm_space(record["replacement"]) not in norm_space(read_text(target)):
                report.error(record["id"], "已落实的引文被改动了")
    write_json(root / "polish" / "polish-log.json", {
        "baseline": baseline, "checked_at": datetime.now().isoformat(timespec="seconds"),
        "changed_blocks": len(edits), "changed_notes": len(note_edits), "edits": edits, "note_edits": note_edits})
    print(f"相对基线改动 {len(edits)} 段、{len(note_edits)} 条注释，记录在 polish/polish-log.json")
    return report.show(args.limit, args.json)


# ---------- 合并中文 MD ----------

MERGED_DIR = "zh_merged"
MERGED_NAME = "book_zh.md"
MERGE_STATE = ".merge-state.json"
FILE_MARK_RE = re.compile(r"^<!--file:([^>\n]+?\.md)-->[ \t]*$", re.M)
MERGED_HEADER = ("<!-- 全书中文 MD，由 zh/ 的逐章文件合并而成，可以直接修改。改完运行 unmerge 写回逐章文件。"
                 "不要改动 file 标记和 b 开头的段落锚点。 -->\n")


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def clean_chapter(text):
    return text.strip("\n") + "\n"


def render_merged(root):
    chapters = {p.name: clean_chapter(read_text(p)) for p in chapter_files(Path(root) / "zh")}
    parts = [f"<!--file:{name}-->\n{text}" for name, text in chapters.items()]
    return MERGED_HEADER + "\n" + "\n".join(parts), chapters


def load_merge_state(root):
    path = Path(root) / MERGED_DIR / MERGE_STATE
    return json.loads(read_text(path)) if path.exists() else {}


def save_merged(root, text, chapters):
    folder = Path(root) / MERGED_DIR
    folder.mkdir(exist_ok=True)
    (folder / MERGED_NAME).write_text(text, encoding="utf-8", newline="\n")
    write_json(folder / MERGE_STATE, {
        "merged": sha(text), "chapters": {name: sha(body) for name, body in chapters.items()}})


def merged_status(root):
    """返回 missing（未合并）、current（与逐章一致）、stale（逐章较新）或 edited（合并文件有人工修改）。"""
    path = Path(root) / MERGED_DIR / MERGED_NAME
    if not path.exists():
        return "missing"
    current = read_text(path)
    rendered, _ = render_merged(root)
    if current == rendered:
        return "current"
    return "stale" if sha(current) == load_merge_state(root).get("merged") else "edited"


def cmd_merge(args):
    root = Path(args.project)
    rendered, chapters = render_merged(root)
    if not chapters:
        print("zh/ 里没有章节。", file=sys.stderr)
        return 2
    path = root / MERGED_DIR / MERGED_NAME
    if merged_status(root) == "edited":
        if not args.force:
            print(f"{path} 有人工修改还没写回 zh/。先运行 unmerge；要放弃这些修改请加 --force（会先备份）。", file=sys.stderr)
            return 1
        backup = path.with_name(f"book_zh.bak-{datetime.now():%Y%m%d-%H%M%S}.md")
        backup.write_text(read_text(path), encoding="utf-8", newline="\n")
        print(f"已备份原合并文件：{backup}")
    save_merged(root, rendered, chapters)
    print(f"已合并 {len(chapters)} 章：{path}")
    return 0


def cmd_unmerge(args):
    root = Path(args.project)
    path = root / MERGED_DIR / MERGED_NAME
    if not path.exists():
        print(f"找不到 {path}，先运行 merge。", file=sys.stderr)
        return 2
    text = read_text(path)
    marks = list(FILE_MARK_RE.finditer(text))
    report = Report()
    leading = re.sub(r"<!--.*?-->", "", text[:marks[0].start()] if marks else text, flags=re.S).strip()
    if leading or not marks:
        report.error(MERGED_NAME, "第一个 file 标记之前有正文，或者找不到 file 标记")
    sections = OrderedDict()
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        name = mark.group(1).strip()
        if name in sections:
            report.error(name, "file 标记重复")
        sections[name] = clean_chapter(text[mark.end():end])
    existing = {p.name: clean_chapter(read_text(p)) for p in chapter_files(root / "zh")}
    for name in sorted(set(existing) - set(sections)):
        report.error(name, "合并文件里缺少这一章的 file 标记")
    for name in sorted(set(sections) - set(existing)):
        report.error(name, "zh/ 里没有这个文件，file 标记可能被改过")
    base = load_merge_state(root).get("chapters", {})
    to_write, kept = [], []
    for name, new in sections.items():
        current = existing.get(name)
        if current is None or new == current:
            continue
        merged_changed = sha(new) != base.get(name)
        chapter_changed = sha(current) != base.get(name)
        if merged_changed and chapter_changed and not args.force:
            report.error(name, "合并文件和逐章文件都改过，需要手工合并；确认以合并文件为准请加 --force")
        elif merged_changed:
            to_write.append(name)
        else:
            kept.append(name)
    if report.errors:
        print("没有写入任何文件。")
        return report.show()
    for name in to_write:
        (root / "zh" / name).write_text(sections[name], encoding="utf-8", newline="\n")
    rendered, chapters = render_merged(root)
    save_merged(root, rendered, chapters)
    print(f"写回 {len(to_write)} 章" + (f"：{', '.join(to_write)}" if to_write else ""))
    if kept:
        print("这些章的逐章文件较新，已保留：" + ", ".join(kept))
    print("接着运行 check 和 audit-check，再重新合成。")
    return 0


# ---------- 进度 ----------

def cmd_status(args):
    root = Path(args.project)
    project = load_project(root)
    sources = chapter_files(root / "source" / "chapters")
    translated, partial = [], []
    for path in sources:
        zh_path = root / "zh" / path.name
        if not zh_path.exists():
            continue
        source_keys = list(parse_chapter(read_text(path))["blocks"])
        blocks = parse_chapter(read_text(zh_path))["blocks"]
        filled = [k for k in source_keys if blocks.get(k)]
        (translated if len(filled) == len(source_keys) else partial).append(f"{path.name}（{len(filled)}/{len(source_keys)}）")
    glossary = load_glossary(root / "glossary" / "glossary.csv")
    _, ledger = load_ledger(root)
    records = ledger.get("records", [])
    audit = Counter(r.get("status") for r in records)
    progress = project.get("progress", {})
    covers = [p.name for p in (root / "cover").glob("cover.*")] if (root / "cover").exists() else []
    backs = [p.name for p in (root / "cover").glob("back.*")] if (root / "cover").exists() else []
    source_names = {p.name.split("_")[0] for p in sources}
    polished = {str(c).split("_")[0] for c in progress.get("polished_chapters", [])} & source_names
    builds = [p.name for p in (root / "build").glob("*.pdf")] if (root / "build").exists() else []
    print(f"书名：{project.get('title_source')} → {project.get('title_zh') or '（未定）'}")
    print(f"语言：{project.get('source_lang')} → {project.get('target_lang')}；体裁：{project.get('genre')}")
    print(f"原文章节：{len(sources)}")
    print(f"术语表：{len(glossary)} 条（" + "，".join(f"{k} {v}" for k, v in Counter(r.get('status') for r in glossary).items()) + "）")
    print(f"已译完：{len(translated)} 章；未译完：{len(partial)} 章" + (f"（{'; '.join(partial[:6])}）" if partial else ""))
    print(f"引文台账：{len(records)} 条" + ("（" + "，".join(f"{k} {v}" for k, v in audit.items()) + "）" if records else "") + f"，第 {ledger.get('round', 0)} 轮")
    print(f"已润色：{len(polished)} 章（来自 project.json 的 progress.polished_chapters）")
    merged = merged_status(root) if chapter_files(root / "zh") else "missing"
    print("合并 MD：" + {"missing": "未生成", "current": f"{MERGED_DIR}/{MERGED_NAME}，与逐章文件一致",
                       "stale": f"{MERGED_DIR}/{MERGED_NAME}，逐章文件较新，合成时会自动更新",
                       "edited": f"{MERGED_DIR}/{MERGED_NAME}，有人工修改还没写回"}[merged])
    print("封面：" + (", ".join(covers) or "无（合成时用自动文字封面）") + "；封底：" + (", ".join(backs) or "无"))
    print("PDF：" + (", ".join(builds) or "无"))
    both_built = any(n.endswith("_阅读版.pdf") for n in builds) and any(not n.endswith("_阅读版.pdf") for n in builds)
    if len(sources) == 0:
        step = "整理原文 MD 并拆章（references/source-md.md）"
    elif not glossary:
        step = "建专有名词总表（references/glossary.md）"
    elif len(translated) < len(sources):
        step = "继续逐章翻译（references/translation.md）"
    elif audit.get("not_reviewed") or (not records and not ledger.get("round")):
        step = "引文核查（references/citation-audit.md）。没有引文的书运行 audit-scan 后把台账 round 设为 1 即可跳过"
    elif len(polished) < len(sources):
        step = "润色（references/polish.md）"
    elif not covers or not backs or not both_built:
        step = "封面、封底与合成，要出完整版和阅读版两份 PDF（references/assembly.md）"
    else:
        step = "看 build/ 里的两个 validation 文件，目视检查后交付（references/assembly.md）"
    if merged == "edited":
        step = "合并 MD 有人工修改，先运行 unmerge 写回 zh/"
    print(f"建议下一步：{step}")
    if progress.get("next"):
        print(f"上次记录的下一步：{progress['next']}")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description="书籍翻译流程工具")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name, func, help_text):
        p = sub.add_parser(name, help=help_text)
        p.set_defaults(func=func)
        return p

    def common(p):
        p.add_argument("--limit", type=int, default=40, help="最多显示多少条")
        p.add_argument("--json", help="把全部结果写入 JSON 文件")

    p = add("init", cmd_init, "建项目目录")
    p.add_argument("dir")
    p.add_argument("--title", required=True)
    p.add_argument("--title-zh")
    p.add_argument("--author")
    p.add_argument("--source-lang", default="en")
    p.add_argument("--genre", default="academic", choices=["academic", "nonfiction", "fiction", "other"])

    add("inspect", cmd_inspect, "查看 PDF 文字层").add_argument("pdf")

    p = add("split", cmd_split, "全书 MD 拆章并加锚点")
    p.add_argument("book")
    p.add_argument("--out", required=True)
    p.add_argument("--force", action="store_true")

    p = add("source-check", cmd_source_check, "查原文的 OCR 和提取问题")
    p.add_argument("chapters")
    common(p)

    p = add("terms", cmd_terms, "提取专名候选")
    p.add_argument("chapters")
    p.add_argument("--glossary")
    p.add_argument("--out")
    p.add_argument("--min-count", type=int, default=2)
    p.add_argument("--limit", type=int, default=80)

    p = add("glossary-check", cmd_glossary_check, "检查术语表")
    p.add_argument("glossary")
    p.add_argument("--source-lang", help="默认读项目的 project.json")
    common(p)

    p = add("check", cmd_check, "译文对原文校验")
    p.add_argument("project")
    p.add_argument("--chapter", help="文件名前缀，如 03")
    common(p)

    p = add("style", cmd_style, "翻译腔和 AI 腔信号")
    p.add_argument("project")
    p.add_argument("--chapter")
    p.add_argument("--long", type=int, default=70)
    p.add_argument("--samples", type=int, default=5)

    p = add("audit-scan", cmd_audit_scan, "从译文生成引文台账")
    p.add_argument("project")
    p.add_argument("--chapter")

    p = add("audit-check", cmd_audit_check, "校验引文台账")
    p.add_argument("project")
    p.add_argument("--final", action="store_true", help="还有未核查条目时报错")
    common(p)

    p = add("polish-start", cmd_polish_start, "润色前备份")
    p.add_argument("project")
    p.add_argument("--new-round", action="store_true")

    p = add("polish-check", cmd_polish_check, "润色后校验")
    p.add_argument("project")
    p.add_argument("--chapter")
    p.add_argument("--protect-quotes", action="store_true", help="引号内文字不许变（学术书用）")
    common(p)

    p = add("merge", cmd_merge, "把 zh/ 合并成全书中文 MD")
    p.add_argument("project")
    p.add_argument("--force", action="store_true", help="放弃合并文件里的人工修改（会先备份）")

    p = add("unmerge", cmd_unmerge, "把全书中文 MD 的修改写回 zh/")
    p.add_argument("project")
    p.add_argument("--force", action="store_true", help="两边都改过时以合并文件为准")

    add("status", cmd_status, "项目进度").add_argument("project")
    return parser


def main():
    args = build_parser().parse_args()
    try:
        code = args.func(args)
        sys.stdout.flush()
        return code
    except OSError as err:
        # 输出被 head 等提前关闭。Windows 上报的是 EINVAL，不是 BrokenPipeError。
        # 文件操作的 OSError 带文件名，照常抛出。
        if not isinstance(err, BrokenPipeError) and (err.errno != errno.EINVAL or err.filename is not None):
            raise
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 141  # 结果被截断，不能当作通过


if __name__ == "__main__":
    raise SystemExit(main())
