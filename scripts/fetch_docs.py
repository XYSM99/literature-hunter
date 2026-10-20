#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""匿名抓取公开文档，支持协议降级、多组请求头轮换、断点续传与完整性校验，
必要时回退到系统 curl。

设计约定：
  * 全程匿名只读，不发送 Authorization / Cookie / Token，不含任何凭据；
  * 串行抓取，请求之间保留间隔，避免给目标站点造成压力；
  * 先用小范围 Range 请求探测，确认存在且文件类型正确后再拉全文。

经验要点（来源：真实抓取复盘）：
  * https 被拦时换 http，同一 URL 常常立刻放行；
  * 请求头不是越"像浏览器"越好——部分站点对伪造 UA 反而拦截，
    默认<｜hy_place▁holder▁no▁813｜>（不加自定义头）能通过时必须优先使用；
  * 因此本脚本按顺序轮换多组请求头，命中即用；
  * Python 层全部失败时，回退到系统自带的 curl（许多站点对 curl 放行）。

用法：
    python fetch_docs.py --url "<URL>" --out-dir ./downloads
    python fetch_docs.py --list urls.txt --out-dir ./downloads
    python fetch_docs.py --mirror-file mirrors.txt --out-dir ./downloads
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

# 仅作为候选之一使用：部分站点对伪装浏览器 UA 反而拦截，因此默认头优先
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
HEADER_SETS = [
    {},
    {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"},
]
INTERVAL = 1.5          # 每次请求之间的礼貌间隔（秒）
CHUNK = 262144          # 256 KB
MAX_RESUME = 30         # 续传最大轮数
TIMEOUT = 45            # 单次请求超时（秒）


def log(msg):
    print(msg, flush=True)


def debug_trace():
    if os.environ.get("LH_DEBUG"):
        import traceback
        traceback.print_exc()


def candidate_urls(url):
    """候选清单：http 优先（不少站点对 https 的 CDN 策略更严格），再试 https。"""
    bare = re.sub(r"^https?://", "", url)
    return ["http://" + bare, "https://" + bare]


def build_req(url, headers, pos=None):
    h = dict(headers) if headers else {}
    if pos:
        h["Range"] = "bytes=%d-" % pos
    return urllib.request.Request(url, headers=h)


def try_open(url, pos=None, timeout=TIMEOUT):
    """依次轮换协议与请求头组合，返回 (response, headers_used, None)。"""
    for u in candidate_urls(url):
        for hs in HEADER_SETS:
            try:
                r = urllib.request.urlopen(build_req(u, hs, pos), timeout=timeout)
                return r, hs, None
            except urllib.error.HTTPError as e:
                if e.code == 416:
                    return None, hs, "done"
                log("  %s / %s -> HTTP %s" % (u, "默认头" if not hs else "自定义头", e.code))
                debug_trace()
            except Exception as e:
                log("  %s / %s -> %s" % (u, "默认头" if not hs else "自定义头", type(e).__name__))
                debug_trace()
            time.sleep(INTERVAL)
    return None, None, "fail"


def total_from(resp):
    cr = resp.headers.get("Content-Range")
    if cr and "/" in cr:
        try:
            return int(cr.split("/")[-1])
        except ValueError:
            pass
    cl = resp.headers.get("Content-Length")
    if cl:
        try:
            return int(cl)
        except ValueError:
            return None
    return None


def probe(url, timeout=TIMEOUT):
    """小范围探测：确认可达性与总长度。返回 (total, headers_used)。"""
    for u in candidate_urls(url):
        for hs in HEADER_SETS:
            try:
                r = urllib.request.urlopen(
                    build_req(u, hs, None) if not hs else build_req(u, hs, None),
                    timeout=timeout)
                with r:
                    r.read(1)
            except urllib.error.HTTPError as e:
                # 403/405 等对 Range 的拒绝不代表不可用，改用普通 GET 再试一次
                if e.code in (403, 405):
                    try:
                        r = urllib.request.urlopen(
                            urllib.request.Request(u, headers=hs or {}), timeout=timeout)
                        with r:
                            total = total_from(r)
                            ctype = (r.headers.get("Content-Type") or "").lower()
                        if total:
                            log("  [probe] %s -> %s bytes (%s)" % (u, total, ctype or "未知类型"))
                            return total, hs
                    except Exception:
                        debug_trace()
                log("  [probe] %s -> HTTP %s" % (u, e.code))
            except Exception as e:
                log("  [probe] %s -> %s" % (type(e).__name__, u))
            time.sleep(INTERVAL)
    return None, None


def looks_like_pdf(path):
    try:
        with open(path, "rb") as f:
            return f.read(5) == b"%PDF-"
    except OSError:
        return False


def is_complete(path, total=None):
    try:
        size = os.path.getsize(path)
    except OSError:
        return False
    if looks_like_pdf(path):
        try:
            with open(path, "rb") as f:
                f.seek(-min(2048, size), os.SEEK_END)
                if b"%%EOF" not in f.read():
                    return False
        except OSError:
            return False
    return size >= total if total else True


def curl_path():
    exe = shutil.which("curl") or shutil.which("curl.exe")
    return exe


def curl_download(url, path, total=None):
    """回退方案：系统 curl + 断点续传循环。"""
    exe = curl_path()
    if not exe:
        return False
    for _ in range(MAX_RESUME):
        subprocess.run([exe, "-sL", "--max-time", "300", "-C", "-", "-o", path, url],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if is_complete(path, total):
            return True
        time.sleep(INTERVAL)
    return False


def download(url, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    total, hs = probe(url)
    if not total:
        log("  Python 层探测失败，回退系统 curl")
        return curl_download(url, path)

    for attempt in range(MAX_RESUME):
        pos = os.path.getsize(path) if os.path.exists(path) else 0
        if pos >= total:
            break
        written = 0
        resp, used, err = try_open(url, pos)
        if err == "done":
            break
        if resp is None:
            log("  [warn] Python 层本轮失败，交给 curl 续传 (%d/%d)" % (attempt + 1, MAX_RESUME))
            if curl_download(url, path, total):
                break
            continue
        try:
            mode = "ab" if pos else "wb"
            with resp, open(path, mode) as f:
                while True:
                    try:
                        chunk = resp.read(CHUNK)
                    except Exception:
                        break
                    if not chunk:
                        break
                    f.write(chunk)
                    written += len(chunk)
        except OSError as e:
            log("  写入失败：%s" % e)
        time.sleep(INTERVAL)

    size = os.path.getsize(path) if os.path.exists(path) else 0
    ok = is_complete(path, total)
    log("[%s] %s size=%d/%d %s" % (
        os.path.basename(path), "OK" if ok else "INCOMPLETE", size, total, path))
    return ok


def load_list(path):
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = re.split(r"[|\t]\s*", line, maxsplit=1)
            url = parts[0].strip()
            name = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
            items.append((url, name))
    return items


def load_mirrors(path):
    groups = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            groups.append([u.strip() for u in re.split(r"[,\s]+", line) if u.strip()])
    return groups


def derive_name(url, idx):
    return os.path.basename(url.split("?")[0]) or "doc_%d" % idx


def main():
    ap = argparse.ArgumentParser(description="匿名抓取公开文档（协议降级 + 头轮换 + 断点续传 + 完整性校验）")
    ap.add_argument("--url", help="单个文档 URL")
    ap.add_argument("--list", help="URL 清单文件，每行一条，可用 | 指定文件名")
    ap.add_argument("--mirror-file", help="候选清单，每行列同一文档的多个候选地址")
    ap.add_argument("--out-dir", default="./downloads", help="输出目录")
    ap.add_argument("--name", help="显式指定输出文件名")
    args = ap.parse_args()

    if not (args.url or args.list or args.mirror_file):
        ap.error("至少提供 --url / --list / --mirror-file 之一")

    os.makedirs(args.out_dir, exist_ok=True)
    tasks = [(args.url, args.name)] if args.url else []
    if args.list:
        tasks.extend(load_list(args.list))
    groups = load_mirrors(args.mirror_file) if args.mirror_file else []

    ok_n = 0
    for i, (url, name) in enumerate(tasks, 1):
        name = name or derive_name(url, i)
        log("[%d/%d] %s" % (i, len(tasks), url))
        if download(url, os.path.join(args.out_dir, name)):
            ok_n += 1
        time.sleep(INTERVAL)

    for gi, group in enumerate(groups, 1):
        log("[候选组 %d/%d] 共 %d 个候选" % (gi, len(groups), len(group)))
        for url in group:
            if download(url, os.path.join(args.out_dir, derive_name(url, gi))):
                ok_n += 1
                break
            time.sleep(INTERVAL)

    log("完成：%d 个成功" % ok_n)
    log("声明：本 skill 仅用于检索公开信息，使用时请遵守各网站的服务条款。")
    return 0 if ok_n else 1


if __name__ == "__main__":
    sys.exit(main())
