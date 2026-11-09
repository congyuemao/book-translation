#!/usr/bin/env python3
"""逐段润色工具：英中对照、按段提交改稿并校验、长句和翻译腔统计。

前提：译文和原文都有段落锚点（<!--b014-->），并且已经用 booktool.py polish-start 建了润色基线。

    python polish_tool.py pairs  <项目目录> <章前缀> [起段 止段]   # 打印英中对照
    python polish_tool.py apply  <项目目录> <章前缀> <改稿文件>     # 校验并写回，不合格的段退回
    python polish_tool.py lint   <项目目录> <章前缀> [--max-len 50] # 长句清单和翻译腔信号（同基线比）

改稿文件格式（只写要改的段，段间空行）：

    <!--b014-->
    这一段的新全文

    <!--b015-->
    ……

apply 拿每段同润色基线比：注号、作者出处（全角括号里带 *缩写* 的）、数字、待核标记、
引号内文字、引文块（> 开头）、台账里已落实的引文，任何一项变了就退回这一段，不写入。
台账里 status 为 not_applicable 的引文（英语原文等，译者自己译的）允许润色；restored、
verified_original、back_translated 的一字不动。
带文件锁，几个子代理可以同时改同一章的不同段。
"""
import argparse
import json
import os
import re
import sys
import time
import zipfile
from collections import Counter
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ANCHOR = re.compile(r"<!--b(\d+)(?:\s+p\.([^\s>]+))?-->[ \t]*\n")
PATCH_ANCHOR = re.compile(r"^<!--b(\d+)(?:\s+p\.[^\s>]+)?-->[ \t]*$", re.M)
NOTES_HEAD = "\n## 注释与引用\n"
PENDING = "【原文待核】"
EDITABLE_STATUSES = {"not_applicable"}
PROTECTED_STATUSES = {"restored", "verified_original", "back_translated"}

# 翻译腔信号：只是提示，不是硬指标
SIGNALS = {
    "作为": r"作为", "，其": r"，其", "的是": r"的是", "之所以": r"之所以", "就…而言": r"就.{1,10}而言",
    "正如": r"正如", "换句话说/也就是说": r"换句话说|也就是说|换言之", "诚然": r"诚然", "与此同时": r"与此同时",
    "从而": r"从而", "一种": r"一种", "这一": r"这一", "进行": r"进行", "具有": r"具有", "存在": r"存在",
    "对于/关于": r"对于|关于", "某种": r"某种", "被": r"被", "的方式/过程/作用/角色": r"的(?:方式|过程|作用|角色)",
    "在于": r"在于", "然而": r"然而", "因此": r"因此", "此外": r"此外", "尽管": r"尽管",
    "当…时": r"当.{1,14}时[，,]", "并非…而是": r"并非.{1,20}而是", "句首这种/这个": r"(?:^|[。！？])这(?:种|个|些|一)",
}


def chapter_file(root, base, prefix):
    found = sorted((Path(root) / base).glob(prefix + "_*.md"))
    if len(found) != 1:
        sys.exit(f"{base} 里找不到唯一的 {prefix}_*.md")
    return found[0]


def split(text):
    i = text.find(NOTES_HEAD)
    body, notes = (text, "") if i < 0 else (text[:i + 1], text[i + 1:])
    marks = list(ANCHOR.finditer(body))
    blocks = {}
    for k, m in enumerate(marks):
        end = marks[k + 1].start() if k + 1 < len(marks) else len(body)
        blocks[m.group(1)] = (m.group(0), body[m.end():end].strip())
    head = body[:marks[0].start()] if marks else body
    return head, blocks, notes


def baseline_text(root, name):
    pointer = Path(root) / "polish" / "baseline.txt"
    if not pointer.exists():
        sys.exit("还没有润色基线，先运行 booktool.py polish-start")
    zname = pointer.read_text(encoding="utf-8").strip()
    with zipfile.ZipFile(Path(root) / "polish" / zname) as z:
        if name not in z.namelist():
            sys.exit(f"基线里没有 {name}")
        return z.read(name).decode("utf-8").replace("\r\n", "\n")


def norm(s):
    return re.sub(r"\s+", "", s)


def refs(t): return re.findall(r"\[(\d+)\]", t)
def inline_refs(t): return Counter(re.findall(r"（\*[^）]*）|\(\*[^)]*\)", t))
def numbers(t): return Counter(re.findall(r"\d[\d,.]*\d|\d", re.sub(r"\[\d+\]", "", t)))
def quotes(t): return Counter(norm(q) for q in re.findall(r"“([^”]*)”", re.sub(r"\[\d+\]", "", t)))
def hanzi(t): return len(re.findall(r"[一-鿿]", t))
def emphasis(t): return Counter(re.findall(r"\*([^*\n]+)\*", t))


def ledger(root, fname):
    path = Path(root) / "audit" / "citations.json"
    if not path.exists():
        return [], set()
    records = json.loads(path.read_text(encoding="utf-8")).get("records", [])
    keep = [r for r in records if r.get("file") == fname and r.get("status") in PROTECTED_STATUSES and r.get("replacement")]
    free = {norm(r.get("excerpt") or r.get("replacement") or "") for r in records
            if r.get("file") == fname and r.get("status") in EDITABLE_STATUSES}
    return keep, {f for f in free if f}


def is_free(q, free):
    return any(q in f or f in q for f in free)


def sentences(text):
    if text.lstrip().startswith(">"):
        return []
    t = re.sub(r"（\*[^）]*）|\[\d+\]|\*", "", text)
    t = re.sub(r"“[^”]*[。！？…]”", "“”。", t)
    t = re.sub(r"“[^”]*”", "“”", t)
    t = re.sub(r"（[^）]*）", "", t)
    return [s.strip() for s in re.split(r"[。！？]", t) if s.strip()]


def long_sentences(blocks, limit):
    return [(k, hanzi(s), s) for k, text in blocks.items() for s in sentences(text) if hanzi(s) >= limit]


def check_block(key, old, new, keep, free):
    errors, warnings = [], []
    if refs(old) != refs(new):
        errors.append(f"注号变了 {refs(old)} → {refs(new)}")
    if inline_refs(old) != inline_refs(new):
        errors.append("作者出处变了")
    if numbers(old) != numbers(new):
        lost, added = numbers(old) - numbers(new), numbers(new) - numbers(old)
        errors.append(f"数字变了：{list(lost.elements())} → {list(added.elements())}")
    if old.count(PENDING) != new.count(PENDING):
        errors.append("待核标记数量变了")
    qo, qn = quotes(old), quotes(new)
    lost = [q for q in (qo - qn).elements() if not is_free(q, free)]
    if lost:
        errors.append(f"引号内文字变了或丢了：{lost}")
    if (qn - qo) and not [q for q in (qo - qn).elements() if is_free(q, free)]:
        errors.append(f"多出了引号内容：{list((qn - qo).elements())}")
    was_quote = old.lstrip().startswith(">")
    if was_quote != new.lstrip().startswith(">"):
        errors.append("引文块标记 > 变了")
    if was_quote and norm(old) != norm(new) and not any(f[:12] in norm(old) for f in free):
        errors.append("引文块内容不能改")
    if old.startswith("#") != new.startswith("#"):
        errors.append("标题标记变了")
    for r in keep:
        if r.get("anchor") == "b" + key and norm(r["replacement"]) not in norm(new):
            errors.append(f"已落实的引文被改动：{r['replacement'][:30]}")
    if "<!--" in new:
        errors.append("段落里混进了锚点或注释标记")
    if emphasis(old) != emphasis(new):
        warnings.append("着重号（*）内容有变化")
    ho, hn = hanzi(old), hanzi(new)
    if ho >= 40 and hn < ho * 0.8:
        warnings.append(f"明显变短 {ho}→{hn} 字，确认没有丢信息")
    if ho >= 40 and hn > ho * 1.3:
        warnings.append(f"明显变长 {ho}→{hn} 字，确认没有添内容")
    return errors, warnings


def cmd_pairs(a):
    _, en, _ = split(chapter_file(a.project, "source/chapters", a.chapter).read_text(encoding="utf-8"))
    _, zh, _ = split(chapter_file(a.project, "zh", a.chapter).read_text(encoding="utf-8"))
    for key, (_, text) in zh.items():
        n = int(key)
        if (a.start and n < a.start) or (a.end and n > a.end):
            continue
        print(f"=== b{key}\nEN: {en.get(key, ('', ''))[1]}\nZH: {text}\n")
    return 0


def cmd_apply(a):
    path = chapter_file(a.project, "zh", a.chapter)
    lock = path.with_suffix(".lock")
    for _ in range(600):
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL))
            break
        except FileExistsError:
            time.sleep(0.2)
    else:
        sys.exit(f"等不到文件锁 {lock}，确认没有别的 apply 在跑后删掉它")
    try:
        head, blocks, notes = split(path.read_text(encoding="utf-8").replace("\r\n", "\n"))
        _, base, _ = split(baseline_text(a.project, path.name))
        keep, free = ledger(a.project, path.name)
        patch = Path(a.patch).read_text(encoding="utf-8").replace("\r\n", "\n")
        marks = list(PATCH_ANCHOR.finditer(patch))
        written, rejected, warned = 0, [], []
        for k, m in enumerate(marks):
            key = m.group(1)
            end = marks[k + 1].start() if k + 1 < len(marks) else len(patch)
            new = patch[m.end():end].strip()
            if key not in blocks or key not in base:
                rejected.append((key, ["没有这个段号"]))
                continue
            errors, warnings = check_block(key, base[key][1], new, keep, free)
            if errors:
                rejected.append((key, errors))
                continue
            if warnings:
                warned.append((key, warnings))
            blocks[key] = (blocks[key][0], new)
            written += 1
        text = head + "".join(anchor + body + "\n\n" for anchor, body in blocks.values()) + notes
        path.write_text(text.rstrip("\n") + "\n", encoding="utf-8", newline="\n")
    finally:
        lock.unlink(missing_ok=True)
    print(f"{path.name}：写入 {written} 段，退回 {len(rejected)} 段，提示 {len(warned)} 段")
    for key, e in rejected:
        print(f"  退回 b{key}：" + "；".join(e))
    for key, w in warned:
        print(f"  提示 b{key}：" + "；".join(w))
    longs = long_sentences({k: v[1] for k, v in blocks.items()}, a.max_len)
    print(f"  全章 ≥{a.max_len} 字的长句 {len(longs)} 句（不计引文），每句都要单独看一遍")
    return 1 if rejected else 0


def cmd_lint(a):
    path = chapter_file(a.project, "zh", a.chapter)
    _, cur, _ = split(path.read_text(encoding="utf-8"))
    _, base, _ = split(baseline_text(a.project, path.name))
    plain = lambda d: "\n".join(re.sub(r"“[^”]*”", "", v[1]) for v in d.values() if not v[1].startswith(">"))
    before, after = plain(base), plain(cur)
    changed = sum(1 for k in cur if k in base and cur[k][1] != base[k][1])
    print(f"{a.chapter}：改动 {changed}/{len(cur)} 段；汉字 {hanzi(before)}→{hanzi(after)}（不计引文）")
    sb = {k: len(re.findall(v, before)) for k, v in SIGNALS.items()}
    sa = {k: len(re.findall(v, after)) for k, v in SIGNALS.items()}
    print("翻译腔信号（基线→现在）：" + "，".join(f"{k} {sb[k]}→{sa[k]}" for k in SIGNALS if sb[k] or sa[k]))
    old_long = long_sentences({k: v[1] for k, v in base.items()}, a.max_len)
    new_long = long_sentences({k: v[1] for k, v in cur.items()}, a.max_len)
    print(f"≥{a.max_len} 字的长句：{len(old_long)}→{len(new_long)}（标出来单独看，不是非拆不可）")
    for key, n, s in new_long:
        print(f"  b{key} {n}字：{s[:70]}……")
    return 0


def main():
    ap = argparse.ArgumentParser(description="逐段润色工具")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pairs", help="打印英中对照")
    p.add_argument("project"); p.add_argument("chapter")
    p.add_argument("start", nargs="?", type=int); p.add_argument("end", nargs="?", type=int)
    p = sub.add_parser("apply", help="校验并写回改稿")
    p.add_argument("project"); p.add_argument("chapter"); p.add_argument("patch")
    p.add_argument("--max-len", type=int, default=50)
    p = sub.add_parser("lint", help="长句和翻译腔信号")
    p.add_argument("project"); p.add_argument("chapter")
    p.add_argument("--max-len", type=int, default=50)
    a = ap.parse_args()
    return {"pairs": cmd_pairs, "apply": cmd_apply, "lint": cmd_lint}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
