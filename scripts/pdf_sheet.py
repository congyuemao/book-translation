#!/usr/bin/env python3
"""目视检查用：把 PDF 的若干页拼成一张缩略图，并检查页面有没有被整本缩小。

    python pdf_sheet.py <PDF> <输出.png> [页码 ...] [--chapters 校验文件.json] [--scale 0.42] [--cols 8]

不给页码时，默认取前 3 页和最后 2 页。加 --chapters build/validation.json 时，再加上每章首页和每章末页
（末页就是下一章首页的前一页，最容易出孤页）。页码从 1 起，负数从末尾数（-1 是最后一页）。

另外会检查第 1 页和最后一页：封面、封底应该铺满整页，右边缘和下边缘如果是白色，多半是某个元素超出版心，
Chrome 把整本 PDF 缩小了（这本书遇到过：索引行尾的全角空格悬出版心，整本缩小 1.6%）。
"""
import argparse
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def main():
    ap = argparse.ArgumentParser(description="PDF 缩略图拼页和整本缩放检查")
    ap.add_argument("pdf"); ap.add_argument("out")
    ap.add_argument("pages", nargs="*", type=int)
    ap.add_argument("--chapters", help="build_book.mjs 生成的 validation*.json，取其中的 pageMap")
    ap.add_argument("--scale", type=float, default=0.42)
    ap.add_argument("--cols", type=int, default=8)
    a = ap.parse_args()
    try:
        import pypdfium2 as pdfium
        from PIL import Image
    except ImportError:
        sys.exit("需要 pypdfium2 和 Pillow：python -m pip install pypdfium2 pillow")

    doc = pdfium.PdfDocument(a.pdf)
    total = len(doc)
    pages = list(a.pages) or [1, 2, 3, -2, -1]
    if a.chapters:
        starts = sorted(set(json.loads(Path(a.chapters).read_text(encoding="utf-8")).get("pageMap", {}).values()))
        pages += starts + [s - 1 for s in starts if s > 1]
    resolved = []
    for p in pages:
        n = p if p > 0 else total + p + 1
        if 1 <= n <= total and n not in resolved:
            resolved.append(n)
    resolved.sort()

    shrunk = []
    for n in sorted({1, total}):
        img = doc[n - 1].render(scale=1).to_pil().convert("RGB")
        w, h = img.size
        edge = [img.getpixel((w - 2, h // 2)), img.getpixel((w // 2, h - 2))]
        if all(min(px) > 245 for px in edge):
            shrunk.append(n)
    if shrunk:
        print(f"警告：第 {shrunk} 页右边缘和下边缘都是白色。如果这是满版的封面或封底，说明整本 PDF 被缩小了，"
              "去找超出版心的元素（长串外文、行尾悬挂的全角空格、过宽的表格和图片）")
    else:
        print("第 1 页和最后一页铺满了，没有发现整本缩放")

    images = [doc[n - 1].render(scale=a.scale).to_pil() for n in resolved]
    w, h = images[0].size
    rows = (len(images) + a.cols - 1) // a.cols
    sheet = Image.new("RGB", (a.cols * (w + 4), rows * (h + 4)), (110, 110, 110))
    for k, im in enumerate(images):
        sheet.paste(im, ((k % a.cols) * (w + 4), (k // a.cols) * (h + 4)))
    sheet.save(a.out)
    print(f"共 {total} 页，拼了 {len(resolved)} 页：{resolved} → {a.out}")
    return 1 if shrunk else 0


if __name__ == "__main__":
    sys.exit(main())
