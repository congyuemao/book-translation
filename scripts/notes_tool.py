#!/usr/bin/env python3
"""章末注释的插入、删除和检查。注号顺延、交叉引用都由脚本处理，不要手工改编号。

    python notes_tool.py add    <项目目录> <章前缀> "<锚定文字>" "<注释正文>"
    python notes_tool.py remove <项目目录> <章前缀> <注号>
    python notes_tool.py lint   <项目目录> [章前缀 ...]

add：注号挂在锚定文字后面。锚定文字必须在该章正文里只出现一次，且后面不能紧跟已有注号。
     给阅读版看的读者注释，在注释正文末尾加 <!--读者-->（或 <!--读者：阅读版只显示的说法-->）。
remove：删掉正文里的注号和对应注释。
两者都会：顺延（或减一）后面的注号和注释编号；同步改注释里的“注N”“同注N”“见注N”；
插注后紧跟的“同上”“中译文同上”改成“同注N”，免得指到新注上；删注时，引用了被删注释的
交叉引用会列出来要你手工处理。“编者注373”“译者注”“原注”里的数字是书里的编号，不会动。

lint：检查注号是否从 1 连续、注号和注释条数是否一致；注释里有没有写段号（读者看不到）；
“同上”紧跟在读者注释后面（多半指错）；正文里注号放在句号后面（应放在标点前）。
"""
import argparse
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HEAD = "\n## 注释与引用\n"
XREF = re.compile(r"(?<!编者)(?<!译者)(?<!原)(注)(\d+)")
SAME = re.compile(r"^(中译文(?:出处)?)?同上")
NOTE_LINE = re.compile(r"^(\d+)\. (.*)$")


def chapter(root, prefix):
    found = sorted((Path(root) / "zh").glob(prefix + "_*.md"))
    if len(found) != 1:
        sys.exit(f"zh 里找不到唯一的 {prefix}_*.md")
    return found[0]


def load(path):
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    if HEAD not in text:
        sys.exit(f"{path.name} 没有“## 注释与引用”，先手工建好注释区")
    return text.split(HEAD, 1)


def save(path, body, notes):
    path.write_text(body + HEAD + notes, encoding="utf-8", newline="\n")


def renumber(notes, fn, insert_at=None, insert_text=None, drop=None):
    """fn: 旧编号 → 新编号。insert_at/insert_text：在新编号 insert_at 处插入一条；drop：删掉这条旧编号。"""
    out, done = [], False
    for line in notes.split("\n"):
        m = NOTE_LINE.match(line)
        if not m:
            out.append(line)
            continue
        n, rest = int(m.group(1)), m.group(2)
        if drop is not None and n == drop:
            continue
        rest = XREF.sub(lambda mm: f"{mm.group(1)}{fn(int(mm.group(2)))}", rest)
        new_n = fn(n)
        if insert_at is not None and new_n == insert_at + 1 and not done:
            out.append(f"{insert_at}. {insert_text}")
            done = True
            if insert_at > 1:
                rest = re.sub(r"^同上书", f"同注{insert_at - 1}所引书", rest)
                rest = SAME.sub(lambda mm: f"{mm.group(1) or ''}同注{insert_at - 1}", rest)
        out.append(f"{new_n}. {rest}")
    if insert_at is not None and not done:
        while out and out[-1] == "":
            out.pop()
        out += [f"{insert_at}. {insert_text}", ""]
    return "\n".join(out)


def cmd_add(a):
    path = chapter(a.project, a.chapter)
    body, notes = load(path)
    if body.count(a.anchor) != 1:
        sys.exit(f"锚定文字在正文里出现 {body.count(a.anchor)} 次，必须正好 1 次：{a.anchor[:40]}")
    i = body.index(a.anchor) + len(a.anchor)
    if re.match(r"⁠?\[\d+\]", body[i:]):
        sys.exit("锚定文字后面已经有注号，换一个位置")
    k = len(re.findall(r"\[(\d+)\]", body[:i])) + 1
    shift = lambda n: n + 1 if n >= k else n
    body = body[:i] + f"[{k}]" + re.sub(r"\[(\d+)\]", lambda m: f"[{shift(int(m.group(1)))}]", body[i:])
    notes = renumber(notes, shift, insert_at=k, insert_text=a.text)
    save(path, body, notes)
    print(f"{path.name}：插入注 {k}")
    return 0


def cmd_remove(a):
    path = chapter(a.project, a.chapter)
    body, notes = load(path)
    k = a.number
    if len(re.findall(rf"\[{k}\]", body)) != 1:
        sys.exit(f"正文里注号 [{k}] 不是正好出现一次")
    old = {int(m.group(1)): m.group(2) for m in map(NOTE_LINE.match, notes.split("\n")) if m}
    if k not in old:
        sys.exit(f"没有第 {k} 条注释")
    pointing = [n for n, t in old.items() if n != k and re.search(rf"(?<!编者)(?<!译者)(?<!原)注{k}(?!\d)", t)]
    follower = old.get(k + 1, "")
    body = body.replace(f"[{k}]", "", 1)
    shift = lambda n: n - 1 if n > k else n
    body = re.sub(r"\[(\d+)\]", lambda m: f"[{shift(int(m.group(1)))}]", body)
    notes = renumber(notes, shift, drop=k)
    save(path, body, notes)
    print(f"{path.name}：删除注 {k}，后面的注号已减一")
    if pointing:
        print(f"  注意：这些注释引用了被删的注 {k}，要手工改：{[shift(n) for n in pointing]}")
    if SAME.match(follower):
        print(f"  注意：原注 {k + 1}（现注 {k}）以“同上”开头，现在指向了别的注释，要手工写明出处")
    return 0


def cmd_lint(a):
    files = [chapter(a.project, c) for c in a.chapters] if a.chapters else sorted((Path(a.project) / "zh").glob("*.md"))
    problems = 0
    for path in files:
        text = path.read_text(encoding="utf-8")
        if HEAD not in text:
            continue
        body, notes = text.split(HEAD, 1)
        refs = [int(x) for x in re.findall(r"\[(\d+)\]", body)]
        nums = [int(m.group(1)) for m in map(NOTE_LINE.match, notes.split("\n")) if m]
        items = {int(m.group(1)): m.group(2) for m in map(NOTE_LINE.match, notes.split("\n")) if m}
        out = []
        if refs != list(range(1, len(refs) + 1)):
            out.append("正文注号不是从 1 连续递增")
        if nums != list(range(1, len(nums) + 1)):
            out.append("注释编号不连续")
        if len(refs) != len(nums):
            out.append(f"注号 {len(refs)} 个，注释 {len(nums)} 条")
        for n, t in items.items():
            visible = re.sub(r"<!--(?!\s*读者[:：]).*?-->", "", t)
            # “《思想录》第206段”这种是书里的编号，不算；没有书名在前的“第N段”多半是我们的段号
            if re.search(r"(?<!》)第\d+段|(?<![A-Za-z])b\d{3}(?!\d)", visible):
                out.append(f"注 {n} 写了段号，读者在书里看不到")
            if SAME.match(t) and n - 1 in items and "<!--读者" in items[n - 1] and not SAME.match(items[n - 1]) \
                    and not re.match(r"(前一处)?中译文", items[n - 1]):
                out.append(f"注 {n} 以“同上”开头，前一条却是读者注释，多半指错了")
        for blk in re.split(r"<!--b\d+[^>]*-->", body):
            if blk.lstrip().startswith(">"):
                continue
            for m in re.finditer(r"[。！？]⁠?\[\d+\]", blk):
                out.append(f"注号放在句末标点后面：……{blk[max(0, m.start() - 12):m.end()]}")
        for line in out:
            print(f"{path.name}：{line}")
        problems += len(out)
    print(f"共 {problems} 处")
    return 1 if problems else 0


def main():
    ap = argparse.ArgumentParser(description="章末注释的插入、删除和检查")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add"); p.add_argument("project"); p.add_argument("chapter"); p.add_argument("anchor"); p.add_argument("text")
    p = sub.add_parser("remove"); p.add_argument("project"); p.add_argument("chapter"); p.add_argument("number", type=int)
    p = sub.add_parser("lint"); p.add_argument("project"); p.add_argument("chapters", nargs="*")
    a = ap.parse_args()
    return {"add": cmd_add, "remove": cmd_remove, "lint": cmd_lint}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
