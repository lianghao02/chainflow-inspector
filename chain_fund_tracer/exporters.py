from __future__ import annotations
import csv
import hashlib
import json
import re
import tempfile
import zipfile
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path
from .branding import PRODUCT_NAME, PRODUCT_SUBTITLE
from .models import AnalysisResult, TraceStep
from .explanations import explain_step, plain_summary
from .svg_exporter import export_svg
def export_text(result: AnalysisResult, path: str) -> None:
    lines = [f"{PRODUCT_NAME}查核紀錄", PRODUCT_SUBTITLE, "="*36, f"查詢輸入：{result.query}", f"網路：{result.network}"]
    if result.time_filter and result.time_filter.get("cutoff_text"):
        lines.append(f"歷史時間錨定：{result.time_filter.get('cutoff_text')}（截止區塊：{result.time_filter.get('end_block')}）")
    if getattr(result, "csv_index", None) and result.csv_index.get("file_name"):
        lines.append(f"歷史 CSV 索引：{result.csv_index.get('file_name')}（SHA-256：{result.csv_index.get('sha256')}）")
    lines.extend(["", "摘要：", *[f"- {x}" for x in result.summary], "", "關聯追蹤（非自然人身分認定）："])
    lines.insert(7 if result.time_filter and result.time_filter.get("cutoff_text") else 6, plain_summary(result.steps))
    for step in result.steps:
        evidence = "｜".join(filter(None, [step.chain, f"區塊 {step.block_number}" if step.block_number else "", f"Log {step.log_index}" if step.log_index else ""]))
        lines.extend([f"[{step.direction} 第 {step.hop} 跳] {step.tx_hash}", f"  時間：{step.timestamp or '未取得'}｜Token／金額：{step.token}／{step.amount or '未取得'}", f"  From：{step.from_address} → To：{step.to_address}", f"  類別：{step.classification} {step.label}｜標籤來源：{step.label_source}｜信心：{step.confidence}｜判定：{step.relation}", f"  證據：{evidence or '未取得'}｜路徑：{step.path_role}｜事件：{step.event_role}"])
        lines.extend([f"  Token 合約：{step.token_contract or '未取得'}", f"  資料依據：{step.evidence_source or '舊紀錄未註記，待核對'}", f"  Relay Request：{step.relay_request_id or '未取得'}｜精確配對：{step.pair_verified}", f"  Explorer：{step.explorer_url or '未取得'}", f"  備註：{step.notes}", explain_step(step).text(), ""])
        if step.deposit_info:
            lines.append("合約結構探測：" + json.dumps(step.deposit_info, ensure_ascii=False))
        if step.trade_info:
            lines.append("投注交易明細：" + json.dumps(step.trade_info, ensure_ascii=False))
    lines.extend(["", "注意事項：", *[f"- {x}" for x in result.warnings], "", "資料來源：", *[f"- {x}" for x in result.sources]])
    Path(path).write_text("\n".join(lines), encoding="utf-8")
def export_csv(result: AnalysisResult, path: str) -> None:
    time_filter = getattr(result, "time_filter", {}) or {}
    cutoff_str = time_filter.get("cutoff_text", "")
    end_block_str = str(time_filter.get("end_block", "")) if time_filter.get("end_block") else ""
    names = [field.name for field in fields(TraceStep)] + ["explanation", "time_filter_cutoff", "time_filter_block"]
    with Path(path).open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=names)
        writer.writeheader()
        for step in result.steps:
            row = step.to_dict()
            row["deposit_info"] = json.dumps(row["deposit_info"], ensure_ascii=False)
            row["trade_info"] = json.dumps(row.get("trade_info", {}), ensure_ascii=False)
            row["explanation"] = explain_step(step).text()
            row["time_filter_cutoff"] = cutoff_str
            row["time_filter_block"] = end_block_str
            # 不信任外部標籤；避免試算表將來源文字解讀為公式。
            for key, value in row.items():
                if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                    row[key] = "'" + value
            writer.writerow(row)


def export_evidence_package(result: AnalysisResult, path: str) -> None:
    """匯出可重現查核的 ZIP；SHA-256 是完整性清冊，不是數位簽章。"""
    destination = Path(path)
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        export_text(result, str(root / "analysis.txt"))
        export_csv(result, str(root / "steps.csv"))
        export_svg(result, str(root / "flow_graph.svg"))
        evidence_dir = root / "evidence"
        evidence_dir.mkdir()
        for index, record in enumerate(result.evidence_records, start=1):
            safe_name = re.sub(r"[^0-9A-Za-z._-]+", "_", str(record.get("name") or "record")).strip("_")
            evidence_path = evidence_dir / f"{index:03d}_{safe_name or 'record'}.json"
            evidence_path.write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        files = sorted(item for item in root.rglob("*") if item.is_file())
        manifest = {
            "format": "chain-fund-tracer evidence package v1",
            "product": PRODUCT_NAME,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "query": result.query,
            "time_filter": result.time_filter or {},
            "csv_index": getattr(result, "csv_index", {}) or {},
            "notice": "本清冊的 SHA-256 用於檢查匯出後檔案完整性，不是數位簽章或自然人身分認定。",
            "files": [
                {
                    "path": item.relative_to(root).as_posix(),
                    "sha256": hashlib.sha256(item.read_bytes()).hexdigest(),
                    "bytes": item.stat().st_size,
                }
                for item in files
            ],
        }
        (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(value for value in root.rglob("*") if value.is_file()):
                archive.write(item, item.relative_to(root).as_posix())
