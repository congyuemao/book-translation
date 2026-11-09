#!/usr/bin/env python3
"""导出给人读的全书中文 Markdown，并做一遍交付前的文字扫描。

    python md_export.py <项目目录> <输出.md> [--reading]

- 去掉段落锚点和 <!--file:…--> 之类的标记，章与章之间用分隔线隔开，方便通读、批注、发给别人。
  这只是副本，改稿仍然改 zh/*.md（或合并稿再 unmerge）。
- --reading：按阅读版处理，去掉注释区、注号和【原文待核】，读者注释（<!--读者-->）也一并去掉。
- 扫描并列出：中文里夹半角标点；引号、书名号、括号不成对；残留的“校注：”“译者注：”“此处略”“TODO”；
  术语表 forbidden_zh 一栏禁用的译法；还剩多少处【原文待核】。
"""
import argparse
import csv
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def main():
    ap = argparse.ArgumentParser(description="导出全书中文 MD 并扫描")
    ap.add_argument("project"); ap.add_argument("out")
    ap.add_argument("--reading", action="store_true")
    a = ap.parse_args()
    root = Path(a.project)
    files = sorted((root / "zh").glob("*.md"))
    forbidden = []
    gl = root / "glossary" / "glossary.csv"
    if gl.exists():
        with open(gl, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                forbidden += [(w, row.get("zh", "")) for w in (row.get("forbidden_zh") or "").split("|") if w]
    issues, parts, pending = [], [], 0
    half = re.compile(r"[一-鿿][,;:!?]|[,;:!?][一-鿿]|[一-鿿]\([一-鿿]")
    for f in files:
        text = f.read_text(encoding="utf-8")
        body = text.split("\n## 注释与引用")[0]
        pending += text.count("【原文待核】")
        for m in half.finditer(re.sub(r"<!--.*?-->", "", body)):
            issues.append(f"{f.name} 半角标点：{body[max(0, m.start() - 10):m.end() + 10].strip()}")
        for blk in re.split(r"<!--b\d+[^>]*-->", body):
            s = re.sub(r"<!--.*?-->", "", blk)
            for l, r in (("“", "”"), ("《", "》"), ("（", "）")):
                if s.count(l) != s.count(r) and not s.lstrip().startswith(">"):
                    issues.append(f"{f.name} {l}{r}不成对：{s.strip()[:40]}")
        for bad in ("校注：", "译者注：", "此处略", "TODO"):
            if bad in text:
                issues.append(f"{f.name} 残留：{bad}")
        for w, right in forbidden:
            if w in body:
                issues.append(f"{f.name} 禁用译法“{w}”（应作“{right}”）")
        out = text
        if a.reading:
            out = out.split("\n## 注释与引用")[0]
            out = re.sub(r"⁠?\[\d+\]|【原文待核】", "", out)
        out = re.sub(r"^<!--(?:b\d+[^>]*|file:[^>]*|p\.[^>]*)-->[ \t]*\n?", "", out, flags=re.M)
        out = re.sub(r"<!--\s*读者[^>]*-->", "", out)
        parts.append(out.strip())
    Path(a.out).write_text("\n\n---\n\n".join(parts) + "\n", encoding="utf-8")
    han = sum(len(re.findall(r"[一-鿿]", p)) for p in parts)
    print(f"写出 {a.out}：{len(files)} 个文件，{han} 个汉字；正文还有【原文待核】{pending} 处")
    for line in issues[:80]:
        print("  " + line)
    print(f"扫描发现 {len(issues)} 处问题" + ("（只列前 80 处）" if len(issues) > 80 else ""))
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
