"""
Case-Level 爬虫：下载 EPA Water Reuse 案例和 CWSRF 案例
========================================================
按 WRAgent.pdf 要求：
  - EPA Water Reuse Case Studies → data/epa_reuse/
  - EPA CWSRF Case Studies → data/epa_cwsrf/

运行方法：
    export http_proxy="" && export https_proxy="" && export HTTP_PROXY="" && export HTTPS_PROXY=""
    python3 case_crawler_v2.py
"""

import asyncio
import os
import re
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BROWSER_ARGS = [
    '--no-sandbox', '--disable-setuid-sandbox',
    '--disable-dev-shm-usage', '--no-proxy-server',
]

REUSE_URL = "https://www.epa.gov/waterreuse/case-studies-demonstrate-benefits-water-reuse"
CWSRF_URL = "https://www.epa.gov/cwsrf/clean-water-state-revolving-fund-emerging-contaminants"


async def download_file(page, url, save_path):
    """用浏览器下载文件"""
    try:
        resp = await page.request.get(url)
        if resp.ok:
            body = await resp.body()
            with open(save_path, "wb") as f:
                f.write(body)
            size_kb = len(body) / 1024
            logger.info(f"    ✅ {os.path.basename(save_path)} ({size_kb:.1f} KB)")
            return True
        else:
            logger.warning(f"    ❌ HTTP {resp.status}: {url}")
            return False
    except Exception as e:
        logger.warning(f"    ❌ {e}")
        return False


async def crawl_cwsrf(page, save_dir):
    """
    CWSRF 页面：直接有 PDF 链接，全部下载
    """
    Path(save_dir).mkdir(parents=True, exist_ok=True)
    logger.info(f"\n{'='*60}")
    logger.info(f"爬取 CWSRF 案例 PDF")
    logger.info(f"{'='*60}")

    await page.goto(CWSRF_URL, wait_until="domcontentloaded", timeout=120000)
    await asyncio.sleep(3)

    # 找所有 PDF 链接
    links = await page.query_selector_all("a[href]")
    pdf_urls = []
    for link in links:
        href = await link.get_attribute("href")
        if not href:
            continue
        if href.startswith("/"):
            href = f"https://www.epa.gov{href}"
        if href.endswith(".pdf"):
            text = (await link.text_content()).strip()
            pdf_urls.append({"url": href, "text": text})

    # 去重
    seen = set()
    unique_pdfs = []
    for p in pdf_urls:
        if p["url"] not in seen:
            seen.add(p["url"])
            unique_pdfs.append(p)

    logger.info(f"  找到 {len(unique_pdfs)} 个 PDF")

    count = 0
    for p in unique_pdfs:
        fn = p["url"].split("/")[-1]
        fn = re.sub(r"[^\w\-.]", "_", fn)
        if not fn.endswith(".pdf"):
            fn += ".pdf"
        save_path = os.path.join(save_dir, fn)
        if os.path.exists(save_path):
            logger.info(f"    跳过已存在: {fn}")
            count += 1
            continue
        if await download_file(page, p["url"], save_path):
            count += 1
        await asyncio.sleep(1)

    logger.info(f"  CWSRF 完成: {count} 个文件\n")
    return count


async def crawl_water_reuse(page, save_dir):
    """
    Water Reuse 页面：案例是子页面链接，需要：
    1. 找到所有案例页面链接
    2. 访问每个案例页面，保存 HTML 并下载其中的 PDF
    """
    Path(save_dir).mkdir(parents=True, exist_ok=True)
    logger.info(f"\n{'='*60}")
    logger.info(f"爬取 Water Reuse 案例")
    logger.info(f"{'='*60}")

    await page.goto(REUSE_URL, wait_until="domcontentloaded", timeout=120000)
    await asyncio.sleep(3)

    # 找所有案例链接（子页面 + 直接 PDF）
    links = await page.query_selector_all("a[href]")
    case_urls = []
    direct_pdfs = []

    for link in links:
        href = await link.get_attribute("href")
        if not href:
            continue
        if href.startswith("/"):
            href = f"https://www.epa.gov{href}"

        text = (await link.text_content()).strip()

        # 直接 PDF 链接
        if href.endswith(".pdf"):
            direct_pdfs.append({"url": href, "text": text})
        # 案例子页面
        elif "waterreuse/water-reuse-case-study" in href or "waterreuse/case-study" in href:
            case_urls.append({"url": href, "text": text})

    # 去重
    seen_urls = set()
    unique_cases = []
    for c in case_urls:
        if c["url"] not in seen_urls:
            seen_urls.add(c["url"])
            unique_cases.append(c)

    unique_pdfs = []
    for p in direct_pdfs:
        if p["url"] not in seen_urls:
            seen_urls.add(p["url"])
            unique_pdfs.append(p)

    logger.info(f"  找到 {len(unique_cases)} 个案例子页面, {len(unique_pdfs)} 个直接 PDF")

    count = 0

    # 下载直接 PDF
    for p in unique_pdfs:
        fn = p["url"].split("/")[-1]
        fn = re.sub(r"[^\w\-.]", "_", fn)
        save_path = os.path.join(save_dir, fn)
        if os.path.exists(save_path):
            logger.info(f"    跳过已存在: {fn}")
            count += 1
            continue
        if await download_file(page, p["url"], save_path):
            count += 1
        await asyncio.sleep(1)

    # 访问每个案例子页面
    for case in unique_cases:
        try:
            logger.info(f"\n  案例: {case['text'][:60]}...")
            await page.goto(case["url"], wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(2)

            # 保存页面为 HTML
            slug = case["url"].rstrip("/").split("/")[-1]
            slug = re.sub(r"[^\w\-]", "_", slug)
            html_path = os.path.join(save_dir, f"{slug}.html")
            if not os.path.exists(html_path):
                html_content = await page.content()
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(html_content)
                logger.info(f"    ✅ 保存 HTML: {slug}.html")
                count += 1

            # 查找页面中的 PDF 链接
            sub_links = await page.query_selector_all("a[href$='.pdf']")
            for sl in sub_links:
                href = await sl.get_attribute("href")
                if not href:
                    continue
                if href.startswith("/"):
                    href = f"https://www.epa.gov{href}"
                fn = href.split("/")[-1]
                fn = re.sub(r"[^\w\-.]", "_", fn)
                save_path = os.path.join(save_dir, fn)
                if os.path.exists(save_path):
                    continue
                if await download_file(page, href, save_path):
                    count += 1
                await asyncio.sleep(1)

        except Exception as e:
            logger.warning(f"    ❌ {case['text'][:40]}: {e}")

    logger.info(f"\n  Water Reuse 完成: {count} 个文件")
    return count


async def main():
    from playwright.async_api import async_playwright

    logger.info("=" * 60)
    logger.info("Case-Level 爬虫: EPA Water Reuse + CWSRF")
    logger.info("=" * 60)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=BROWSER_ARGS)
        page = await browser.new_page()

        reuse_count = await crawl_water_reuse(page, "data/epa_reuse")
        cwsrf_count = await crawl_cwsrf(page, "data/epa_cwsrf")

        await browser.close()

    logger.info(f"\n{'='*60}")
    logger.info(f"全部完成！")
    logger.info(f"  Water Reuse: {reuse_count} 个文件 → data/epa_reuse/")
    logger.info(f"  CWSRF: {cwsrf_count} 个文件 → data/epa_cwsrf/")
    logger.info(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
