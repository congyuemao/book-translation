#!/usr/bin/env python3
"""按译本页码重做原书索引（阶段 6，用户要索引时用）。

    python index_tool.py <项目目录> <完整版 PDF> --prefix 16 [--terms glossary/index_terms.tsv]
                         [--overrides glossary/index_overrides.json] [--dry-run]

前提：
- 原文 source/chapters 的段落锚点带原书页码（<!--b014 p.95-->）。EPUB 用 epub2md.py 转、再用 booktool.py split 拆章，
  就会带上。没有原书页码就没法换算。
- 原书索引已整理成 source/chapters/<前缀>_*.md，每个词条一段：“Head: 12, 45–47”，有子条目的写成
  “Head: sub one: 12; sub two: 30”，参见写成“Head: see Other”。
- 词条译名表 --terms（TSV，表头 anchor、source、zh）：每个词条的中文名。有子条目的，source 和 zh 都用分号
  （英文 ; 、中文 ；）分开，第一项是主条目。
- 原书索引里排版出错、一段挤了两个词条之类的，写进 --overrides（JSON）：
  {"b276": [["无产阶级", "proletariat", "SEE工人阶级"], ["蒲鲁东，皮埃尔-约瑟夫", "Proudhon, Pierre-Joseph", "11, 14, 28"]]}

做法（同一本书上，单页引用的核实率从直接搜中文的约 86% 提高到 97% 以上）：
1. 在完整版 PDF 里给每个中文段落定位页码。
2. 原书单页引用 p：先在原书第 p 页的英文段落里找词条，找到了就落到对应中文段所在的页（段落跨页时，
   看中文关键词出现在哪页，或按词在英文段里的位置估计）。
3. 英文段里找不到（原书索引常有一两页的出入）：在原书第 p 页对应的中文页码范围里找中文关键词。
4. 连续页码 a–b：从 a 页第一段所在页算到 b 页最后一段所在页。
5. 补查：中文关键词（含术语表别名）不在该页时，先在前后两页找，再在前后八页找，全书只出现一页的就用那一页；
   还对不上的列为“未能核实”，原样换算，不改。
结果写回 zh/<前缀>_*.md（保留第一段的标题和说明），报告写到 build/index_report.txt。
PDF 的页码必须就是书上印的页码（build_book.mjs 从封面算起，正好如此）。改了任何正文都要重新出一次完整版、
重跑本脚本，再合成两版。
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BLOCK = re.compile(r"<!--b(\d+)(?:\s+p\.([^\s>]+))?-->\n(.*?)(?=\n\n<!--b|\n\n##\s+注释|\Z)", re.S)
norm = lambda s: re.sub(r"[\s⁠­]+", "", s)


def roman(s):
    v = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
    s = s.lower()
    return sum(-v[c] if i + 1 < len(s) and v[s[i + 1]] > v[c] else v[c] for i, c in enumerate(s))


def plain(text):
    t = re.sub(r"^>\s*|^#+\s*", "", text, flags=re.M)
    t = re.sub(r"\[\d+\]|【原文待核】|\*|<[^>]+>|\\", "", t)
    return norm(t)


def chapter_files(root, base):
    return {p.name.split("_")[0]: p for p in sorted((Path(root) / base).glob("*.md"))}


def main():
    ap = argparse.ArgumentParser(description="按译本页码重做原书索引")
    ap.add_argument("project"); ap.add_argument("pdf")
    ap.add_argument("--prefix", required=True, help="索引那一章的文件名前缀，如 16")
    ap.add_argument("--terms", default="glossary/index_terms.tsv")
    ap.add_argument("--overrides", default="glossary/index_overrides.json")
    ap.add_argument("--dry-run", action="store_true", help="只报告，不写文件")
    ap.add_argument("--out", help="写到这个文件，不覆盖 zh 里的索引（比对用）")
    a = ap.parse_args()
    try:
        from pypdf import PdfReader
    except ImportError:
        sys.exit("需要 pypdf：python -m pip install pypdf")
    root = Path(a.project)
    pages = [norm(p.extract_text() or "") for p in PdfReader(a.pdf).pages]
    toc = next((i for i, t in enumerate(pages) if "目录" in t[:12]), 0)
    # 索引那一章的首页：书眉后面紧跟“索引”二字。找不到就当没有索引页。
    index_start = next((i for i in range(toc + 1, len(pages)) if re.match(r"^\D{0,40}?\d*索引", pages[i])), len(pages))

    zh_files, src_files = chapter_files(root, "zh"), chapter_files(root, "source/chapters")
    body_prefixes = [k for k in sorted(zh_files) if k in src_files and k != a.prefix]

    # 1. 中文段落 → PDF 页
    blockpage, chapter_end, cursor, unlocated = {}, {}, toc + 1, 0
    for pre in body_prefixes:
        text = zh_files[pre].read_text(encoding="utf-8").split("\n## 注释与引用")[0]
        for m in BLOCK.finditer(text + "\n\n"):
            s = plain(m.group(3))
            if not s:
                continue
            found = None
            for probe in (s[:16], s[len(s) // 3:len(s) // 3 + 12], s[-12:]):
                for pn in range(cursor, min(cursor + 12, index_start)):
                    if probe and probe in pages[pn]:
                        found = pn
                        break
                if found is not None:
                    break
            if found is None:
                unlocated += 1
                found = cursor
            blockpage[(pre, int(m.group(1)))] = cursor = found
        end = cursor
        for pn in range(cursor, min(cursor + 12, index_start)):
            if "注释与引用" in pages[pn]:
                end = pn
                break
        chapter_end[pre] = end
    keys_sorted = sorted(blockpage)
    pos = {k: i for i, k in enumerate(keys_sorted)}

    def block_end(k):
        i = pos[k]
        if i + 1 < len(keys_sorted) and keys_sorted[i + 1][0] == k[0]:
            return blockpage[keys_sorted[i + 1]]
        return chapter_end[k[0]]

    # 2. 原书页 → 英文段落
    order = []
    for pre in body_prefixes:
        for m in BLOCK.finditer(src_files[pre].read_text(encoding="utf-8") + "\n\n"):
            if m.group(2) and (pre, int(m.group(1))) in blockpage:
                order.append((m.group(2), pre, int(m.group(1)), m.group(3)))
    labels = []
    for lab, *_ in order:
        if lab not in labels:
            labels.append(lab)

    def page_no(label):
        return int(label) if label.isdigit() else -1000 + roman(label) if re.fullmatch(r"[ivxlcdm]+", label, re.I) else None

    def blocks_on(label):
        """原书这一页上的段落：从这页开始的段，加上从前一页延续过来的那一段。
        整页都在一个长段中间、没有段落从这页开始的，就取覆盖这一页的那一段。"""
        res = []
        for i, (lab, pre, b, txt) in enumerate(order):
            if lab == label:
                if not res and i > 0 and order[i - 1][0] != label:
                    res.append(order[i - 1])
                res.append(order[i])
        if not res and page_no(label) is not None:
            before = [x for x in order if page_no(x[0]) is not None and page_no(x[0]) < page_no(label)]
            if before:
                res.append(before[-1])
        return res

    # 3. 中文关键词（含术语表别名）
    alias = {}
    gl = root / "glossary" / "glossary.csv"
    if gl.exists():
        with open(gl, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                names = [row.get("zh", "")] + [x for x in (row.get("aliases_zh") or "").split("|") if x]
                for n in names:
                    alias.setdefault(n, set()).update(x for x in names if x)

    def zh_keys(head):
        h = re.sub(r"[《》“”〈〉*]", "", head)
        base = re.split(r"[，,（(：:]", h)[0].strip()
        ks = {base}
        for par in re.findall(r"（([^）]+)）", h):
            if not re.search(r"\d", par):
                ks.update(x for x in re.split(r"[或、]", par) if x)
        ks.update(p for p in re.split(r"与|和|及", base) if len(p) >= 2)
        for n in list(ks) + [base]:
            for al in alias.get(n, ()):
                ks.add(re.sub(r"[《》“”〈〉]", "", al))
        for n in list(ks):
            if "·" in n:
                ks.add(n.split("·")[-1])
        return [norm(k) for k in ks if len(norm(k)) >= 2]

    def en_keys(head):
        h = re.split(r"[:(]", head)[0].replace("*", "").replace('"', "").replace("“", "").replace("”", "").strip()
        ks = [h.split(",")[0].strip()] if "," in h and len(h.split(",")[0].split()) <= 3 else [h]
        if "," not in h:
            ks += sorted((w for w in re.findall(r"[A-Za-z’'-]{5,}", h)), key=len, reverse=True)[:2]
        return [k.lower()[:max(5, min(len(k), 12))] for k in ks if k]

    def has(pn, ks):
        return 0 <= pn < len(pages) and any(k in pages[pn] for k in ks)

    def page_for(label, eks, zks, report, where):
        """原书单页 → 译本页（0 起算）。"""
        cands = blocks_on(label)
        for lab, pre, b, txt in cands:
            low = txt.lower()
            for k in eks:
                j = low.find(k)
                if j >= 0:
                    start, end = blockpage[(pre, b)], block_end((pre, b))
                    span = range(start, max(start, end) + 1)
                    guess = start + int(round((end - start) * j / max(1, len(low))))
                    hit = [pn for pn in span if has(pn, zks)]
                    return (min(hit, key=lambda pn: abs(pn - guess)) if hit else guess), "en"
        if not cands:
            report.append(f"无此原书页 {where}：p.{label}")
            return None, "none"
        lo = blockpage[(cands[0][1], cands[0][2])]
        hi = block_end((cands[-1][1], cands[-1][2]))
        hit = [pn for pn in range(lo, hi + 1) if has(pn, zks)]
        return (hit[0] if hit else lo), ("zh" if hit else "guess")

    def refine(pn, zks, single, how, head, report):
        """补查：关键词不在该页时就近改正。"""
        if has(pn, zks):
            return pn
        for d in (1, 2):
            for q in (pn - d, pn + d):
                if has(q, zks):
                    report.append(f"就近 {head}：{pn + 1}→{q + 1}")
                    return q
        if how == "en":
            return pn  # 英文段落里有这个词，中文用了别的说法，信英文段落的定位
        where = [q for q in range(toc + 1, index_start) if has(q, zks)]
        close = [q for q in where if abs(q - pn) <= 8]
        if close:
            q = min(close, key=lambda q: abs(q - pn))
            report.append(f"稍远 {head}：{pn + 1}→{q + 1}")
            return q
        if len(where) == 1 and single:
            report.append(f"唯一 {head}：{pn + 1}→{where[0] + 1}")
            return where[0]
        report.append(f"未能核实 {head}：第{pn + 1}页（全书出现在 {[q + 1 for q in where[:10]]}）")
        return pn

    def expand(a_, b_):
        if b_ and a_.isdigit() and b_.isdigit() and len(b_) < len(a_):
            b_ = a_[:len(a_) - len(b_)] + b_
        return a_, b_

    def map_refs(tail, en, zh, report):
        zks, eks = zh_keys(zh), en_keys(en)
        refs = re.findall(r"(?<![\w])([ivxlc]+|\d+)(?:\s*[–—-]\s*([ivxlc]+|\d+))?(?![\w])", tail)
        out, singles = [], [r for r in refs if not r[1]]
        for a_, b_ in refs:
            a_, b_ = expand(a_, b_)
            if b_:
                fa, fb = blocks_on(a_), blocks_on(b_)
                if fa and fb:
                    first = ([x for x in fa if x[0] == a_] or fa)[0]
                    last = fb[-1]
                    lo, hi = blockpage[(first[1], first[2])], block_end((last[1], last[2]))
                    out += list(range(lo, max(lo, hi) + 1))
                else:
                    report.append(f"无此原书页 {zh}：{a_}–{b_}")
                continue
            pn, how = page_for(a_, eks, zks, report, zh)
            if pn is None:
                continue
            out.append(refine(pn, zks, len(singles) == 1, how, zh, report))
        return fmt([p + 1 for p in out])

    def fmt(nums):
        nums = sorted(set(nums))
        res, i = [], 0
        while i < len(nums):
            j = i
            while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
                j += 1
            res.append(str(nums[i]) if i == j else f"{nums[i]}—{nums[j]}")
            i = j + 1
        return ", ".join(res)

    # 4. 读词条，生成中文索引
    terms = {}
    tpath = root / a.terms
    if not tpath.exists():
        sys.exit(f"缺词条译名表 {tpath}（TSV，表头 anchor、source、zh）")
    with open(tpath, encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            terms[row["anchor"]] = (row["source"], row["zh"])
    overrides = json.loads((root / a.overrides).read_text(encoding="utf-8")) if (root / a.overrides).exists() else {}
    src_index = src_files[a.prefix].read_text(encoding="utf-8")
    zh_path = zh_files[a.prefix]
    keep_head = next(iter(BLOCK.finditer(zh_path.read_text(encoding="utf-8") + "\n\n")), None)
    out = [f"<!--b{keep_head.group(1)}" + (f" p.{keep_head.group(2)}" if keep_head.group(2) else "") + f"-->\n{keep_head.group(3).strip()}"] if keep_head else []
    report, unmapped = [], []
    for m in BLOCK.finditer(src_index + "\n\n"):
        anchor, text = "b" + m.group(1), m.group(3).strip()
        if keep_head and anchor == "b" + keep_head.group(1):
            continue
        if anchor in overrides:
            segs = overrides[anchor]
        elif anchor in terms:
            en, zh = terms[anchor]
            ens, zhs = [x.strip() for x in en.split(";")], [x.strip() for x in zh.split("；")]
            if len(ens) > 1:
                tails = [p.split(":", 1)[1] if ":" in p else "" for p in text.split(";")]
                segs = [(zhs[0] if k == 0 else f"{zhs[0]}：{zhs[k] if k < len(zhs) else ens[k]}",
                         ens[0] if k == 0 else f"{ens[0]}: {ens[k]}", tails[k] if k < len(tails) else "") for k in range(len(ens))]
            else:
                colon = text.rfind(":")
                segs = [(zh, en, text[colon + 1:] if colon >= 0 else "")]
        else:
            unmapped.append(f"{anchor} {text[:40]}")
            continue
        lines = []
        for z, e, tail in segs:
            e = e.replace("*", "").replace("“", '"').replace("”", '"').strip()
            tail = tail.strip()
            if tail.startswith("SEE"):
                lines.append(f"{z}　*{e}*　见{tail[3:]}")
            elif re.match(r"(?i)see\s", tail) and not re.search(r"\d", tail):
                target = re.sub(r"(?i)^see\s+", "", tail).strip()
                zt = next((zz for ee, zz in terms.values() if ee.lower().startswith(target.lower()[:12])), target)
                lines.append(f"{z}　*{e}*　见{zt.split('；')[0]}")
            else:
                lines.append(f"{z}　*{e}*　{map_refs(tail, e, z, report)}")
        out.append(f"<!--{anchor}" + (f" p.{m.group(2)}" if m.group(2) else "") + "-->\n" + "\n\n".join(lines))

    counts = {k: sum(1 for r in report if r.startswith(k)) for k in ("就近", "稍远", "唯一", "未能核实", "无此原书页")}
    (root / "build").mkdir(exist_ok=True)
    (root / "build" / "index_report.txt").write_text("\n".join(report + [f"缺译名 {u}" for u in unmapped]) + "\n", encoding="utf-8")
    print(f"PDF {len(pages)} 页；中文段落定位 {len(blockpage)} 段，未定位 {unlocated} 段；词条 {len(out)} 个，缺译名 {len(unmapped)} 个")
    print("补查：" + "，".join(f"{k} {v}" for k, v in counts.items()) + "（详见 build/index_report.txt）")
    if not a.dry_run:
        target = Path(a.out) if a.out else zh_path
        target.write_text("\n\n".join(out) + "\n", encoding="utf-8")
        print(f"已写到 {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
