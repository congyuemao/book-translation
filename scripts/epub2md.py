#!/usr/bin/env python3
"""EPUB 转全书 Markdown（阶段 1），保留原书页码，并能回头核对转换有没有丢字。只用 Python 标准库。

    python epub2md.py convert <书.epub> <输出 book.md> [--skip 正则] [--images 图片目录] [--list]
    python epub2md.py check   <书.epub> <source/chapters 目录> [--skip 正则]

convert：
- 按 OPF 的 spine 顺序读每个 XHTML，linear="no" 的跳过；--skip 再按文件名或 id 跳过（默认跳过封面、目录页 nav/toc）。
  先加 --list 看一遍 spine 里有哪些文件、各自的标题，再决定跳过哪些。
- 每个文件成为一章，以 `# 标题` 开头，正好满足 booktool.py split 的要求。文件里没有标题就用 <title>；
  开头连着两个标题、前一个像“Chapter 1”“第一章”“Part II”时，合成一个“Chapter 1: 标题”。其余标题按相对层级降为 ##、###。
- 段落、引文块（> ）、列表、表格、图片、着重（*斜体*、**粗体**）、上下标都转成 Markdown。图片复制到 --images 目录。
- 页码：识别 epub:type="pagebreak"、role="doc-pagebreak"，以及 id 形如 page_12、pg12、p12 的锚点，
  在页码开始的那一段前写 `<!--p.12-->`。booktool.py split 会把页码带进段落锚点（<!--b014 p.12-->），
  以后做索引、核对原书页码都靠它。段落中间换页的，记在该段开头的页码上，跨页的段由后续页码接上。
- 注释：noteref 链接转成 [n]；文末或单独文件里的脚注、尾注（epub:type footnote/endnote/rearnote，
  或 aside、class 含 note 的段）按原样转成段落，转完要人工整理到每章末的“## Notes”下，脚本会提示数量。
check：把 EPUB 每个文件的文字和 source/chapters 里对应的章逐词比对（忽略大小写、标点和 Markdown 标记），
  报告每章第一个不一致的位置。人工整理过原文 MD 之后跑一遍，确认没有丢段落、漏句子。
"""
import argparse
import html.entities
import posixpath
import re
import shutil
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

XHTML = "{http://www.w3.org/1999/xhtml}"
EPUB_NS = "{http://www.idpf.org/2007/ops}"
OPF = "{http://www.idpf.org/2007/opf}"
DEFAULT_SKIP = r"(?i)(^|/)(cover|nav|toc)[^/]*\.x?html?$"
PAGE_ID = re.compile(r"^(?:page|pg|p)[_-]?([0-9ivxlcdm]+)$", re.I)
CHAPTER_LABEL = re.compile(r"^(chapter|part|book|section|kapitel|chapitre|teil|第.{1,6}[章部篇卷])\s*[\w.]*$", re.I)
BLOCK_TAGS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "ul", "ol", "table", "pre", "figure",
              "section", "article", "aside", "header", "footer", "dl", "hr", "body", "nav"}


class Book:
    def __init__(self, path):
        self.zip = zipfile.ZipFile(path)
        container = ET.fromstring(self.zip.read("META-INF/container.xml"))
        self.opf_path = container.find(".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile").get("full-path")
        self.base = posixpath.dirname(self.opf_path)
        opf = ET.fromstring(self.zip.read(self.opf_path))
        self.manifest = {i.get("id"): i for i in opf.find(f"{OPF}manifest")}
        self.spine = []
        for ref in opf.find(f"{OPF}spine"):
            item = self.manifest.get(ref.get("idref"))
            if item is not None and "html" in item.get("media-type", ""):
                self.spine.append((ref.get("idref"), posixpath.join(self.base, item.get("href")), ref.get("linear", "yes")))

    def read_xhtml(self, name):
        raw = self.zip.read(name).decode("utf-8", errors="replace")
        raw = re.sub(r"<!DOCTYPE[^>]*>", "", raw, flags=re.I)

        def entity(m):
            code = html.entities.name2codepoint.get(m.group(1))
            return chr(code) if code else m.group(0)
        raw = re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;|#)(\w+);", entity, raw)
        return ET.fromstring(raw)


def local(el):
    return el.tag.split("}")[-1] if isinstance(el.tag, str) else ""


def page_of(el):
    """如果这个元素是页码标记，返回页码。"""
    t = (el.get(f"{EPUB_NS}type") or "") + " " + (el.get("role") or "")
    if "pagebreak" in t:
        label = el.get("title") or el.get("aria-label") or (el.text or "").strip() or el.get("id", "")
        m = PAGE_ID.match(label)
        return m.group(1) if m else label.strip() or None
    m = PAGE_ID.match(el.get("id", "")) if local(el) in ("a", "span") else None
    return m.group(1) if m else None


def escape(text):
    text = re.sub(r"\s+", " ", text.replace(" ", " "))
    return re.sub(r"([*_`])", r"\\\1", text)


class Converter:
    def __init__(self, book, images_dir):
        self.book = book
        self.images_dir = images_dir
        self.notes_seen = 0

    def inline(self, el, pages, name):
        """把一个元素的行内内容转成 Markdown，页码记成 (页码, 在文字中的位置)。"""
        out = escape(el.text or "")
        for child in el:
            tag = local(child)
            p = page_of(child)
            if p:
                pages.append((p, len(out)))
                out += escape(child.tail or "")
                continue
            sub = []
            inner = self.inline(child, sub, name)
            start = len(out)
            etype = child.get(f"{EPUB_NS}type") or ""
            if tag in ("em", "i", "cite") and inner.strip():
                wrapped, shift = f"*{inner.strip()}*", 1
            elif tag in ("strong", "b") and inner.strip():
                wrapped, shift = f"**{inner.strip()}**", 2
            elif tag in ("sup", "sub"):
                linked = any(local(c) == "a" and (c.get("href") or "").find("#") >= 0 for c in child)
                if "noteref" in etype or (tag == "sup" and linked and re.fullmatch(r"\[?\d+\]?", inner.strip())):
                    wrapped, shift = f"[{inner.strip().strip('[]')}]", 1
                else:
                    wrapped, shift = f"<{tag}>{inner}</{tag}>", 5
            elif tag == "a" and "noteref" in etype:
                wrapped, shift = f"[{inner.strip().strip('[]')}]", 1
            elif tag == "br":
                wrapped, shift = "  \n", 0
            elif tag == "img":
                wrapped, shift = self.image(child, name), 0
            else:
                wrapped, shift = inner, 0
            for pg, off in sub:
                pages.append((pg, start + shift + off))
            out += wrapped + escape(child.tail or "")
        return out

    def image(self, el, name):
        src = el.get("src") or el.get("{http://www.w3.org/1999/xlink}href") or ""
        if not src or not self.images_dir:
            return ""
        path = posixpath.normpath(posixpath.join(posixpath.dirname(name), src))
        try:
            data = self.book.zip.read(path)
        except KeyError:
            return ""
        self.images_dir.mkdir(parents=True, exist_ok=True)
        target = self.images_dir / posixpath.basename(path)
        target.write_bytes(data)
        return f"![{el.get('alt', '')}]({self.images_dir.name}/{target.name})"

    def blocks(self, el, name, out):
        """深度优先收集块级元素，返回 [(种类, 文本, 页码列表)]。"""
        for child in el:
            tag = local(child)
            p = page_of(child)
            if p and not len(child) and not (child.text or "").strip():
                out.append(("page", p, []))
                if (child.tail or "").strip():
                    out.append(("p", escape(child.tail), []))
                continue
            etype = child.get(f"{EPUB_NS}type") or ""
            classes = child.get("class", "")
            if re.match(r"h[1-6]$", tag):
                pages = []
                out.append((tag, self.inline(child, pages, name).replace("**", "").strip(), pages))
            elif tag in ("p",) or (tag == "div" and not any(local(c) in BLOCK_TAGS for c in child)):
                pages = []
                text = self.inline(child, pages, name).strip()
                if any(k in etype for k in ("footnote", "endnote", "rearnote")) or re.search(r"\bnote", classes):
                    self.notes_seen += 1
                if text or pages:
                    out.append(("p", text, pages))
            elif tag == "blockquote":
                sub = []
                self.blocks(child, name, sub)
                if not any(k in ("p", "h1", "h2") for k, _, _ in sub):
                    pages = []
                    sub = [("p", self.inline(child, pages, name).strip(), pages)]
                for kind, text, pages in sub:
                    out.append(("q", text, pages) if kind == "p" else (kind, text, pages))
            elif tag in ("ul", "ol"):
                lines, pages = [], []
                for i, li in enumerate([c for c in child if local(c) == "li"], 1):
                    sub = []
                    text = self.inline(li, sub, name).strip()
                    mark = f"{i}. " if tag == "ol" else "- "
                    pages += [(pg, 0) for pg, _ in sub]
                    lines.append(mark + text)
                out.append(("list", "\n".join(lines), pages))
            elif tag == "table":
                rows = []
                for tr in child.iter(f"{XHTML}tr"):
                    cells = [self.inline(td, [], name).strip().replace("|", "\\|") for td in tr if local(td) in ("td", "th")]
                    if cells:
                        rows.append("| " + " | ".join(cells) + " |")
                if rows:
                    width = rows[0].count(" | ") + 1
                    rows.insert(1, "|" + " --- |" * width)
                    out.append(("table", "\n".join(rows), []))
            elif tag == "pre":
                out.append(("pre", "```\n" + "".join(child.itertext()).rstrip() + "\n```", []))
            elif tag == "hr":
                out.append(("p", "* * *", []))
            elif tag in BLOCK_TAGS or tag in ("span", "a"):
                if any(k in etype for k in ("footnote", "endnote", "rearnote")):
                    self.notes_seen += 1
                self.blocks(child, name, out)
            elif tag == "img":
                out.append(("p", self.image(child, name), []))

    def chapter(self, name):
        root = self.book.read_xhtml(name)
        body = root.find(f"{XHTML}body")
        if body is None:
            return None, []
        raw = []
        self.blocks(body, name, raw)
        title_el = root.find(f".//{XHTML}title")
        return (title_el.text or "").strip() if title_el is not None else "", raw


def render(raw, fallback_title):
    """把块列表排成一章 Markdown：保证一个 # 标题，页码标记放在页开始的那一段前面。"""
    heads = [k for k, _, _ in raw if re.match(r"h[1-6]$", k)]
    top = min((int(k[1]) for k in heads), default=1)
    items = raw
    # 合并“Chapter 1”加标题
    merged, i = [], 0
    while i < len(items):
        kind, text, pages = items[i]
        nxt = items[i + 1] if i + 1 < len(items) else None
        if re.match(r"h[1-6]$", kind) and nxt and re.match(r"h[1-6]$", nxt[0]) and CHAPTER_LABEL.match(text.strip()) \
                and not merged:
            merged.append((kind, f"{text.strip()}: {nxt[1].strip()}", pages + nxt[2]))
            i += 2
            continue
        merged.append((kind, text, pages))
        i += 1
    # 每段前都写上它开始时所在的页码：段落中间换页的，下一段从新页算起
    lines, has_h1, current = [], False, None
    for kind, text, pages in merged:
        if kind == "page":
            current = text
            continue
        if not text.strip():
            if pages:
                current = pages[-1][0]
            continue
        start = [p for p, off in pages if off == 0]
        if start:
            current = start[-1]
        if current:
            lines.append(f"<!--p.{current}-->")
        if re.match(r"h[1-6]$", kind):
            level = 1 if not has_h1 else max(2, int(kind[1]) - top + 1)
            has_h1 = True
            lines.append("#" * level + " " + text.strip())
        elif kind == "q":
            lines.append("\n".join("> " + line for line in text.split("\n")))
        else:
            lines.append(text)
        lines.append("")
        later = [p for p, off in pages if off > 0]
        if later:
            current = later[-1]
    if not has_h1:
        lines.insert(0, f"# {fallback_title or '未命名'}\n")
    return "\n".join(lines).rstrip() + "\n"


def cmd_convert(a):
    book = Book(a.epub)
    skip = re.compile(a.skip) if a.skip else None
    images = Path(a.images) if a.images else Path(a.out).parent / "images"
    conv = Converter(book, images)
    parts, report = [], []
    for idref, name, linear in book.spine:
        skipped = linear == "no" or (skip and (skip.search(name) or skip.search(idref)))
        if a.list:
            title, raw = conv.chapter(name)
            words = sum(len(t.split()) for k, t, _ in raw if k != "page")
            print(f"{'跳过' if skipped else '保留'}  {name}  标题：{title[:40]}  约 {words} 词")
            continue
        if skipped:
            continue
        title, raw = conv.chapter(name)
        if not [b for b in raw if b[0] != "page" and b[1].strip()]:
            report.append(f"{name}：没有正文，已跳过")
            continue
        parts.append(render(raw, title))
    if a.list:
        return 0
    text = "\n".join(parts)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(text, encoding="utf-8")
    pages = len(re.findall(r"^<!--p\.", text, re.M))
    chapters = len(re.findall(r"^# ", text, re.M))
    print(f"写出 {a.out}：{chapters} 章，{pages} 处页码标记")
    for line in report:
        print("  " + line)
    if conv.notes_seen:
        print(f"  发现约 {conv.notes_seen} 处脚注或尾注元素，已按段落转出，要人工整理到各章末的“## Notes”下")
    if not pages:
        print("  没有找到页码标记：这本 EPUB 可能不带原书页码，做索引时就没法按原书页码定位")
    print("下一步：人工通读 book.md（删掉书名页、版权页等非正文，核对标题层级），再运行 booktool.py split")
    return 0


def words(text):
    text = re.sub(r"<!--.*?-->|<[^>]+>|!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"^#+ |^> |\\", "", text, flags=re.M)
    return [w for w in (re.sub(r"[^\w]", "", t.lower()) for t in text.split()) if w]


def cmd_check(a):
    book = Book(a.epub)
    skip = re.compile(a.skip) if a.skip else None
    conv = Converter(book, None)
    epub_parts = []
    for idref, name, linear in book.spine:
        if linear == "no" or (skip and (skip.search(name) or skip.search(idref))):
            continue
        title, raw = conv.chapter(name)
        body = " ".join(t for k, t, _ in raw if k != "page")
        if body.strip():
            epub_parts.append((name, words(body)))
    chapters = sorted(Path(a.chapters).glob("*.md"))
    print(f"EPUB 正文文件 {len(epub_parts)} 个，source/chapters {len(chapters)} 章")
    all_epub = [w for _, ws in epub_parts for w in ws]
    all_md = [w for f in chapters for w in words(f.read_text(encoding="utf-8"))]
    if all_epub == all_md:
        print(f"全书逐词一致，共 {len(all_md)} 词")
        return 0
    def locate(seq, start):
        """在 EPUB 词序列里，从 start 附近找到 seq 的开头，找不到就返回 start。"""
        head = seq[:8]
        for d in range(0, 400):
            for p in (start + d, start - d):
                if 0 <= p and all_epub[p:p + len(head)] == head:
                    return p
        return start

    pos, bad = 0, 0
    for f in chapters:
        md = words(f.read_text(encoding="utf-8"))
        pos = locate(md, pos)
        seg = all_epub[pos:pos + len(md)]
        if seg != md:
            bad += 1
            i = next((k for k, (x, y) in enumerate(zip(seg, md)) if x != y), min(len(seg), len(md)))
            print(f"{f.name}：第 {i} 词起不一致  EPUB …{' '.join(seg[max(0, i - 4):i + 6])}…  MD …{' '.join(md[max(0, i - 4):i + 6])}…")
        pos += len(md)
    print(f"EPUB {len(all_epub)} 词，MD {len(all_md)} 词。差异处回 EPUB 看是不是整理时丢了或多了内容")
    return 1


def main():
    ap = argparse.ArgumentParser(description="EPUB 转全书 Markdown，并核对")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("convert"); p.add_argument("epub"); p.add_argument("out")
    p.add_argument("--skip", default=DEFAULT_SKIP); p.add_argument("--images"); p.add_argument("--list", action="store_true")
    p = sub.add_parser("check"); p.add_argument("epub"); p.add_argument("chapters"); p.add_argument("--skip", default=DEFAULT_SKIP)
    a = ap.parse_args()
    return {"convert": cmd_convert, "check": cmd_check}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
