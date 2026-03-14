"""
数据质量检查脚本 v2 (适配新目录结构)
=====================================
按照 WRAgent.pdf 要求检查：
  - tdb_<X>_info.json (5 字段)
  - tdb_<X>_description.json (2 字段)
  - tdb_<X>_treatment/ (overall.json + 各工艺.json)
  - properties/tdb_<X>_properties.json (JSON, 6字段)
  - fatetrans/tdb_<X>_fatetrans.json (JSON, 6字段)
  - ref/tdb_<X>_ref.json (JSON, 6字段)

运行方法：
    python3 data_checker_v2.py
    python3 data_checker_v2.py --verbose
"""

import json
import argparse
from pathlib import Path

DATA_DIR = Path("data/tdb")
TAXONOMY_FILE = Path("data/taxonomy.json")

INFO_FIELDS = ["Contaminant Name", "CAS Number", "DTXSID", "Synonyms", "Contaminant Type"]
DESC_FIELDS = ["Contaminant Name", "Description"]
OVERALL_FIELDS = ["Contaminant Name", "Overall"]
TREATMENT_FIELDS = ["Contaminant Name", "Function", "Details"]
PROP_FIELDS = ["Contaminant Name", "Parameter", "Value", "Units", "Condition", "Ref#"]
FATE_FIELDS = ["Contaminant Name", "Parameter", "Value", "Units", "Condition", "Ref#"]
REF_FIELDS = ["Contaminant Name", "Ref#", "Treatment Process", "Author", "Year", "Title", "Source"]


class DataCheckerV2:
    def __init__(self, verbose=False):
        self.verbose = verbose
        self.issues = []
        self.stats = {
            "total": 0, "complete": 0,
            "missing_info": 0, "missing_desc": 0,
            "missing_treatment": 0, "missing_props": 0,
            "missing_fate": 0, "missing_ref": 0,
            "bad_json": 0, "empty_fields": 0,
            "total_treatments": 0, "total_props": 0,
            "total_fate": 0, "total_refs": 0,
        }

    def log(self, level, msg):
        self.issues.append({"level": level, "msg": msg})
        if self.verbose or level == "ERROR":
            icon = {"ERROR": "❌", "WARN": "⚠️", "INFO": "✅"}.get(level, "")
            print(f"  {icon} {msg}")

    def check_json_file(self, path, fields, label):
        """检查 JSON 文件存在性和字段完整性"""
        if not path.exists():
            self.log("ERROR", f"缺失: {label}")
            return False, None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            self.log("ERROR", f"JSON 损坏: {label}")
            self.stats["bad_json"] += 1
            return False, None

        # 如果是 dict，检查字段
        if isinstance(data, dict):
            for f in fields:
                val = data.get(f, "")
                if not str(val).strip() or str(val).strip() == "N/A":
                    if f not in ["DTXSID", "Synonyms"]:  # 这些可以为空
                        self.log("WARN", f"字段'{f}'为空: {label}")
                        self.stats["empty_fields"] += 1
        # 如果是 list，检查第一条的字段
        elif isinstance(data, list):
            if len(data) > 0 and isinstance(data[0], dict):
                for f in fields:
                    if f not in data[0]:
                        self.log("WARN", f"缺少字段'{f}': {label}")
                        self.stats["empty_fields"] += 1

        return True, data

    def run(self):
        print("=" * 60)
        print("WR-Agent 数据质检 v2 (适配新目录结构)")
        print("=" * 60)

        if not DATA_DIR.exists():
            print("\n❌ data/tdb/ 目录不存在")
            return

        dirs = sorted([d for d in DATA_DIR.iterdir()
                       if d.is_dir() and d.name != "__pycache__"])
        if not dirs:
            print("\n❌ 没有数据")
            return

        print(f"\n发现 {len(dirs)} 个污染物目录\n")

        for d in dirs:
            safe = d.name
            self.stats["total"] += 1
            if self.verbose:
                print(f"\n检查: {safe}")

            ok = True

            # 1. info.json
            found, _ = self.check_json_file(
                d / f"tdb_{safe}_info.json", INFO_FIELDS, f"{safe}/info.json")
            if not found:
                self.stats["missing_info"] += 1
                ok = False

            # 2. description.json
            found, _ = self.check_json_file(
                d / f"tdb_{safe}_description.json", DESC_FIELDS, f"{safe}/description.json")
            if not found:
                self.stats["missing_desc"] += 1
                ok = False

            # 3. treatment/ 目录
            tdir = d / f"tdb_{safe}_treatment"
            if tdir.exists():
                # overall.json
                found, _ = self.check_json_file(
                    tdir / f"treatment_{safe}_overall.json", OVERALL_FIELDS,
                    f"{safe}/treatment/overall.json")
                if not found:
                    self.stats["missing_treatment"] += 1
                    ok = False

                # 各工艺 json
                treatment_files = [f for f in tdir.iterdir()
                                   if f.name.endswith(".json") and "overall" not in f.name]
                self.stats["total_treatments"] += len(treatment_files)
                for tf in treatment_files:
                    self.check_json_file(tf, TREATMENT_FIELDS, f"{safe}/treatment/{tf.name}")
            else:
                self.log("ERROR", f"treatment 目录缺失: {safe}")
                self.stats["missing_treatment"] += 1
                ok = False

            # 4. properties/ → JSON
            prop_file = d / "properties" / f"tdb_{safe}_properties.json"
            found, pdata = self.check_json_file(prop_file, PROP_FIELDS, f"{safe}/properties.json")
            if not found:
                self.stats["missing_props"] += 1
            elif isinstance(pdata, list):
                self.stats["total_props"] += len(pdata)

            # 5. fatetrans/ → JSON
            fate_file = d / "fatetrans" / f"tdb_{safe}_fatetrans.json"
            found, fdata = self.check_json_file(fate_file, FATE_FIELDS, f"{safe}/fatetrans.json")
            if not found:
                self.stats["missing_fate"] += 1
            elif isinstance(fdata, list):
                self.stats["total_fate"] += len(fdata)

            # 6. ref/ → JSON
            ref_file = d / "ref" / f"tdb_{safe}_ref.json"
            found, rdata = self.check_json_file(ref_file, REF_FIELDS, f"{safe}/ref.json")
            if not found:
                self.stats["missing_ref"] += 1
            elif isinstance(rdata, list):
                self.stats["total_refs"] += len(rdata)

            if ok:
                self.stats["complete"] += 1

        # taxonomy
        if TAXONOMY_FILE.exists():
            tax = json.loads(TAXONOMY_FILE.read_text(encoding="utf-8"))
            print(f"\ntaxonomy.json: {len(tax)} 条同义词映射")
        else:
            print("\n⚠️ taxonomy.json 不存在")

        # 报告
        s = self.stats
        print(f"\n{'=' * 60}")
        print(f"数据质检报告")
        print(f"{'=' * 60}")
        print(f"  污染物总数:       {s['total']}")
        print(f"  完整(全部文件齐): {s['complete']} ✅")
        print(f"  缺 info.json:     {s['missing_info']}")
        print(f"  缺 description:   {s['missing_desc']}")
        print(f"  缺 treatment:     {s['missing_treatment']}")
        print(f"  缺 properties:    {s['missing_props']}")
        print(f"  缺 fatetrans:     {s['missing_fate']}")
        print(f"  缺 ref:           {s['missing_ref']}")
        print(f"  JSON 错误:        {s['bad_json']}")
        print(f"  空字段:           {s['empty_fields']}")
        print(f"{'=' * 60}")
        print(f"  工艺详情总数:     {s['total_treatments']}")
        print(f"  properties 总条数: {s['total_props']}")
        print(f"  fatetrans 总条数:  {s['total_fate']}")
        print(f"  references 总条数: {s['total_refs']}")
        if s["total"]:
            print(f"  完整率:           {s['complete']/s['total']*100:.1f}%")
        print(f"{'=' * 60}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--verbose", "-v", action="store_true")
    DataCheckerV2(p.parse_args().verbose).run()
