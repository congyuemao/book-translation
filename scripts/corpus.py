#!/usr/bin/env python3
"""本地引文语料：把在线文库抓到本地，再按关键词检索中译原文。

适合作者大量引用、又有大规模中文在线文库的情况（比如马恩著作之于中文马克思主义文库）。
抓下来的每页存成一个 txt：第一行 URL，第二行标题，后面是正文。

    python corpus.py crawl <语料目录> --seed URL [--seed URL ...] --allow URL前缀 [--allow ...]
                           [--workers 3] [--delay 0.3] [--max 4000] [--restart]
        例：--seed https://www.marxists.org/chinese/marx/index.htm --allow https://www.marxists.org/chinese/marx/
    python corpus.py pdf   <语料目录> <文件.pdf> --title "《马克思恩格斯全集》第46卷（上）" [--url 来源URL]
    python corpus.py grep  <语料目录> 关键词1 [关键词2 ...] [--t 标题片段] [--url 路径片段] [--w 300] [--c 160] [--max 12]
    python corpus.py show  <语料目录> <文件名> <起始偏移> <长度>

crawl：从种子页出发，只跟进同一站点、路径以 --allow 开头的 .htm/.html 链接；PDF 链接记进 pdfs.json，不下载。
        网页编码按页面声明解码，GB2312、GBK 一律按 GB18030 读。
        默认 3 个线程同时抓、每个线程间隔 0.3 秒，别给对方服务器添负担，线程别超过 6。
        可以随时中断（Ctrl+C、超时、--max 到了）：每抓一页就记进 index.jsonl，队列存在 crawl_state.json，
        再运行同一条命令就接着抓，已存过的页不重复保存。抓完会删掉 crawl_state.json。
pdf：把 PDF 文字层转成一页一段，带“[PDF第N页]”标记，去掉中文着重点和折行。
grep：所有关键词必须出现在同一窗口里（默认前后 300 字）。关键词选 2—6 字、译法稳定的实词，多试几组。
      搜到的文字才算数：要逐字复制，用 show 取原文，不凭记忆补。
"""
import argparse
import html
import json
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from queue import Queue

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

UA = "Mozilla/5.0 (book-translation corpus builder)"


def fetch(url):
    req = urllib.request.Request(urllib.parse.quote(url, safe=":/?=&%#"), headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=40).read()


def decode(raw):
    m = re.search(rb"charset=[\"']?([\w-]+)", raw[:3000])
    enc = m.group(1).decode().lower() if m else "utf-8"
    if enc in ("gb2312", "gbk", "gb18030"):
        enc = "gb18030"
    if raw.startswith(b"\xef\xbb\xbf"):
        enc = "utf-8-sig"
    for e in (enc, "utf-8", "gb18030"):
        try:
            return raw.decode(e)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def page_text(markup):
    title = (re.search(r"<title>(.*?)</title>", markup, re.S | re.I) or [None, ""])[1]
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", markup, flags=re.S | re.I)
    t = re.sub(r"<br\s*/?>|</p>|</div>|</h\d>|</tr>|</li>", "\n", t, flags=re.I)
    t = html.unescape(re.sub(r"<[^>]+>", "", t))
    t = re.sub(r"[ \t　\xa0]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    return re.sub(r"\s+", " ", html.unescape(title)).strip(), t


def allowed(link, prefixes):
    """--allow 写完整的 URL 前缀最稳妥。Windows 的 Git Bash 会把以 / 开头的参数改写成本地路径，
    所以只写路径时，脚本也接受不带开头斜杠的写法（chinese/marx/）。"""
    path = urllib.parse.urlparse(link).path
    for p in prefixes:
        if p.startswith("http"):
            if link.startswith(p):
                return True
        elif path.startswith("/" + p.lstrip("/")):
            return True
    return False


def cmd_crawl(a):
    out = Path(a.corpus)
    (out / "txt").mkdir(parents=True, exist_ok=True)
    host = urllib.parse.urlparse(a.seed[0]).netloc
    idx_path, state_path, pdf_path = out / "index.jsonl", out / "crawl_state.json", out / "pdfs.json"
    done = {}  # 已存过的 URL → 文件名
    if idx_path.exists():
        for line in idx_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                done[r.get("url") or r.get("u")] = r.get("file") or r.get("f")
    pdfs = json.loads(pdf_path.read_text(encoding="utf-8")) if pdf_path.exists() else {}
    if state_path.exists() and not a.restart:
        st = json.loads(state_path.read_text(encoding="utf-8"))
        pending, seen = st["pending"], set(st["seen"])
        print(f"接着上次抓：已存 {len(done)} 页，队列 {len(pending)}", flush=True)
    else:
        pending, seen = [], set()
    for s in a.seed:
        if s not in seen:
            seen.add(s); pending.append(s)
    nums = [int(p.stem) for p in (out / "txt").glob("*.txt") if p.stem.isdigit()]
    st = {"n": max(nums, default=0), "fetched": 0, "stop": False, "busy": set()}
    q, lock = Queue(), threading.Lock()
    for u in pending:
        q.put(u)

    def save_state():
        with lock:
            left = list(dict.fromkeys(u for u in list(q.queue) + list(st["busy"]) if u))
            state_path.write_text(json.dumps({"pending": left, "seen": sorted(seen)}, ensure_ascii=False), encoding="utf-8")
            pdf_path.write_text(json.dumps(pdfs, ensure_ascii=False, indent=0), encoding="utf-8")
        return left

    def work():
        while True:
            url = q.get()
            if url is None or st["stop"]:
                if url is not None:
                    q.put(url)  # 留在队列里，下次接着抓
                q.task_done(); return
            with lock:
                st["busy"].add(url)
            try:
                markup = decode(fetch(url))
                found = []
                for m in re.finditer(r"href\s*=\s*[\"']?([^\"'\s>]+)", markup, re.I):
                    link = urllib.parse.urljoin(url, html.unescape(m.group(1))).split("#")[0]
                    parts = urllib.parse.urlparse(link)
                    if parts.netloc != host:
                        continue
                    if parts.path.lower().endswith(".pdf"):
                        found.append(("pdf", link, re.sub(r"<[^>]+>|\s+", "", markup[m.end():m.end() + 200].split("</a>")[0])[:60]))
                    elif re.search(r"\.html?$", parts.path, re.I) and allowed(link, a.allow):
                        found.append(("page", link, ""))
                with lock:
                    for kind, link, label in found:
                        if kind == "pdf":
                            pdfs.setdefault(link, label)
                        elif link not in seen:
                            seen.add(link); q.put(link)
                if url not in done:  # 已存过的页只为找链接重抓一遍，不重复保存
                    title, text = page_text(markup)
                    with lock:
                        st["n"] += 1; st["fetched"] += 1
                        name, n = f"{st['n']:05d}.txt", st["fetched"]
                        done[url] = name
                        if n >= a.max:
                            st["stop"] = True
                    (out / "txt" / name).write_text(f"{url}\n{title}\n{text}", encoding="utf-8")
                    with lock, open(idx_path, "a", encoding="utf-8") as f:
                        f.write(json.dumps({"file": name, "url": url, "title": title, "chars": len(text)}, ensure_ascii=False) + "\n")
                    if n % 50 == 0:
                        print(f"已抓 {n} 页，队列 {q.qsize()}", flush=True)
                    if n % 200 == 0:
                        save_state()
            except Exception as e:
                print("出错", url, repr(e)[:120], flush=True)
            finally:
                with lock:
                    st["busy"].discard(url)
                q.task_done()
            time.sleep(a.delay)

    threads = [threading.Thread(target=work, daemon=True) for _ in range(a.workers)]
    for t in threads:
        t.start()
    try:
        while q.unfinished_tasks and not st["stop"]:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("收到中断，等手上的几页抓完……", flush=True)
    st["stop"] = True
    for _ in threads:
        q.put(None)  # 每个线程收到下一项就退出
    try:
        while any(t.is_alive() for t in threads):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass  # 再按一次就不等了，没抓完的页还在队列里
    left = save_state()
    if not left:
        state_path.unlink(missing_ok=True)
    print(f"本次新存 {st['fetched']} 页，语料共 {len(done)} 页；PDF 链接 {len(pdfs)} 个（记在 pdfs.json，没有下载）；"
          + (f"队列剩 {len(left)}，再运行同一命令接着抓" if left else "已抓完"))
    return 0


def cmd_pdf(a):
    try:
        from pypdf import PdfReader
    except ImportError:
        sys.exit("需要 pypdf：python -m pip install pypdf")
    out = Path(a.corpus) / "txt"
    out.mkdir(parents=True, exist_ok=True)
    src = Path(a.file)
    fullwidth = str.maketrans("０１２３４５６７８９", "0123456789")
    parts = [a.url or src.as_posix(), a.title, a.title]
    reader = PdfReader(str(src))
    chars = 0
    for i, page in enumerate(reader.pages, 1):
        try:
            t = page.extract_text() or ""
        except Exception:
            t = ""
        t = t.translate(fullwidth)
        t = re.sub(r"(?<![一-鿿A-Za-z])·(?=[一-鿿])|(?<=[一-鿿])·(?=[一-鿿]·)", "", t)
        t = re.sub(r"\s*\n\s*", "", t)
        chars += len(t)
        parts.append(f"[PDF第{i}页] {t}")
    target = out / f"pdf_{src.stem}.txt"
    target.write_text("\n".join(parts), encoding="utf-8")
    print(f"{target.name}：{len(reader.pages)} 页，{chars} 字。文字层太少的是扫描件，需要先 OCR")
    return 0


def cmd_grep(a):
    files = sorted((Path(a.corpus) / "txt").glob("*.txt"))
    if not files:
        sys.exit("语料目录里没有 txt，先 crawl 或 pdf")
    hits = 0
    for fp in files:
        t = fp.read_text(encoding="utf-8")
        head = t[:600].split("\n")
        url, title = head[0], head[1] if len(head) > 1 else ""
        if a.t and a.t not in title and a.t not in t[:600]:
            continue
        if a.url and a.url not in url:
            continue
        first, last = a.kw[0], -10 ** 9
        i = t.find(first)
        while i >= 0:
            window = t[max(0, i - a.w):i + a.w]
            if all(k in window for k in a.kw) and i - last > a.w:
                last = i
                hits += 1
                start = max(0, i - a.c)
                print(f"--- {fp.name} @{start} | {title[:50]} | {url}")
                print(t[start:i + a.c + len(first)].replace("\n", " ⏎ "))
                if hits >= a.max:
                    print("（达到上限。加 --t、--url 或更多关键词收窄）")
                    return 0
            i = t.find(first, i + 1)
    print(f"共 {hits} 处；语料 {len(files)} 页")
    return 0


def cmd_show(a):
    t = (Path(a.corpus) / "txt" / a.file).read_text(encoding="utf-8")
    print(t[:300].split("\n")[1] if "\n" in t[:300] else "")
    print(t[a.start:a.start + a.length])
    return 0


def main():
    ap = argparse.ArgumentParser(description="本地引文语料：抓取、转换、检索")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("crawl"); p.add_argument("corpus")
    p.add_argument("--seed", action="append", required=True); p.add_argument("--allow", action="append", required=True)
    p.add_argument("--max", type=int, default=4000, help="本次新存大约多少页就停（正在抓的几页会存完）")
    p.add_argument("--delay", type=float, default=0.3, help="每个线程两次请求之间的间隔（秒）")
    p.add_argument("--workers", type=int, default=3, help="同时抓几页，别超过 6")
    p.add_argument("--restart", action="store_true", help="不接着上次的队列，从种子页重来（已存的页不重复保存）")
    p = sub.add_parser("pdf"); p.add_argument("corpus"); p.add_argument("file")
    p.add_argument("--title", required=True); p.add_argument("--url", default="")
    p = sub.add_parser("grep"); p.add_argument("corpus"); p.add_argument("kw", nargs="+")
    p.add_argument("--t", default=""); p.add_argument("--url", default="")
    p.add_argument("--w", type=int, default=300); p.add_argument("--c", type=int, default=160); p.add_argument("--max", type=int, default=12)
    p = sub.add_parser("show"); p.add_argument("corpus"); p.add_argument("file")
    p.add_argument("start", type=int); p.add_argument("length", type=int)
    a = ap.parse_args()
    return {"crawl": cmd_crawl, "pdf": cmd_pdf, "grep": cmd_grep, "show": cmd_show}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
