"""
TDB 全量爬虫 v3 (严格按文档要求)
==================================
按照 WRAgent.pdf 最新要求：
  - info.json, description.json
  - treatment/ 文件夹 (overall.json + 各工艺.json)
  - properties/tdb_<X>_properties.json (6字段, 空值=N/A)
  - fatetrans/tdb_<X>_fatetrans.json (6字段, 空值=N/A)
  - ref/tdb_<X>_ref.json (6字段, 空值=N/A, Ref#去重)
  - taxonomy.json

运行方法：
    export http_proxy="" && export https_proxy="" && export HTTP_PROXY="" && export HTTPS_PROXY=""
    python3 tdb_crawler_v3.py --limit 3       # 先测试3个
    python3 tdb_crawler_v3.py                  # 全量爬取
    python3 tdb_crawler_v3.py --start-from "Alachlor"  # 断点续爬

后台运行：
    nohup python3 tdb_crawler_v3.py > crawl_output.log 2>&1 &
    tail -f crawl_output.log
"""

import asyncio
import json
import os
import re
import argparse
import logging
from datetime import datetime
from pathlib import Path

BASE_URL = "https://tdb.epa.gov/tdb"
DATA_DIR = Path("data/tdb")
TAXONOMY_FILE = Path("data/taxonomy.json")
LOG_FILE = Path("data/crawl_log.json")

BROWSER_ARGS = [
    '--no-sandbox', '--disable-setuid-sandbox',
    '--disable-dev-shm-usage', '--no-proxy-server',
]
PAGE_TIMEOUT = 120000
MAX_RETRIES = 3
CRAWL_DELAY = 3

os.makedirs("data", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("data/crawler.log", encoding="utf-8")]
)
logger = logging.getLogger(__name__)


def na(val):
    """空值统一返回 N/A"""
    if val is None:
        return "N/A"
    s = str(val).strip()
    return s if s and s != "-" else "N/A"


def sanitize(name):
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = re.sub(r'\s+', '_', name)
    return name.strip('._')


class CrawlLog:
    def __init__(self):
        self.data = {"completed": [], "failed": [], "start_time": "", "last_update": ""}
        if LOG_FILE.exists():
            try:
                self.data = json.loads(LOG_FILE.read_text(encoding="utf-8"))
            except:
                pass

    def mark_done(self, name):
        if name not in self.data["completed"]:
            self.data["completed"].append(name)
        self.data["last_update"] = datetime.now().isoformat()
        self._save()

    def mark_fail(self, name, err):
        self.data["failed"].append({"name": name, "error": err, "time": datetime.now().isoformat()})
        self._save()

    def is_done(self, name):
        return name in self.data["completed"]

    def _save(self):
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)


class TDBCrawlerV3:
    def __init__(self):
        self.crawl_log = CrawlLog()
        self.taxonomy = []

    async def run(self, limit=None, start_from=None):
        from playwright.async_api import async_playwright

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.crawl_log.data["start_time"] = datetime.now().isoformat()

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True, args=BROWSER_ARGS)

            # ===== Step 1: 获取污染物列表 =====
            logger.info("=" * 60)
            logger.info("Step 1: 获取污染物列表 (通过 API 拦截)")
            logger.info("=" * 60)

            ctx = await browser.new_context()
            page = await ctx.new_page()
            page.set_default_timeout(PAGE_TIMEOUT)
            contaminants = await self._get_list(page)
            await ctx.close()

            if not contaminants:
                logger.error("未获取到污染物列表，终止")
                await browser.close()
                return

            with open(DATA_DIR / "contaminant_list.json", "w", encoding="utf-8") as f:
                json.dump(contaminants, f, ensure_ascii=False, indent=2)
            logger.info(f"共 {len(contaminants)} 个污染物")

            if start_from:
                idx = next((i for i, c in enumerate(contaminants) if c["name"] == start_from), 0)
                contaminants = contaminants[idx:]
            if limit:
                contaminants = contaminants[:limit]

            total = len(contaminants)
            logger.info(f"准备爬取 {total} 个污染物\n")

            # ===== Step 2: 逐个爬取 =====
            for i, cont in enumerate(contaminants, 1):
                name = cont["name"]
                if self.crawl_log.is_done(name):
                    logger.info(f"[{i}/{total}] 跳过已完成: {name}")
                    self._add_taxonomy(cont)
                    continue

                ok = False
                for retry in range(MAX_RETRIES):
                    try:
                        logger.info(f"[{i}/{total}] 爬取: {name} (ID: {cont['id']})")
                        ctx = await browser.new_context()
                        page = await ctx.new_page()
                        page.set_default_timeout(PAGE_TIMEOUT)
                        await self._crawl_one(page, cont)
                        await ctx.close()
                        self.crawl_log.mark_done(name)
                        self._add_taxonomy(cont)
                        ok = True
                        break
                    except Exception as e:
                        logger.warning(f"  重试 {retry+1}/{MAX_RETRIES}: {e}")
                        try: await ctx.close()
                        except: pass
                        if retry == MAX_RETRIES - 1:
                            self.crawl_log.mark_fail(name, str(e))

                await asyncio.sleep(CRAWL_DELAY)

            await browser.close()

            # ===== Step 3: 保存 taxonomy =====
            with open(TAXONOMY_FILE, "w", encoding="utf-8") as f:
                json.dump(self.taxonomy, f, ensure_ascii=False, indent=2)

            done = len(self.crawl_log.data["completed"])
            fail = len(self.crawl_log.data["failed"])
            logger.info("=" * 60)
            logger.info(f"全部完成！成功: {done}  失败: {fail}  Taxonomy: {len(self.taxonomy)} 条")
            logger.info("=" * 60)

    # ------------------------------------------------------------------
    # 获取污染物列表
    # ------------------------------------------------------------------
    async def _get_list(self, page):
        api_data = []

        async def capture(resp):
            if "get-all-contaminants" in resp.url:
                try:
                    body = await resp.json()
                    if isinstance(body, list):
                        api_data.extend(body)
                except: pass

        page.on("response", capture)
        await page.goto(f"{BASE_URL}/findcontaminant", wait_until="networkidle", timeout=PAGE_TIMEOUT)
        await asyncio.sleep(3)

        result = []
        for item in api_data:
            result.append({
                "name": str(item.get("contName", "")).strip(),
                "cas": str(item.get("casNumber", "")).strip(),
                "synonyms": str(item.get("synonymName", "")).strip(),
                "type": str(item.get("contType", "")).strip(),
                "id": str(item.get("contid", "")),
            })
        result.sort(key=lambda x: x["name"].lower())
        return result

    # ------------------------------------------------------------------
    # 爬取单个污染物
    # ------------------------------------------------------------------
    async def _crawl_one(self, page, cont):
        name = cont["name"]
        safe = sanitize(name)
        cid = cont["id"]

        # 创建目录结构
        cdir = DATA_DIR / safe
        tdir = cdir / f"tdb_{safe}_treatment"
        prop_dir = cdir / "properties"
        fate_dir = cdir / "fatetrans"
        ref_dir = cdir / "ref"
        for d in [cdir, tdir, prop_dir, fate_dir, ref_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # 拦截所有 API 响应
        captured = {}

        async def capture(resp):
            url = resp.url
            try:
                ct = resp.headers.get("content-type", "")
                if "json" in ct and resp.status == 200 and "treatability-api" in url:
                    body = await resp.json()
                    # 用 URL 的最后一段作为 key
                    path_part = url.split("treatability-api/")[-1].split("?")[0]
                    captured[path_part] = body
            except: pass

        page.on("response", capture)

        # 打开详情页，等待所有 API 加载完成
        await page.goto(f"{BASE_URL}/contaminant?id={cid}", wait_until="networkidle", timeout=PAGE_TIMEOUT)
        await asyncio.sleep(5)

        logger.info(f"  拦截到 {len(captured)} 个 API: {list(captured.keys())}")

        # ===== 1. info.json =====
        info_raw = self._find_data(captured, ["get-contaminant-overview"])
        if isinstance(info_raw, list) and info_raw:
            info_raw = info_raw[0]
        if not isinstance(info_raw, dict):
            info_raw = {}

        # 调试：打印 overview 的全部 key
        if info_raw:
            logger.info(f"  overview keys: {list(info_raw.keys())}")

        info = {
            "Contaminant Name": name,
            "CAS Number": na(info_raw.get("casNumber", cont["cas"])),
            "DTXSID": na(info_raw.get("dtxsid", "")),
            "Synonyms": na(info_raw.get("synonymName", cont["synonyms"])),
            "Contaminant Type": na(info_raw.get("contType", cont["type"])),
        }
        self._save_json(cdir / f"tdb_{safe}_info.json", info)

        # ===== 2. description.json =====
        desc = na(info_raw.get("contDesc", ""))
        self._save_json(cdir / f"tdb_{safe}_description.json", {
            "Contaminant Name": name,
            "Description": desc,
        })
        logger.info(f"  ✅ info + description")

        # ===== 3. treatment/ =====
        # overall summary 可能在 overview API 中
        overall_text = na(info_raw.get("treatmentSummary", ""))

        # 也检查 treatments API
        treatments_raw = self._find_data(captured, ["get-contaminant-treatments"])

        # 调试：打印数据结构帮助理解
        if treatments_raw is not None:
            if isinstance(treatments_raw, list):
                logger.info(f"  treatments 数据: list, {len(treatments_raw)} 条")
                if treatments_raw:
                    sample = treatments_raw[0]
                    if isinstance(sample, dict):
                        logger.info(f"  第一条 keys: {list(sample.keys())}")
            elif isinstance(treatments_raw, dict):
                logger.info(f"  treatments 数据: dict, keys={list(treatments_raw.keys())}")
        else:
            logger.warning(f"  ⚠️ 未找到 treatments 数据")

        # 提取工艺详情列表
        treatment_items = []

        if isinstance(treatments_raw, dict):
            # 可能是 {treatmentSummary: "...", treatments: [...]} 结构
            if not overall_text or overall_text == "N/A":
                overall_text = na(treatments_raw.get("treatmentSummary", ""))
            treatment_items = treatments_raw.get("treatments", [])
            if not treatment_items:
                treatment_items = treatments_raw.get("treatmentDescriptions", [])
        elif isinstance(treatments_raw, list):
            for item in treatments_raw:
                if not isinstance(item, dict):
                    continue
                if "treatmentSummary" in item and (not overall_text or overall_text == "N/A"):
                    overall_text = na(item["treatmentSummary"])
                if "treatmentProcessName" in item:
                    treatment_items.append(item)
                elif "summaryDesc" in item or "fullDesc" in item:
                    treatment_items.append(item)

        self._save_json(tdir / f"treatment_{safe}_overall.json", {
            "Contaminant Name": name,
            "Overall": overall_text if overall_text != "N/A" else "",
        })

        # 各工艺详情
        func_count = 0
        for td in treatment_items:
            if not isinstance(td, dict):
                continue
            func_name = td.get("treatmentProcessName", "") or td.get("processName", "")
            if not func_name:
                continue
            details = na(td.get("fullDesc", "") or td.get("summaryDesc", "") or td.get("description", ""))
            sfn = re.sub(r"[^\w]", "_", func_name)
            self._save_json(tdir / f"treatment_{safe}_{sfn}.json", {
                "Contaminant Name": name,
                "Function": func_name,
                "Details": details,
            })
            func_count += 1
        logger.info(f"  ✅ treatment: overall + {func_count} 个工艺")

        # ===== 4. properties/ → JSON (6字段) =====
        props_raw = self._find_data(captured, ["get-contaminant-properties"])
        if isinstance(props_raw, list):
            props_json = []
            for p in props_raw:
                if not isinstance(p, dict): continue
                props_json.append({
                    "Contaminant Name": name,
                    "Parameter": na(p.get("parameter")),
                    "Value": na(p.get("value")),
                    "Units": na(p.get("units")),
                    "Condition": na(p.get("condition")),
                    "Ref#": na(p.get("refNumber")),
                })
            self._save_json(prop_dir / f"tdb_{safe}_properties.json", props_json)
            logger.info(f"  ✅ properties.json ({len(props_json)} 条)")
        else:
            self._save_json(prop_dir / f"tdb_{safe}_properties.json", [])
            logger.info(f"  ⚠️ properties: 无数据")

        # ===== 5. fatetrans/ → JSON (6字段) =====
        fate_raw = self._find_data(captured, ["get-contaminant-fate-and-transport"])
        if isinstance(fate_raw, list):
            fate_json = []
            for p in fate_raw:
                if not isinstance(p, dict): continue
                fate_json.append({
                    "Contaminant Name": name,
                    "Parameter": na(p.get("parameter")),
                    "Value": na(p.get("value")),
                    "Units": na(p.get("units")),
                    "Condition": na(p.get("condition")),
                    "Ref#": na(p.get("refNumber")),
                })
            self._save_json(fate_dir / f"tdb_{safe}_fatetrans.json", fate_json)
            logger.info(f"  ✅ fatetrans.json ({len(fate_json)} 条)")
        else:
            self._save_json(fate_dir / f"tdb_{safe}_fatetrans.json", [])
            logger.info(f"  ⚠️ fatetrans: 无数据")

        # ===== 6. ref/ → JSON (6字段, Ref#去重) =====
        refs_raw = self._find_data(captured, ["get-contaminant-references"])
        if isinstance(refs_raw, list):
            seen_refs = set()
            ref_json = []
            for r in refs_raw:
                if not isinstance(r, dict): continue
                ref_num = na(r.get("refNumber"))
                if ref_num in seen_refs:
                    continue  # Ref# 去重
                seen_refs.add(ref_num)
                ref_json.append({
                    "Contaminant Name": name,
                    "Ref#": ref_num,
                    "Treatment Process": na(r.get("treatmentProcessName")),
                    "Author": na(r.get("author")),
                    "Year": na(r.get("year")),
                    "Title": na(r.get("title")),
                    "Source": na(r.get("source")),
                })
            self._save_json(ref_dir / f"tdb_{safe}_ref.json", ref_json)
            logger.info(f"  ✅ ref.json ({len(ref_json)} 条, 去重后)")
        else:
            self._save_json(ref_dir / f"tdb_{safe}_ref.json", [])
            logger.info(f"  ⚠️ ref: 无数据")

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    def _find_data(self, captured, keys):
        """在 captured dict 中模糊匹配 key"""
        # 先精确匹配
        for k in keys:
            if k in captured:
                return captured[k]
        # 再模糊匹配
        for k in keys:
            for ck in captured:
                if k in ck.lower():
                    return captured[ck]
        return None

    def _save_json(self, path, data):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _add_taxonomy(self, cont):
        syns = cont.get("synonyms", "")
        if not syns or syns.strip().upper() == "N/A":
            return
        for s in syns.split(","):
            s = s.strip()
            if s:
                self.taxonomy.append({"Contaminant Name": cont["name"], "Synonyms": s})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TDB 全量爬虫 v3")
    parser.add_argument("--limit", type=int, help="只爬取前N个")
    parser.add_argument("--start-from", type=str, help="从指定污染物开始")
    args = parser.parse_args()
    asyncio.run(TDBCrawlerV3().run(limit=args.limit, start_from=args.start_from))
