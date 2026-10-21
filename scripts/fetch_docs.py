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


def build_req(url, headers, rng=None):
    """rng 为 None 时不发 Range；(start,) 表示 bytes=start-；(start, end) 表示闭区间。"""
    h = dict(headers) if headers else {}
    if rng:
        h["Range"] = "bytes=%d-" % rng[0] if len(rng) == 1 else "bytes=%d-%d" % (rng[0], rng[1])
    return urllib.request.Request(url, headers=h)


def try_open(url, pos=None, timeout=TIMEOUT):
    """依次轮换协议与请求头组合，返回 (response, headers_used, err)。

    err 取值：None（成功）/ "done"（416，说明已下完）/ "fail"（全部组合都失败）。
    """
    for u in candidate_urls(url):
        for hs in HEADER_SETS:
            try:
                r = urllib.request.urlopen(build_req(u, hs, (pos,) if pos else None),
                                           timeout=timeout)
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
    """小范围探测：确认可达性、总长度，以及服务器是否支持 Range。

    返回 (total, headers_used, supports_range)。
    顺序：先发 Range: bytes=0-99 只取前 100 字节（最省流量）；
    服务器忽略 Range 时返回 200，同样能拿到 Content-Length；
    403/405/501 等明确拒绝 Range 时，退成普通 GET 再试一次。
    """
    for u in candidate_urls(url):
        for hs in HEADER_SETS:
            tag = "默认头" if not hs else "自定义头"
            try:
                r = urllib.request.urlopen(build_req(u, hs, (0, 99)), timeout=timeout)
                with r:
                    total = total_from(r)
                    ctype = (r.headers.get("Content-Type") or "").lower()
                    status = getattr(r, "status", None)
                    r.read(1)
                if total:
                    log("  [probe] %s / %s -> %s bytes (%s) [%s]" % (
                        u, tag, total, ctype or "未知类型",
                        "支持续传" if status == 206 else "不支持续传"))
                    return total, hs, status == 206
                log("  [probe] %s / %s -> 未返回长度信息" % (u, tag))
            except urllib.error.HTTPError as e:
                if e.code not in (403, 405, 400, 501):
                    log("  [probe] %s / %s -> HTTP %s" % (u, tag, e.code))
                # 拒绝或不支持 Range：改用普通 GET 再试一次
                try:
                    r = urllib.request.urlopen(
                        urllib.request.Request(u, headers=dict(hs)), timeout=timeout)
                    with r:
                        total = total_from(r)
                        ctype = (r.headers.get("Content-Type") or "").lower()
                        r.read(1)
                    if total:
                        log("  [probe] %s / %s -> %s bytes (%s) [普通GET]" % (
                            u, tag, total, ctype or "未知类型"))
                        return total, hs, False
                except urllib.error.HTTPError as e2:
                    log("  [probe] %s / %s -> 普通GET HTTP %s" % (u, tag, e2.code))
                except Exception as e2:
                    log("  [probe] %s / %s -> 普通GET %s" % (u, tag, type(e2).__name__))
                    debug_trace()
            except Exception as e:
                log("  [probe] %s / %s -> %s" % (u, tag, type(e).__name__))
                debug_trace()
            time.sleep(INTERVAL)
    return None, None, False


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


def curl_download(url, path, total=None, resume=True):
    """回退方案：系统 curl + 断点续传循环。

    关键：curl 的 `-C -` 在服务器不支持字节范围时会直接报错退出（exit 33，
    "HTTP server doesn't seem to support byte ranges"），文件永远停在残缺状态。
    因此每轮都比对文件大小：只要一轮下来没有任何增长，就判定续传无效，
    下一轮去掉 `-C -` 整份重下。
    """
    exe = curl_path()
    if not exe:
        return False
    for _ in range(MAX_RESUME):
        before = os.path.getsize(path) if os.path.exists(path) else 0
        cmd = [exe, "-sL", "--max-time", "300"]
        if resume and before > 0:
            cmd += ["-C", "-"]
        cmd += ["-o", path, url]
        proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if is_complete(path, total):
            return True
        after = os.path.getsize(path) if os.path.exists(path) else 0
        if resume and (proc.returncode != 0 or after <= before):
            log("  [warn] curl 续传无效（exit %d，%d -> %d 字节），改为整份重下"
                % (proc.returncode, before, after))
            resume = False       # 下一轮去掉 -C -
            continue
        time.sleep(INTERVAL)
    return False


def download(url, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    total, hs, supports_range = probe(url)
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
            if curl_download(url, path, total, resume=supports_range):
                break
            continue
        try:
            # 服务器若忽略 Range 会返回 200 全量，此时追加写必然损坏文件，
            # 必须改成从头覆盖；只有确认 206 才允许续写。
            status = getattr(resp, "status", None)
            if pos and status != 206:
                log("  [warn] 服务器忽略 Range（返回 %s），本轮整份重下" % status)
                pos = 0
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
    if not ok:
        log("  [提示] 仍未下载完整。常见原因：① 站点对匿名请求限流；"
            "② 服务器不支持断点续传且单次连接被中断；③ URL 实际返回的是错误页（非 PDF）。"
            "建议：换用 --mirror-file 指定镜像地址，或稍后重试。")
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
