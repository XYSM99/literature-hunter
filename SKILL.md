---
name: literature-hunter
description: 从境外政府/国际组织/学会/标准机构的官方网站检索、筛选、抓取并结构化整理公开文献资料（技术手册、临床指南、标准规范、法律法规、统计报告等）。当用户提出「查某机构某某手册有几个版本」「把某份指南下载下来」「找某某标准的原文」等需求，或遇到境外站点访问受限、下载被拦截、版本众多难以取舍、需要把检索结果整理成清单/对照表/文档时，应使用本技能。This skill should be used when locating, screening, downloading, or structuring overseas publicly available literature such as technical manuals, clinical guidelines, regulatory documents, standards and statistical reports.
agent_created: true
---

# 文献猎手（Literature Hunter）

## Purpose

把「找到境外公开文献 → 拿到完整原文件 → 整理成可用清单」这件事流程化，替代临时试错。核心价值在三点：**定位快**（知道去哪一类站点找、怎么搜）、**拿得到**（被拦时有一套降级路径）、**输出可用**（不是丢一串链接，而是结构化成清单与对照表）。

## When to use

出现以下任一情形时启用：

- 需要境外机构（政府部门、国际组织、行业学会、标准制定机构）发布的公开文档原文
- 需要梳理某一文档的版本沿革、生效时间、篇幅、获取渠道
- 目标站点访问受限、返回 403 / 404 / 超时，或下载到一半中断
- 检索结果杂乱，需要筛选权威版本并剔除二手、过时、转述内容
- 需要把一批文献整理成清单、对照表、Word/Excel 交付物

## Core workflow

### Step 1 — 拆解需求

明确五件事，避免无效抓取：

| 维度 | 要确定的内容 |
|---|---|
| 发布主体 | 哪家机构？官方站点域名是什么？（决定检索起点） |
| 文档类型 | 技术手册 / 指南 / 标准 / 法规 / 统计年报 / 数据表 |
| 时间范围 | 是否只要现行版？还是要历年版本？起止年份 |
| 语言与形式 | 英文原文即可，还是需要对译；PDF / Excel / 网页表格 |
| 交付形态 | 只要文件？还是要清单表、版本对照表、说明文档 |

### Step 2 — 检索定位

加载 `references/sources.md` 获取按领域分类的站点清单与检索语法。

要点：

- **优先官方 domains**：政府与非营利机构域名通常以 `.gov` `.int` `.org` 结尾，其次是高校 `.edu`
- **按文件名搜索**：目标文档往往有固定命名规律（如 `xxx_manual_2024.pdf`），搜文件名比搜标题更准
- **警惕 "current" 陷阱**：很多站点用 `xxx_current.pdf` 指向最新版，历史版本藏在 `/archive/`、`/previous/`、`/validation/<年份>/`、站点子库里
- **自建记录型站点（ institutional repository）是金矿**：官方主页下架的资料常被永久编号保存在机构知识库里，用 `${站点}/view/<编号>/...` 形式可长期取用
- 用 WebFetch/WebSearch 先定位目录页，从目录页的 `<a href>` 提取真实文件链接，比猜测 URL 可靠
- 每个候选链接先做小范围探测（`Range: bytes=0-99`）确认存在与文件类型，再决定是否拉取全文

### Step 3 — 筛选与去重

加载 `references/filtering.md`。

判断优先级：**发布主体权威性 > 版本时效性 > 完整性 > 获取稳定性**。同一份文档同时出现在官网与第三方站点时，先判断第三方是否为授权转载；二手转载（网盘、文库、个人博客）仅在官网与镜像均不可用且已明确标注的情况下采用，并在交付时注明来源差异。

### Step 4 — 抓取下载

加载 `references/access-playbook.md` 获取受限访问的降级路径。

常规执行：

```bash
# 单文件抓取（自动协议降级 + 断点续传 + 完整性校验）
python scripts/fetch_docs.py --url "<URL>" --out-dir ./downloads

# 从清单批量抓取（每行一个 URL，可给多个候选）
python scripts/fetch_docs.py --list urls.txt --out-dir ./downloads

# 批量提取元信息（页数、大小、首页标题、是否完整）
python scripts/pdf_probe.py ./downloads --format table
```

关键原则：

- 先探测、后下载：一律先用小范围请求验证可达性，确认无误再取全文
- 单线程、串行抓取，保留请求间隔，避免给目标站点造成压力
- 下载后必须校验完整性，PDF 检查文件尾部是否有 `%%EOF`
- 中断优先用断点续传补齐；**但服务器不支持 Range 时必须整份重下**——
  盲目 `-C -` 会卡在残缺状态（curl 报 exit 33），脚本已自动识别并切换
- 续传写入前确认响应是 206；若服务器忽略 Range 返回 200 全量，必须从头覆盖写，否则文件损坏

### Step 5 — 结构化输出

加载 `references/output-format.md` 套用输出模板。

三种典型交付物：

1. **版本沿革表** — 适用「某手册有几个版本」类需求：版本 / 生效日期 / 篇幅页数 / 文件大小 / 获取来源 / 备注
2. **批次清单表** — 适用「批量下载」类需求：序号 / 文档名 / 年份 / 页数 / 大小 / 本地路径 / 校验状态
3. **单文档摘要卡** — 适用「帮我看看这份文件」类需求：发布主体、版本与时间、覆盖范围、关键变化、获取链接

输出要求：

- 页数、大小一律以**实际解析结果**为准，不照抄站点标称值（站点标称常缺失或过期）
- 无法获取的信息明确标注「站点未提供」或「待核实」，不留空、不臆造
- 交付文档默认中文；若用户指定字体或格式（如 Word + 指定字体），按其偏好输出

## Hard constraints（不可协商）

1. **不携带任何凭据**：不在脚本、文档、示例、注释中写入账号、密码、Cookie、Token、API Key。所有访问均为匿名只读。
2. **只碰公开资源**：不绕过付费墙、不尝试登录、不抓取需授权内容。
3. **合规声明**：本 skill 仅用于检索公开信息，使用时请遵守各网站的服务条款。每次交付产物时应附上该声明。
4. **控制抓取强度**：串行请求、保留间隔、禁止并发压测目标站点。
5. **交付前自检**：列出待发布文件清单，逐项检查是否残留账号、密钥、个人信息、本地绝对路径。

## Quick reference

| 情形 | 动作 |
|---|---|
| https 返回 403 | 换 http 协议重试（不少政府站点 CDN 对 https 更严格） |
| 站点整站不可达 | 查机构知识库记录号、同域镜像域名、REST 化服务源 |
| 文件只有部分下载 | `Range` 续传补齐，检查 `%%EOF` |
| 续传无效（curl exit 33 / 文件不增长） | 服务器不支持 Range，去掉 `-C -` 整份重下 |
| 续传后文件变大但仍损坏 | 服务器忽略 Range 返回了 200 全量却被追加写入，改为从头覆盖写 |
| 历史版本找不回 | 从现行版页面找 previous versions 链接 → 机构知识库 → 年份目录命名规律 |
| 不知文件是否完整 | `python scripts/pdf_probe.py <file>` |
| 需要建清单表 | 套 `references/output-format.md` 模板 |

## Bundled resources

- `references/sources.md` — 按领域分类的官方源清单与检索语法
- `references/access-playbook.md` — 受限访问的降级路径与命令行写法
- `references/filtering.md` — 可信度评估、版本识别与去重规则
- `references/output-format.md` — 三类结构化输出模板
- `scripts/fetch_docs.py` — 匿名抓取：协议降级、断点续传、尾部校验
- `scripts/pdf_probe.py` — PDF 元信息提取与完整性校验
- `assets/sample-output.png` — 示例输出截图
