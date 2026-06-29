"""
从巨潮资讯网下载A股年报PDF，提取全文文本或结构化表格。
表格提取内置质量评分，pdfplumber提取质量不达标时自动渲染页面图片，供Claude Vision读取。

依赖: akshare, requests, pdfplumber, PyMuPDF (fitz)
前置: ak.set_token("your_cninfo_token") 需在调用前设置

用法:
    # 全文提取（向后兼容）
    from extract_annual_report import extract
    data = extract("600110", 2025)
    print(data["text"][:500])

    # 结构化表格提取（自动 pdfplumber → Vision回退）
    from extract_annual_report import extract_section, extract_sections
    r = extract_section("002709", 2024, "revenue_breakdown")
    print(r["source"], r["quality_score"])  # "pdfplumber" 85 或 "vision_needed" 55

    # 批量提取
    result = extract_sections("002709", 2024)
    print(result["summary"])  # {total, pdfplumber_success, vision_needed, failed}
"""

import re, io, time, os
import requests
import pdfplumber
import akshare as ak
import fitz  # PyMuPDF，PDF页面渲染为图片，供Vision回退


def extract(symbol: str, year: int) -> dict:
    """
    下载指定股票和年份的年报PDF，提取全文文本。

    Args:
        symbol: 6位股票代码，如 "600110"
        year: 年报年份，如 2025

    Returns:
        dict:
            - success: bool
            - title: 公告标题
            - pages: 总页数
            - text: 全文文本 (~20-40万字)
            - size_mb: PDF文件大小
            - elapsed: 总耗时(秒)
            - error: 错误信息 (仅失败时)
    """
    t0 = time.time()
    result = {
        "success": False,
        "title": "",
        "pages": 0,
        "text": "",
        "size_mb": 0,
        "elapsed": 0,
    }

    # Step 1: 查年报公告
    try:
        df = ak.stock_zh_a_disclosure_report_cninfo(
            symbol=symbol,
            category="年报",
            start_date=f"{year}0101",
            end_date=f"{year + 1}1231",
        )
    except Exception as e:
        result["error"] = f"查询公告失败: {e}"
        return result

    full = df[df["公告标题"].str.contains("年年度报告$", regex=True)]
    if full.empty:
        result["error"] = f"未找到{year}年年报（共{len(df)}条公告，均非年报全文）"
        return result

    row = full.iloc[0]
    result["title"] = row["公告标题"]

    # Step 2: 构建PDF URL（巨潮静态CDN）
    ann_id = row["公告链接"].split("announcementId=")[1].split("&")[0]
    pdf_url = (
        f"http://static.cninfo.com.cn/finalpage/"
        f"{row['公告时间']}/{ann_id}.PDF"
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }

    # Step 3: 下载PDF（带重试）
    for attempt in range(1, 4):
        try:
            resp = requests.get(pdf_url, headers=headers, timeout=60)
            if resp.status_code == 200:
                break
            if attempt < 3:
                time.sleep(2)
        except Exception:
            if attempt == 3:
                result["error"] = f"PDF下载失败（重试3次后）: {type(e).__name__}"
                return result
            time.sleep(2)
    else:
        result["error"] = f"PDF下载失败: HTTP {resp.status_code}"
        return result

    result["size_mb"] = round(len(resp.content) / 1024 / 1024, 1)

    # Step 4: 提取全文文本
    try:
        pdf = pdfplumber.open(io.BytesIO(resp.content))
        pages_text = []
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                pages_text.append(t)
        result["pages"] = len(pdf.pages)
        result["text"] = "\n".join(pages_text)
        pdf.close()
    except Exception as e:
        result["error"] = f"PDF解析失败: {e}"
        return result

    result["success"] = True
    result["elapsed"] = round(time.time() - t0, 1)
    return result


# ============================================================
#  结构化表格提取 + 质量评分 + Vision 回退
# ============================================================

SECTION_CONFIG = {
    "revenue_breakdown": {
        "keywords": ["营业收入构成", "占公司营业收入", "营业收入 构成",
                     "主营业务分行业", "主营业务分产品", "分产品情况",
                     "分行业情况"],
        "required_fields": ["营业收入", "毛利率", "分产品"],
        "pages_range": (0, 50),
    },
    "customer_concentration": {
        "keywords": ["前五名客户", "客户集中", "主要客户", "主要销售客户",
                     "前五名", "前五大客户"],
        "required_fields": ["客户名称", "销售额", "占年度销售总额"],
        "pages_range": (0, 80),
    },
    "guarantee_pledge": {
        "keywords": ["对外担保", "担保总额", "担保情况", "大股东",
                     "质押股份", "前十名股东", "持股"],
        "required_fields": ["担保", "质押", "净资产"],
        "pages_range": (30, 200),
    },
    "inventory_receivables": {
        "keywords": ["应收账款", "存货", "存货分类", "应收账款分类", "账龄"],
        "required_fields": ["应收账款", "存货", "账面余额"],
        "pages_range": (80, 200),
    },
}

VISION_IMAGE_DIR = "/tmp/astock_vision"


def _clean_table(table: list) -> list:
    """
    清理 pdfplumber extract_table() 的输出：
    1. 去掉全None的行
    2. 合并被拆成多行的表头
    3. 去掉全空列
    """
    if not table:
        return []

    # Step 1: 去全None行
    rows = []
    for row in table:
        has_value = any(c and str(c).strip() for c in row)
        if has_value:
            rows.append([str(c).strip() if c else "" for c in row])

    if not rows:
        return []

    # Step 2: 合并连续的被拆分行（同一逻辑行但被pdfplumber切成2-3行）
    # 规则：当前行有效值 ≤ 1 个，说明它大概率是上一行表头的延续
    merged = [rows[0]]
    for i in range(1, len(rows)):
        curr = rows[i]
        prev = merged[-1]
        curr_filled = sum(1 for c in curr if c)
        # 当前行极稀疏（≤1个有效值）→ 合并到上一行
        if curr_filled <= 1 and len(curr) == len(prev):
            merged[-1] = [
                (prev[j] + (" " + curr[j] if curr[j] else "")).strip()
                for j in range(len(prev))
            ]
        else:
            merged.append(curr)

    # Step 3: 去全空列
    cols = len(merged[0])
    keep_cols = []
    for j in range(cols):
        if any(row[j] for row in merged if j < len(row)):
            keep_cols.append(j)

    result = []
    for row in merged:
        result.append([row[j] if j < len(row) else "" for j in keep_cols])

    return result


def _quality_score(table: list, section_type: str) -> float:
    """
    对清洗后的表格做质量评分，返回 0-100。

    5项检查：
    - 空列比（30%）：空列/总列 > 40% 扣全分
    - 数据密度（20%）：平均每行有效值 < 3 扣全分
    - 碎片化（20%）：数据行<2 扣全分
    - 关键字段（20%）：缺 required_fields 扣分
    - 异常值（10%）：数值数量级异常扣分
    """
    if not table or len(table) < 2:
        return 0.0

    config = SECTION_CONFIG.get(section_type, {})
    required_fields = config.get("required_fields", [])
    n_rows = len(table)
    n_cols = max(len(r) for r in table)

    # 1. 空列比 (0-30)
    empty_cols = 0
    for j in range(n_cols):
        col_vals = [row[j] if j < len(row) else "" for row in table]
        if sum(1 for v in col_vals if v) / max(len(col_vals), 1) < 0.1:
            empty_cols += 1
    empty_ratio = empty_cols / max(n_cols, 1)
    score_empty = 30 * max(0, 1 - empty_ratio / 0.4)

    # 2. 数据密度 (0-20)
    filled_per_row = []
    for row in table:
        filled = sum(1 for c in row if c)
        filled_per_row.append(filled)
    avg_filled = sum(filled_per_row) / len(filled_per_row)
    score_density = 20 * min(1, avg_filled / 3)

    # 3. 碎片化 (0-20)：数据行至少2行
    data_rows = sum(1 for r in table if sum(1 for c in r if c) >= 3)
    score_frag = 20 if data_rows >= 2 else 10 if data_rows >= 1 else 0

    # 4. 关键字段 (0-20)
    if required_fields:
        all_text = " ".join(
            [" ".join(r) for r in table]
        ).lower()
        found = sum(1 for f in required_fields if f.lower() in all_text)
        score_fields = 20 * (found / len(required_fields))
    else:
        score_fields = 20

    # 5. 异常值检查 (0-10)
    score_anomaly = 10
    for row in table:
        for cell in row:
            # 检查是否有明显错误的数字（如负数百分比）
            cleaned = cell.replace(",", "").replace("%", "").strip()
            try:
                val = float(cleaned)
                if abs(val) > 1e15:  # 千万亿，明显异常
                    score_anomaly -= 2
                    break
            except ValueError:
                continue

    total = score_empty + score_density + score_frag + score_fields + score_anomaly
    return round(max(0, min(100, total)), 1)


def search_pages(pdf, keywords: list, pages_range: tuple = None) -> list:
    """
    在PDF中搜索包含指定关键词的页码。

    Args:
        pdf: pdfplumber打开的PDF对象
        keywords: 关键词列表（OR匹配）
        pages_range: (start, end) 页码范围，None=全搜索

    Returns:
        匹配的页码列表（从1开始）
    """
    matched = []
    start = pages_range[0] - 1 if pages_range else 0
    end = min(pages_range[1], len(pdf.pages)) if pages_range else len(pdf.pages)

    for i in range(start, end):
        try:
            text = pdf.pages[i].extract_text()
            if text and any(kw in text for kw in keywords):
                matched.append(i + 1)
        except Exception:
            continue
    return matched


def render_page_image(pdf_path: str, page_num: int, output_dir: str = None) -> str:
    """
    用PyMuPDF渲染PDF指定页面为JPEG图片。

    Args:
        pdf_path: PDF文件路径
        page_num: 页码（从1开始）
        output_dir: 输出目录，默认 VISION_IMAGE_DIR

    Returns:
        渲染后的图片文件路径
    """
    output_dir = output_dir or VISION_IMAGE_DIR
    os.makedirs(output_dir, exist_ok=True)

    base = os.path.splitext(os.path.basename(pdf_path))[0]
    out_path = os.path.join(output_dir, f"{base}_p{page_num}.jpg")

    doc = fitz.open(pdf_path)
    page = doc[page_num - 1]
    mat = fitz.Matrix(1.5, 1.5)
    pix = page.get_pixmap(matrix=mat)
    pix.save(out_path)
    doc.close()
    return out_path


def extract_section(symbol: str, year: int, section_type: str) -> dict:
    """
    提取年报中某个特定章节的结构化表格数据。
    自动走 pdfplumber提取 → 质量评分 → Vision回退。

    Args:
        symbol: 6位股票代码
        year: 年报年份
        section_type: "revenue_breakdown" | "customer_concentration"
                     | "guarantee_pledge" | "inventory_receivables"

    Returns:
        dict: {
            success, section, source, quality_score,
            data: {headers, rows}, image_path, pages, elapsed, error
        }
    """
    t0 = time.time()
    config = SECTION_CONFIG.get(section_type)
    if not config:
        return {
            "success": False, "section": section_type,
            "error": f"不支持的section_type: {section_type}，可选: {list(SECTION_CONFIG.keys())}",
            "elapsed": 0,
        }

    result = {
        "success": False, "section": section_type,
        "source": None, "quality_score": 0,
        "data": None, "image_path": None,
        "pages": [], "elapsed": 0, "error": None,
    }

    # Step 1: 下载PDF（一次下载，内存+磁盘复用）
    try:
        url = _get_pdf_url(symbol, year)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }
        resp = _download_with_retry(url, headers)
        pdf_bytes = resp.content
    except Exception as e:
        result["error"] = f"年报下载失败: {e}"
        result["elapsed"] = round(time.time() - t0, 1)
        return result

    # 保存到磁盘（供Vision渲染用）
    try:
        os.makedirs(VISION_IMAGE_DIR, exist_ok=True)
        pdf_path = os.path.join(VISION_IMAGE_DIR, f"{symbol}_{year}.pdf")
        if not os.path.exists(pdf_path):
            with open(pdf_path, "wb") as f:
                f.write(pdf_bytes)
    except Exception:
        pdf_path = None

    # Step 2: 搜索目标页面
    pdf = pdfplumber.open(io.BytesIO(pdf_bytes))

    matched_pages = search_pages(
        pdf, config["keywords"],
        pages_range=config.get("pages_range")
    )
    result["pages"] = matched_pages

    if not matched_pages:
        pdf.close()
        result["error"] = f"未找到{section_type}相关章节（关键词: {config['keywords']}）"
        result["elapsed"] = round(time.time() - t0, 1)
        return result

    # Step 3: 在所有匹配页提取表格 + 质量评分
    best_table = None
    best_score = 0
    best_page = matched_pages[0]

    for pn in matched_pages:
        try:
            tables = pdf.pages[pn - 1].extract_tables()
        except Exception:
            continue
        for t in tables:
            if not t:
                continue
            cleaned = _clean_table(t)
            if not cleaned or len(cleaned) < 2:
                continue
            score = _quality_score(cleaned, section_type)
            if score > best_score:
                best_score = score
                best_table = cleaned
                best_page = pn

    pdf.close()

    # Step 4: 判断走 pdfplumber 还是 Vision 回退
    QUALITY_THRESHOLD = 70

    if best_table and best_score >= QUALITY_THRESHOLD:
        # pdfplumber 提取通过
        headers = best_table[0] if best_table else []
        rows = best_table[1:] if best_table and len(best_table) > 1 else []
        result["success"] = True
        result["source"] = "pdfplumber"
        result["quality_score"] = best_score
        result["data"] = {"headers": headers, "rows": rows}
        result["pages"] = [best_page]
    elif pdf_path and os.path.exists(pdf_path):
        # Vision 回退
        try:
            img_path = render_page_image(pdf_path, best_page)
            result["success"] = True
            result["source"] = "vision_needed"
            result["quality_score"] = best_score
            result["image_path"] = img_path
            result["pages"] = [best_page]
            result["data"] = None
        except Exception as e:
            result["error"] = f"Vision回退渲染失败: {e}"
    else:
        if best_table:
            # 没有PDF文件但表格勉强可用，降级返回
            headers = best_table[0] if best_table else []
            rows = best_table[1:] if best_table and len(best_table) > 1 else []
            result["success"] = True
            result["source"] = "pdfplumber_low_quality"
            result["quality_score"] = best_score
            result["data"] = {"headers": headers, "rows": rows}
        else:
            result["error"] = "pdfplumber未识别到表格，且无法渲染Vision回退"

    result["elapsed"] = round(time.time() - t0, 1)
    return result


def extract_sections(symbol: str, year: int, section_types: list = None) -> dict:
    """
    批量提取多个章节。

    Args:
        symbol: 6位股票代码
        year: 年报年份
        section_types: 要提取的章节类型列表，默认全部4个

    Returns:
        dict: {sections: {type: result, ...}, summary: {...}}
    """
    if section_types is None:
        section_types = list(SECTION_CONFIG.keys())

    t0 = time.time()
    sections = {}
    vision_needed = []

    for st in section_types:
        sections[st] = extract_section(symbol, year, st)
        if sections[st]["source"] == "vision_needed":
            vision_needed.append(st)

    return {
        "sections": sections,
        "summary": {
            "total": len(section_types),
            "pdfplumber_success": sum(
                1 for s in sections.values()
                if s["source"] and s["source"].startswith("pdfplumber")
            ),
            "vision_needed": vision_needed,
            "failed": sum(1 for s in sections.values() if not s["success"]),
            "elapsed": round(time.time() - t0, 1),
        },
    }


# ---- 内部辅助函数 ----

def _get_pdf_url(symbol: str, year: int) -> str:
    """获取年报PDF的直链URL（复用extract逻辑中的URL构建）"""
    df = ak.stock_zh_a_disclosure_report_cninfo(
        symbol=symbol,
        category="年报",
        start_date=f"{year}0101",
        end_date=f"{year + 1}1231",
    )
    full = df[df["公告标题"].str.contains("年年度报告$", regex=True)]
    if full.empty:
        raise ValueError(f"未找到{year}年年报")
    row = full.iloc[0]
    ann_id = row["公告链接"].split("announcementId=")[1].split("&")[0]
    return (
        f"http://static.cninfo.com.cn/finalpage/"
        f"{row['公告时间']}/{ann_id}.PDF"
    )


def _download_with_retry(url: str, headers: dict, max_retries: int = 3):
    """带重试的HTTP下载，返回Response对象"""
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=60)
            if resp.status_code == 200:
                return resp
            if attempt < max_retries:
                time.sleep(2)
        except Exception:
            if attempt == max_retries:
                raise
            time.sleep(2)
    raise RuntimeError(f"PDF下载失败: HTTP {resp.status_code}")
