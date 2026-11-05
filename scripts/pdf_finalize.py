"""读取排版后 PDF 的目标页码；写书签和元数据；回读校验。供 build_book.mjs 调用。"""
import json
import re
import sys
import unicodedata
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def normalize(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value or ""))


def present(sample, haystack):
    """Chrome 可能把常用字写成部首码位，比对时让部首码位匹配任何字，这个问题单独报告。"""
    pattern = "".join(f"(?:{re.escape(ch)}|[\u2e80-\u2fdf])" for ch in normalize(sample))
    return re.search(pattern, haystack) is not None


def page_map(pdf_path, sections_path):
    reader = PdfReader(pdf_path)
    sections = json.loads(Path(sections_path).read_text(encoding="utf-8"))
    destinations = reader.named_destinations
    outlines = {}

    def walk(items):
        for item in items:
            if isinstance(item, list):
                walk(item)
            else:
                outlines.setdefault(normalize(item.title), []).append(reader.get_destination_page_number(item) + 1)

    walk(reader.outline)
    result = {}
    for section in sections:
        dest = destinations.get(section["id"]) or destinations.get("/" + section["id"])
        if dest is not None:
            page = reader.get_destination_page_number(dest) + 1
        else:
            matches = outlines.get(normalize(section["title"]), [])
            if len(matches) != 1:
                raise ValueError(f"找不到唯一的章节目标：{section['id']} {matches}")
            page = matches[0]
        text = normalize(reader.pages[page - 1].extract_text())
        if not present(section["shortTitle"], text):
            raise ValueError(f"目标页上没有章节标题：{section['id']}（第 {page} 页）")
        result[section["id"]] = page
    pages = list(result.values())
    if pages != sorted(set(pages)):
        raise ValueError("章节页码没有严格递增")
    print(json.dumps(result, ensure_ascii=False))


def fonts_report(reader):
    resources, unembedded = 0, set()
    seen = set()
    for page in reader.pages:
        res = page.get("/Resources")
        fonts = res.get_object().get("/Font") if res else None
        if not fonts:
            continue
        for ref in fonts.get_object().values():
            key = getattr(ref, "idnum", id(ref))
            if key in seen:
                continue
            seen.add(key)
            resources += 1
            font = ref.get_object()
            base = str(font.get("/BaseFont", "?"))
            if font.get("/Subtype") == "/Type3":
                continue
            descendants = font.get("/DescendantFonts")
            target = descendants.get_object()[0].get_object() if descendants else font
            descriptor = target.get("/FontDescriptor")
            descriptor = descriptor.get_object() if descriptor else {}
            if not any(k in descriptor for k in ("/FontFile", "/FontFile2", "/FontFile3")):
                unembedded.add(base)
    return resources, sorted(unembedded)


def finalize(source, target, config_path):
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    reader = PdfReader(source)
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    writer.root_object.pop(NameObject("/Outlines"), None)
    for entry in config["outline"]:
        writer.add_outline_item(entry["title"], entry["page"] - 1)
    writer.add_metadata(config["metadata"])
    writer.root_object[NameObject("/PageMode")] = NameObject("/UseOutlines")
    with open(target, "wb") as stream:
        writer.write(stream)

    final = PdfReader(target)
    if len(final.pages) != len(reader.pages) or len(final.outline) != len(config["outline"]):
        raise ValueError("页数或书签数量不一致")
    links_before = sum(len(p.get("/Annots", []) or []) for p in reader.pages)
    links_after = sum(len(p.get("/Annots", []) or []) for p in final.pages)
    if links_before != links_after:
        raise ValueError("收尾时丢失了链接")

    texts = [p.extract_text() or "" for p in final.pages]
    blank, sparse = [], []
    for number, text in enumerate(texts, 1):
        size = len(normalize(text))
        if number == 1:  # 封面可能全是图
            continue
        has_image = bool(final.pages[number - 1].images) if size == 0 else False
        if size == 0 and not has_image:
            blank.append(number)
        elif 0 < size < 80:
            sparse.append([number, size])
    resources, unembedded = fonts_report(final)
    joined = normalize("".join(texts))
    radicals = len(re.findall(r"[\u2e80-\u2fdf]", "".join(texts)))
    missing = [t for t in config.get("expectBlocks", []) if not present(t, joined)]
    print(json.dumps({
        "pages": len(final.pages), "bookmarks": len(final.outline), "links": links_after,
        "blankPages": blank, "sparsePages": sparse, "replacementCharacters": joined.count("�"),
        "pendingMarkersInPdf": joined.count("【原文待核】"), "fontResources": resources,
        "unembeddedFonts": unembedded, "radicalCharsInPdfText": radicals, "sampleBlocksMissingFromPdf": missing[:20],
        "sampleBlocksChecked": len(config.get("expectBlocks", [])),
        "bytes": Path(target).stat().st_size,
    }, ensure_ascii=False))


if __name__ == "__main__":
    command = sys.argv[1]
    if command == "page-map":
        page_map(*sys.argv[2:])
    elif command == "finalize":
        finalize(*sys.argv[2:])
    else:
        raise SystemExit("需要 page-map 或 finalize")
