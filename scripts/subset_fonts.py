"""按全书用字生成字体子集，供 build_book.mjs 嵌入 HTML 和 PDF。不改动系统字体。

用途有二：HTML 离线也能显示正确字体；避免 Chrome 把"一""马"等字写成部首码位
（U+2F00、U+2EE2 等），否则 PDF 里的文字复制、搜索会对不上。子集里没有部首码位，问题就消失了。

用法：python subset_fonts.py <用字文本文件> <源字体> <输出文件>
"""
import sys
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont


def main(text_path, source, target):
    text = Path(text_path).read_text(encoding="utf-8")
    text += "".join(chr(i) for i in range(32, 127)) + "—…×‘’“”《》（）【】，。、；：？！·✦"
    font = TTFont(source)
    options = subset.Options()
    options.name_IDs = ["*"]
    options.name_legacy = True
    options.name_languages = ["*"]
    options.notdef_outline = True
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(text=text)
    subsetter.subset(font)
    try:
        import brotli  # noqa: F401
        font.flavor = "woff2"
    except ImportError:
        font.flavor = None
    font.save(target)
    print(font.flavor or "ttf")


if __name__ == "__main__":
    main(*sys.argv[1:4])
