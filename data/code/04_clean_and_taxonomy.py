"""
数据清理脚本：
1. 清除所有 JSON 中的 HTML 标签，转为纯文本
2. 重新生成 taxonomy.json，修复逗号分割导致的错误同义词

运行方法：
    python3 cleanup.py
"""

import json
import re
import html
from pathlib import Path

DATA_DIR = Path("data/tdb")
TAXONOMY_FILE = Path("data/taxonomy.json")


def strip_html(text):
    """去除 HTML 标签，解码 HTML 实体，整理空白"""
    if not text or text == "N/A":
        return text
    # 解码 HTML 实体 (&nbsp; &ldquo; 等)
    text = html.unescape(text)
    # <p> 和 <br> 替换为换行
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>\s*<p[^>]*>', '\n', text, flags=re.IGNORECASE)
    # 去除所有 HTML 标签
    text = re.sub(r'<[^>]+>', '', text)
    # 整理多余空白和换行
    text = re.sub(r'\r\n', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = text.strip()
    return text


def clean_json_value(obj):
    """递归清理 JSON 中所有字符串值的 HTML 标签"""
    if isinstance(obj, str):
        return strip_html(obj)
    elif isinstance(obj, dict):
        return {k: clean_json_value(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_json_value(item) for item in obj]
    return obj


def clean_all_json_files():
    """遍历所有污染物目录，清理所有 JSON 文件中的 HTML"""
    dirs = sorted([d for d in DATA_DIR.iterdir() if d.is_dir() and d.name != "__pycache__"])
    total_files = 0
    total_cleaned = 0

    for d in dirs:
        # 遍历目录下所有 JSON 文件（包括子目录）
        for json_file in d.rglob("*.json"):
            total_files += 1
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                cleaned = clean_json_value(data)

                # 只有内容变了才写回
                if cleaned != data:
                    json_file.write_text(
                        json.dumps(cleaned, ensure_ascii=False, indent=2),
                        encoding="utf-8"
                    )
                    total_cleaned += 1
            except Exception as e:
                print(f"  ❌ {json_file}: {e}")

    print(f"扫描 {total_files} 个 JSON 文件，清理了 {total_cleaned} 个含 HTML 的文件")


def rebuild_taxonomy():
    """重新生成 taxonomy.json，正确处理同义词分割"""
    list_path = DATA_DIR / "contaminant_list.json"
    if not list_path.exists():
        print("❌ contaminant_list.json 不存在")
        return

    contaminants = json.loads(list_path.read_text(encoding="utf-8"))
    print(f"读取 {len(contaminants)} 个污染物")

    taxonomy = []
    for c in contaminants:
        name = c.get("name", "")
        syns_raw = c.get("synonyms", "")
        if not syns_raw or syns_raw.strip().upper() == "N/A":
            continue

        # 同义词之间用逗号分隔，但要注意：
        # 有些同义词本身包含逗号（如化学名），这里我们从 info.json 读取原始值
        # API 返回的 synonymName 是以 ", " 分隔的
        # 用 ", " (逗号+空格) 而不是单纯的 "," 来分割，减少误切
        for syn in syns_raw.split(", "):
            syn = syn.strip().rstrip(",").strip()
            if not syn:
                continue
            # 过滤掉明显不是同义词的（纯数字、单个字符、和污染物名相同的）
            if syn == name:
                continue
            if len(syn) <= 1 and syn.isdigit():
                continue
            taxonomy.append({
                "Contaminant Name": name,
                "Synonyms": syn
            })

    with open(TAXONOMY_FILE, "w", encoding="utf-8") as f:
        json.dump(taxonomy, f, ensure_ascii=False, indent=2)

    print(f"✅ 生成 {len(taxonomy)} 条同义词映射")
    print(f"\n前5条：")
    for e in taxonomy[:5]:
        print(f"   {e['Synonyms']}  →  {e['Contaminant Name']}")


def main():
    print("=" * 60)
    print("WR-Agent 数据清理")
    print("=" * 60)

    print("\n[1/2] 清理 HTML 标签...")
    clean_all_json_files()

    print("\n[2/2] 重新生成 taxonomy.json...")
    rebuild_taxonomy()

    print("\n✅ 清理完成！")


if __name__ == "__main__":
    main()
