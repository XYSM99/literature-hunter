#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量提取 PDF 元信息并做完整性校验。

用于 Step 5「结构化输出」：把页数、大小、首页标题做成清单，
避免照抄站点标称值（站点常缺项或已过期）。

依赖：pypdf（如未安装：pip install pypdf）

用法：
    python pdf_probe.py ./downloads
    python pdf_probe.py ./downloads --format json
    python pdf_probe.py ./downloads --rename-by-year
"""

import argparse
import glob
import json
import os
import re
import sys

try:
    from pypdf import PdfReader
except ImportError:
    sys.stderr.write(
        "缺少 pypdf，请先安装：pip install pypdf\n"
        "（在隔离环境中使用对应的 python 解释器安装）\n")
    raise

YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.2f %s" % (n, unit)
        n /= 1024.0


def read_info(path):
    info = {
        "file": os.path.basename(path),
        "path": path,
        "size_bytes": os.path.getsize(path),
        "size": human_size(os.path.getsize(path)),
        "pages": None,
        "title_head": "",
        "year": None,
        "complete": False,
        "error": None,
    }
    try:
        with open(path, "rb") as f:
            head = f.read(5)
            f.seek(0, os.SEEK_END)
            size = f.tell()
            tail_len = min(2048, size)
            f.seek(-tail_len, os.SEEK_END)
            tail = f.read()
        info["complete"] = head == b"%PDF-" and b"%%EOF" in tail
    except OSError as e:
        info["error"] = "read-error: %s" % e
        return info

    try:
        reader = PdfReader(path)
        info["pages"] = len(reader.pages)
        first = (reader.pages[0].extract_text() or "").strip()
        info["title_head"] = re.sub(r"\s+", " ", first)[:120]
        m = YEAR_RE.search(info["title_head"])
        if m:
            info["year"] = int(m.group(0))
    except Exception as e:
        info["error"] = "parse-error: %s" % type(e).__name__
    return info


def collect(targets):
    files = []
    for t in targets:
        if os.path.isdir(t):
            files.extend(sorted(glob.glob(os.path.join(t, "**", "*.pdf"), recursive=True)))
        else:
            files.append(t)
    return [read_info(f) for f in files if os.path.exists(f)]


def print_table(rows):
    headers = ["文件", "页数", "大小", "首页开头", "版本年份", "完整性"]
    widths = [max([len(r["file"]) for r in rows] + [len(headers[0])]),
              8, 10, 40, 10, 8]
    line = "  ".join("-" * w for w in widths)
    print("  ".join(h.ljust(w) for h, w in zip(headers, widths)))
    print(line)
    for r in rows:
        cells = [
            r["file"],
            str(r["pages"] if r["pages"] is not None else "-"),
            r["size"],
            (r["title_head"][:38] + "...") if len(r["title_head"]) > 40 else r["title_head"],
            str(r["year"] or "-"),
            "完整" if r["complete"] else "不完整",
        ]
        print("  ".join(c.ljust(w) for c, w in zip(cells, widths)))
    bad = [r for r in rows if not r["complete"]]
    if bad:
        print("\n需重下载（不完整）：")
        for r in bad:
            print("  - %s%s" % (r["file"], "  (%s)" % r["error"] if r["error"] else ""))


def main():
    ap = argparse.ArgumentParser(description="PDF 元信息提取与完整性校验")
    ap.add_argument("targets", nargs="+", help="PDF 文件或目录")
    ap.add_argument("--format", choices=("table", "json"), default="table")
    ap.add_argument("--rename-by-year", action="store_true",
                    help="按首页识别到的年份重命名为 <原名>_<年份>.pdf")
    args = ap.parse_args()

    rows = collect(args.targets)
    if not rows:
        print("未找到任何 PDF")
        return 1

    if args.format == "json":
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        print_table(rows)

    if args.rename_by_year:
        renamed = 0
        for r in rows:
            if not r["year"]:
                continue
            stem, ext = os.path.splitext(r["path"])
            new = "%s_%d%s" % (stem, r["year"], ext)
            if not os.path.exists(new):
                os.rename(r["path"], new)
                print("renamed -> %s" % os.path.basename(new))
                renamed += 1
        print("重命名 %d 个" % renamed)

    incomplete = sum(1 for r in rows if not r["complete"])
    print("\n合计 %d 个文件，%d 个不完整" % (len(rows), incomplete))
    print("声明：本 skill 仅用于检索公开信息，使用时请遵守各网站的服务条款。")
    return 0 if incomplete == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
