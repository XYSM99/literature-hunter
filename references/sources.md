# 检索源清单与定位语法

本文件为 Step 2「检索定位」的参考。所有站点均为公开访问，匿名只读，不需要任何账号或密钥。

## 一、按资料类型选站点

### 政府部门・监管机构（一手权威）

| 主体 | 典型域名 | 常见资料 |
|---|---|---|
| 美国 CDC | cdc.gov | 技术手册、监测方案、指南、统计年报 |
| 美国 NIH / NLM | nih.gov, nlm.nih.gov | 共识文件、PubMed 检索 |
| 美国 FDA | fda.gov | 器械指引、药品说明书、行业指南 |
| 美国 CMS | cms.gov | 质量报告、医保支付规则 |
| 美国 EPA | epa.gov | 环境标准、技术白皮书 |
| 欧盟 / ECDC | europa.eu, ecdc.europa.eu | 欧盟指令、监测报告 |
| 英国 UKHSA / GOV.UK | gov.uk | 公共卫生指南、法规 |
| WHO / PAHO | who.int, paho.org | 国际指南、技术文件、疫情通报 |

### 国际组织・标准机构

| 主体 | 域名 | 说明 |
|---|---|---|
| ISO / IEC / ASTM | iso.org, iec.ch, astm.org | 标准文本（部分收费，需注意版权） |
| CLSI / AAMI | clsi.org, aami.org | 检验、器械行业标准 |
| NICE / SIGN | nice.org.uk, sign.ac.uk | 循证指南 |
| OECD / World Bank | oecd.org, worldbank.org | 统计数据库、政策报告 |

### 学协会（多为 PDF 直挂）

APIC、SHEA、IDSA、ATS、ASPEN、ASH、ESCMID 等 —— 通常把指南 PDF 挂在自己的 `/guidelines/` 或 `/resources/` 下，是官方文件的主力。

### 机构知识库（ institutional repository）—— 找历史版本的关键

许多政府与科研机构设有永久保存库，即使主页下架，仍有编号记录：

- **CDC Stacks**（CDC 官方出版物的保存库，`stacks.cdc.gov/view/cdc/<编号>/`）
- Zenodo、OSF、Dryad、Figshare（数据集与预印本，附带 DOI）
- 高校 IR（`dspace`、`digitallibrary` 类站点）

**用法**：先搜 「文档标题 + 年份」，若结果中出现 `site/view/<数字编号>` 形态的链接，基本就是稳定的永久存档，优先选用。

### 文献检索入口

| 用途 | 入口 |
|---|---|
| 生物医学文献题录 | PubMed、Europe PMC |
| 全文开放获取 | PMC、DOAJ |
| 预印本 | medRxiv、bioRxiv、arXiv |
| 灰色文献 | 搜索引擎 + `filetype:pdf` |

## 二、定位语法

### 搜索引擎 tactics

| 技巧 | 写法 | 用途 |
|---|---|---|
| 精确短语 | `"Patient Safety Component Manual"` | 排除词序干扰 |
| 文件类型 | `filetype:pdf` | 只找 PDF 原件 |
| 站点限定 | `site:cdc.gov` | 限定权威域 |
| 排除词 | `-zhihu -baidu` | 剔除二手中文转述 |
| 年份定位 | `2024 OR 2025` | 缩小版本范围 |
| 文件名模式 | `"pcsmanual_2024"`、`"manual_20??"` | 命中内部命名规律 |
| 标题补全 | 搜 `"Table of Contents" + 关键词` | 找到目录页，顺藤摸瓜拿链接 |

**顺序建议**：先用网页搜索找「目录页」→ 抓取目录页 HTML → 用正则从 `href` 提取 `.pdf` 链接 → 得到真实文件地址。这比猜测 URL 命中率高得多。

### 目录页提取链接的写法

```bash
curl -sL --max-time 45 -o page.html "<目录页 URL>"
grep -oE 'href="[^"]*\.pdf[^"]*"' page.html | sort -u
```

相对路径需拼上目录页基址后再用。

### 年份命名规律

官方手册常见存放规律（猜不出就回退到目录页）：

```
/pdf/<topic>/<topic>manual_<年份>.pdf
/pdf/validation/<年份>/<topic>manual_<年份>.pdf
/archive/<年份>/<topic>_manual.pdf
```

## 三、永久编号 versus current

同一份文档往往有两个入口：

- **current 型**：`<name>_current.pdf` —— 始终指向最新版，适合「只要现行」
- **编号/年份型**：`<name>_<年份>.pdf` 或知识库编号 —— 适合「要特定版本」

**拿版本历史时，务必找年份型链接**；只取现行版才用 current 型。两者混用容易把不同年份的文件误记为同一版。
