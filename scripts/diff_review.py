#!/usr/bin/env python3
"""改动对照页：把译文的改动逐段做成一张 HTML，删去的标红、新写的标绿，给用户逐条把关。

    python diff_review.py <项目目录> [--rev HEAD~3 | --base 基线.zip或目录] [--chapters 07 12] [--en] [--out build/改动对照.html]

对比的两边：
- 默认：git 里上一次提交（HEAD）对比工作区，即“还没提交的改动”。
- --rev：git 里的某个版本对比工作区，比如 --rev HEAD~5、某个提交号或标签。
- --base：一个润色基线 zip（polish/baseline-*.zip）或一个装着旧版 zh/*.md 的目录；写 --base baseline 就是当前润色基线。
按段落锚点对齐，只列有改动的段和注释。加 --en 会附上那段的英文原文，方便判断改得对不对。
页面同时标出改动落在作者正文、引文（引号或引文块里）还是注释，用户最关心“改的是原文还是注释”。
"""
import argparse
import difflib
import html
import re
import subprocess
import sys
import zipfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BLOCK = re.compile(r"<!--b(\d+)(?:\s+p\.[^\s>]+)?-->\n(.*?)(?=\n\n<!--b|\n\n##\s+注释与引用|\Z)", re.S)
NOTE = re.compile(r"^(\d+)\. (.*)$", re.M)


def parse(text):
    body, _, notes = text.partition("\n## 注释与引用\n")
    return {k: v.strip() for k, v in BLOCK.findall(body + "\n\n")}, dict(NOTE.findall(notes))


def old_text(root, name, a):
    if a.base:
        base = Path(a.base)
        if a.base == "baseline":  # 当前润色基线
            base = root / "polish" / (root / "polish" / "baseline.txt").read_text(encoding="utf-8").strip()
        if base.suffix == ".zip":
            with zipfile.ZipFile(base) as z:
                return z.read(name).decode("utf-8") if name in z.namelist() else ""
        p = base / name
        return p.read_text(encoding="utf-8") if p.exists() else ""
    r = subprocess.run(["git", "show", f"{a.rev}:zh/{name}"], cwd=root, capture_output=True)
    return r.stdout.decode("utf-8") if r.returncode == 0 else ""


def diff(a, b):
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(html.escape(a[i1:i2]))
        if op in ("delete", "replace"):
            out.append(f"<del>{html.escape(a[i1:i2])}</del>")
        if op in ("insert", "replace"):
            out.append(f"<ins>{html.escape(b[j1:j2])}</ins>")
    return "".join(out)


def where(old, new):
    """改动落在哪里：引文还是作者正文。"""
    if old.lstrip().startswith(">"):
        return "引文块"
    quotes = lambda t: re.findall(r"“[^”]*”", t)
    rest = lambda t: re.sub(r"“[^”]*”", "“”", t)
    kinds = []
    if quotes(old) != quotes(new):
        kinds.append("引号内")
    if rest(old) != rest(new):
        kinds.append("正文")
    return "、".join(kinds) or "格式"


def main():
    ap = argparse.ArgumentParser(description="译文改动对照页")
    ap.add_argument("project")
    ap.add_argument("--rev", default="HEAD")
    ap.add_argument("--base")
    ap.add_argument("--chapters", nargs="*")
    ap.add_argument("--en", action="store_true", help="附英文原文")
    ap.add_argument("--out", default="build/改动对照.html")
    a = ap.parse_args()
    root = Path(a.project)
    files = sorted((root / "zh").glob("*.md"))
    if a.chapters:
        files = [f for f in files if f.name.split("_")[0] in a.chapters]
    sections, total = [], {"段落": 0, "注释": 0}
    for f in files:
        before = old_text(root, f.name, a).replace("\r\n", "\n")
        after = f.read_text(encoding="utf-8").replace("\r\n", "\n")
        if before == after:
            continue
        ob, on = parse(before)
        nb, nn = parse(after)
        src = {}
        if a.en:
            sp = sorted((root / "source" / "chapters").glob(f.name.split("_")[0] + "_*.md"))
            if sp:
                src, _ = parse(sp[0].read_text(encoding="utf-8"))
        items = []
        for k in nb:
            o, n = ob.get(k, ""), nb[k]
            if o == n:
                continue
            total["段落"] += 1
            clean = lambda t: re.sub(r"⁠", "", t)
            en = f'<p class="en">{html.escape(src.get(k, ""))}</p>' if a.en and src.get(k) else ""
            items.append(f'<article><h3>b{k}　<span class="tag">{where(o, n) if o else "新段"}</span></h3>'
                         f'<div class="diff">{diff(clean(o), clean(n))}</div>{en}</article>')
        for k in sorted(set(on) | set(nn), key=int):
            o, n = on.get(k, ""), nn.get(k, "")
            if o == n:
                continue
            total["注释"] += 1
            items.append(f'<article><h3>注 {k}　<span class="tag">注释</span></h3><div class="diff">{diff(o, n)}</div></article>')
        if items:
            sections.append(f"<h2>{html.escape(f.name)}</h2>" + "".join(items))
    label = f"基线 {a.base}" if a.base else f"git {a.rev}"
    page = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>译文改动对照</title><style>
:root{{--bg:#faf8f4;--fg:#22272b;--muted:#68737a;--card:#fff;--line:#e3ddd2;--del-bg:#fbe1dc;--del-fg:#9b2c1d;--ins-bg:#dcf1df;--ins-fg:#1d6b33;--accent:#b44230}}
@media (prefers-color-scheme:dark){{:root{{--bg:#17191b;--fg:#e8e4dc;--muted:#9aa3a8;--card:#202326;--line:#33383c;--del-bg:#4a2420;--del-fg:#f3b3a7;--ins-bg:#1f3b27;--ins-fg:#a8e0b5;--accent:#e07a63}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.8 "Noto Serif SC","Songti SC",serif}}
main{{max-width:860px;margin:0 auto;padding:28px 16px 80px}}
h1{{font:700 24px/1.3 "Noto Sans SC",sans-serif;margin:0 0 8px}}h2{{font:700 18px/1.4 "Noto Sans SC",sans-serif;margin:36px 0 12px;padding-bottom:6px;border-bottom:2px solid var(--accent)}}
h3{{font:600 15px/1.4 "Noto Sans SC",sans-serif;margin:0 0 6px}}.tag{{font-weight:400;color:var(--muted)}}
article{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 16px;margin:0 0 10px}}
.en{{color:var(--muted);font-size:14px;border-top:1px dashed var(--line);margin:8px 0 0;padding-top:6px}}
del{{background:var(--del-bg);color:var(--del-fg);text-decoration:line-through}}ins{{background:var(--ins-bg);color:var(--ins-fg);text-decoration:none}}
.lead{{color:var(--muted)}}</style></head><body><main>
<h1>译文改动对照</h1><p class="lead">对比：{html.escape(label)} → 当前工作区。<del>删去的</del>　<ins>新写的</ins>。共改动 {total["段落"]} 段、{total["注释"]} 条注释。</p>
{"".join(sections) or "<p>没有改动。</p>"}</main></body></html>'''
    out = root / a.out if not Path(a.out).is_absolute() else Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"改动 {total['段落']} 段、{total['注释']} 条注释 → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
