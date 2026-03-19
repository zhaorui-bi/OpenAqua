"""
Step 1 (Vue提取版): 从 TDB 页面的 Vue 实例直接提取全部数据
=============================================================
原理：TDB 网站用 Vue.js 加载数据，所有污染物数据存在 Vue 实例的
      data 属性里。我们用 Playwright 打开页面，等 Vue 渲染完，
      然后用 JS 从 Vue 实例里把数据全部取出来。

运行方法：
    export http_proxy="" && export https_proxy="" && export HTTP_PROXY="" && export HTTPS_PROXY=""
    python3 step1_get_list_vue.py
"""

import asyncio
import json
import os
import re

BROWSER_ARGS = [
    '--no-sandbox', '--disable-setuid-sandbox',
    '--disable-dev-shm-usage', '--no-proxy-server',
]


async def main():
    from playwright.async_api import async_playwright
    os.makedirs("data/tdb", exist_ok=True)

    print("=" * 60)
    print("Step 1 (Vue提取版): 获取 TDB 污染物完整列表")
    print("=" * 60)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=BROWSER_ARGS)

        # 监听所有网络请求，捕获 API 响应
        context = await browser.new_context()
        page = await context.new_page()

        # 用来存储拦截到的 API 数据
        api_data = []

        # 方法1：拦截网络请求，捕获 API 返回的 JSON
        async def handle_response(response):
            url = response.url
            if "contaminant" in url.lower() and "api" in url.lower():
                try:
                    body = await response.json()
                    if isinstance(body, list) and len(body) > 10:
                        api_data.clear()
                        api_data.extend(body)
                        print(f"  🎯 拦截到 API 响应: {url}")
                        print(f"     包含 {len(body)} 条数据")
                except:
                    pass
            # 也尝试捕获其他可能的数据接口
            elif "get-all" in url.lower() or "findcontaminant" in url.lower():
                try:
                    ct = response.headers.get("content-type", "")
                    if "json" in ct:
                        body = await response.json()
                        if isinstance(body, list) and len(body) > 10:
                            api_data.clear()
                            api_data.extend(body)
                            print(f"  🎯 拦截到数据响应: {url}")
                            print(f"     包含 {len(body)} 条数据")
                except:
                    pass

        page.on("response", handle_response)

        # ===== 打开页面 =====
        print("\n[1/4] 打开 TDB 页面...")
        await page.goto(
            "https://tdb.epa.gov/tdb/findcontaminant",
            wait_until="networkidle",
            timeout=120000
        )
        await asyncio.sleep(5)
        print("  ✅ 页面加载完成")

        # ===== 检查拦截到的 API 数据 =====
        if api_data:
            print(f"\n[2/4] 已通过网络拦截获取到 {len(api_data)} 条数据！")
            contaminants = _convert_api_data(api_data)
        else:
            print("\n[2/4] 未拦截到 API，尝试从页面提取...")

            # 方法2：从 Vue 实例提取
            print("  尝试从 Vue 实例提取...")
            vue_data = await page.evaluate("""
                () => {
                    // 方法A：遍历所有元素找 Vue 实例
                    const allElements = document.querySelectorAll('*');
                    for (const el of allElements) {
                        // Vue 2.x
                        if (el.__vue__) {
                            const vm = el.__vue__;
                            // 递归查找包含 contaminant 数据的属性
                            function findData(obj, depth) {
                                if (depth > 5) return null;
                                if (!obj || typeof obj !== 'object') return null;
                                
                                for (const key of Object.keys(obj)) {
                                    const val = obj[key];
                                    if (Array.isArray(val) && val.length > 50) {
                                        if (val[0] && (val[0].contName || val[0].contid || val[0].casNumber)) {
                                            return val;
                                        }
                                    }
                                    if (typeof val === 'object' && val !== null && !Array.isArray(val)) {
                                        const found = findData(val, depth + 1);
                                        if (found) return found;
                                    }
                                }
                                return null;
                            }
                            
                            // 检查 $data
                            let result = findData(vm.$data, 0);
                            if (result) return { source: 'vue_data', data: result };
                            
                            // 检查 $root
                            result = findData(vm.$root.$data, 0);
                            if (result) return { source: 'vue_root', data: result };
                            
                            // 检查所有计算属性和方法返回的数据
                            if (vm._computedWatchers) {
                                for (const key of Object.keys(vm._computedWatchers)) {
                                    const val = vm[key];
                                    if (Array.isArray(val) && val.length > 50 && val[0] && val[0].contName) {
                                        return { source: 'vue_computed_' + key, data: val };
                                    }
                                }
                            }
                        }
                    }
                    
                    // 方法B：检查全局变量
                    for (const key of Object.keys(window)) {
                        try {
                            const val = window[key];
                            if (Array.isArray(val) && val.length > 50 && val[0] && val[0].contName) {
                                return { source: 'window_' + key, data: val };
                            }
                        } catch(e) {}
                    }
                    
                    return null;
                }
            """)

            if vue_data and vue_data.get("data"):
                print(f"  ✅ 从 {vue_data['source']} 提取到 {len(vue_data['data'])} 条数据！")
                contaminants = _convert_api_data(vue_data["data"])
            else:
                print("  Vue 实例未找到数据，尝试方法3...")

                # 方法3：用 CSRF token 调用 API
                print("\n[3/4] 尝试带 CSRF token 调用 API...")
                csrf_data = await page.evaluate("""
                    async () => {
                        // 从 meta 标签获取 CSRF token
                        const csrfMeta = document.querySelector('meta[name="_csrf"]');
                        const csrfHeaderMeta = document.querySelector('meta[name="_csrf_header"]');
                        const token = csrfMeta ? csrfMeta.getAttribute('content') : '';
                        const headerName = csrfHeaderMeta ? csrfHeaderMeta.getAttribute('content') : 'X-CSRF-TOKEN';
                        
                        // 尝试多个可能的 API 路径
                        const urls = [
                            '/tdb/treatability-api/get-all-contaminants',
                            '/tdb/api/get-all-contaminants',
                            '/tdb/api/contaminants',
                            '/tdb/api/findcontaminant',
                            '/tdb/treatability-api/contaminants',
                            '/tdb/treatability-api/findcontaminant',
                        ];
                        
                        for (const url of urls) {
                            try {
                                const headers = {
                                    'Accept': 'application/json',
                                    'X-Requested-With': 'XMLHttpRequest',
                                };
                                if (token) headers[headerName] = token;
                                
                                const resp = await fetch(url, {
                                    method: 'GET',
                                    credentials: 'same-origin',
                                    headers: headers
                                });
                                
                                if (resp.ok) {
                                    const ct = resp.headers.get('content-type') || '';
                                    if (ct.includes('json')) {
                                        const data = await resp.json();
                                        if (Array.isArray(data) && data.length > 10) {
                                            return { url: url, data: data };
                                        }
                                    }
                                }
                            } catch(e) {}
                        }
                        return null;
                    }
                """)

                if csrf_data and csrf_data.get("data"):
                    print(f"  ✅ API 成功: {csrf_data['url']}, {len(csrf_data['data'])} 条数据")
                    contaminants = _convert_api_data(csrf_data["data"])
                else:
                    print("  API 也失败了，使用方法4: 表格提取...")

                    # 方法4：最后的备用——从表格提取
                    contaminants = await _extract_from_table(page)

        await browser.close()

        if not contaminants:
            print("\n❌ 所有方法都未获取到数据")
            return

        # ===== 保存 =====
        contaminants.sort(key=lambda x: x["name"].lower())

        out_path = "data/tdb/contaminant_list.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(contaminants, f, ensure_ascii=False, indent=2)

        has_id = sum(1 for c in contaminants if c["id"])
        print(f"\n{'=' * 60}")
        print(f"✅ 完成！共 {len(contaminants)} 个污染物")
        print(f"   其中 {has_id} 个有 ID")
        print(f"   保存到: {out_path}")
        print(f"{'=' * 60}")

        print("\n前10条：")
        for c in contaminants[:10]:
            print(f"   {c['name']:30s}  ID={c['id']:6s}  CAS={c['cas']}")

        print(f"\n后5条：")
        for c in contaminants[-5:]:
            print(f"   {c['name']:30s}  ID={c['id']:6s}  CAS={c['cas']}")


def _convert_api_data(items):
    """把 API 返回的数据转换成我们需要的格式"""
    contaminants = []
    seen = set()
    for item in items:
        # 兼容不同的字段名
        name = str(item.get("contName", "") or item.get("name", "") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        contaminants.append({
            "name": name,
            "cas": str(item.get("casNumber", "") or item.get("cas", "") or "").strip(),
            "synonyms": str(item.get("synonymName", "") or item.get("synonyms", "") or item.get("synonymDisplay", "") or "").strip(),
            "type": str(item.get("contType", "") or item.get("type", "") or "").strip(),
            "id": str(item.get("contid", "") or item.get("id", "") or ""),
        })
    return contaminants


async def _extract_from_table(page):
    """从页面表格提取，遍历所有字母"""
    print("\n  从表格提取（遍历字母索引）...")
    all_contaminants = []
    seen = set()

    chars = ["All"] + [str(i) for i in range(10)] + [chr(i) for i in range(ord('A'), ord('Z') + 1)]

    for ch in chars:
        try:
            await page.goto("https://tdb.epa.gov/tdb/findcontaminant",
                          wait_until="domcontentloaded", timeout=120000)
            await page.wait_for_selector("table tbody tr", timeout=60000)
            await asyncio.sleep(2)

            link = await page.query_selector(f'a:text-is("{ch}")')
            if not link:
                continue
            await link.click()
            await asyncio.sleep(4)

            rows = await page.query_selector_all("table tbody tr")
            count_before = len(all_contaminants)

            for row in rows:
                cells = await row.query_selector_all("td")
                if len(cells) < 4:
                    continue
                name = (await cells[0].text_content()).strip()
                if not name or name in seen:
                    continue
                seen.add(name)

                link_el = await cells[0].query_selector("a")
                cont_id = ""
                if link_el:
                    href = await link_el.get_attribute("href") or ""
                    m = re.search(r'id=(\d+)', href)
                    if m:
                        cont_id = m.group(1)

                all_contaminants.append({
                    "name": name,
                    "cas": (await cells[1].text_content()).strip(),
                    "synonyms": (await cells[2].text_content()).strip(),
                    "type": (await cells[3].text_content()).strip(),
                    "id": cont_id,
                })

            added = len(all_contaminants) - count_before
            if added > 0:
                print(f"    [{ch:3s}] +{added:3d} 条, 累计 {len(all_contaminants)}")

        except Exception as e:
            print(f"    [{ch:3s}] 失败: {e}")

    return all_contaminants


if __name__ == "__main__":
    asyncio.run(main())
