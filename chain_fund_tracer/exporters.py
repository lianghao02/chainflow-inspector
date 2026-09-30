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
    status_labels = {"complete": "完整", "partial": "部分完成", "failed": "失敗"}
    lines.append(f"分析狀態：{status_labels.get(result.analysis_status, result.analysis_status)}")
    if result.incomplete_tracks:
        lines.append(f"未完成核心資產軌道：{'、'.join(result.incomplete_tracks)}")
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
    names = [field.name for field in fields(TraceStep)] + [
        "explanation", "time_filter_cutoff", "time_filter_block", "analysis_status", "incomplete_tracks"
    ]
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
            row["analysis_status"] = result.analysis_status
            row["incomplete_tracks"] = "、".join(result.incomplete_tracks)
            # 不信任外部標籤；避免試算表將來源文字解讀為公式。
            for key, value in row.items():
                if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                    row[key] = "'" + value
            writer.writerow(row)


def export_subpoena_csv(result: AnalysisResult, path: str) -> None:
    """匯出法證函調候選清單 CSV，供檢警調等辦案人員依案發金流發文向交易所或 VASP 調取資料。"""
    headers = [
        "service_provider",
        "service_type",
        "association_level",
        "chain",
        "from_address",
        "to_address",
        "tx_hash",
        "datetime_tw",
        "asset",
        "amount",
        "label_basis",
        "inquiry_value",
        "limitations",
    ]
    with Path(path).open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=headers)
        writer.writeheader()
        for cand in getattr(result, "subpoena_candidates", []):
            row = cand.to_dict() if hasattr(cand, "to_dict") else dict(cand)
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
        if getattr(result, "subpoena_candidates", None):
            export_subpoena_csv(result, str(root / "subpoena_candidates.csv"))
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
            "analysis_status": result.analysis_status,
            "incomplete_tracks": list(result.incomplete_tracks),
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


def export_agent_bundle(result: AnalysisResult, path: str) -> None:
    """匯出供 Antigravity / Codex / ChatGPT 等 Agent 進行鏈上資金分析的標準資料包。
    包含 README.txt, PROMPT.txt, summary.json, transactions.json, token_transfers.json,
    internal_transactions.json, traces_and_logs.json, labels.json, contracts.json, diagnostic.log。
    """
    destination = Path(path)
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)

        # 1. 整理基本中繼資料與可用性
        availabilities = dict(getattr(result, "availabilities", {}))
        tx_avail = availabilities.get("transactions")
        tr_avail = availabilities.get("token_transfers")
        itx_avail = availabilities.get("internal_transactions")
        log_avail = availabilities.get("logs")

        tx_items = list(result.transactions)
        # 地址採集以完整 FlowEvent 為主；交易查詢仍支援既有 Transfer 模型。
        transfer_events = [e for e in result.flow_events if e.event_type == "token_transfer"]
        tr_items = [e.to_dict() for e in transfer_events] if transfer_events else [t.to_dict() for t in result.transfers]
        itx_items = list(getattr(result, "internal_transactions", []))
        log_items = list(getattr(result, "contract_logs", []))

        # 2. 產出 labels.json 與 contracts.json
        labels_map: dict[str, Any] = {}
        contracts_map: dict[str, Any] = {}
        for step in result.steps:
            if step.label or step.classification:
                labels_map[step.address.lower()] = {
                    "label": step.label,
                    "classification": step.classification,
                    "label_source": step.label_source,
                    "confidence": step.confidence,
                }
            if step.token_contract:
                contracts_map[step.token_contract.lower()] = {
                    "symbol": step.token,
                    "type": "ERC-20",
                }

        # 3. 產出 summary.json
        inbound_steps = [s.to_dict() for s in result.steps if s.path_role == "入金"]
        outflow_steps = [s.to_dict() for s in result.steps if s.path_role == "出金"]
        summary_data = {
            "target_address": result.query,
            "network": result.network,
            "chain_id": 137 if result.network.lower() == "polygon" else 0,
            "export_time_utc": datetime.now(timezone.utc).isoformat(),
            "analysis_status": result.analysis_status,
            "time_filter": result.time_filter or {},
            "csv_index": getattr(result, "csv_index", {}) or {},
            "data_availability": {
                "transactions": tx_avail.to_dict() if tx_avail else {
                    "available": bool(tx_items), "status": "Success" if tx_items else "UnsupportedProvider",
                    "record_count": len(tx_items),
                },
                "token_transfers": tr_avail.to_dict() if tr_avail else {
                    "available": bool(tr_items), "status": "Success" if tr_items else "UnsupportedProvider",
                    "record_count": len(tr_items),
                },
                "internal_transactions": itx_avail.to_dict() if itx_avail else {
                    "available": False, "status": "UnsupportedProvider",
                    "record_count": len(itx_items), "reason": "未配置專屬 Internal Tx 索引或公共端點未回傳",
                },
                "contract_logs": log_avail.to_dict() if log_avail else {
                    "available": bool(log_items), "status": "Success" if log_items else "UnsupportedProvider",
                    "record_count": len(log_items),
                },
            },
            "counts": {
                "transactions_count": len(tx_items),
                "token_transfers_count": len(tr_items),
                "internal_transactions_count": len(itx_items),
                "flow_events_count": len(getattr(result, "flow_events", [])),
                "direct_inbound_count": len(inbound_steps),
                "direct_outflow_count": len(outflow_steps),
                "subpoena_candidates_count": len(result.subpoena_candidates),
            },
            "subpoena_candidates": [c.to_dict() for c in result.subpoena_candidates],
            "suspect_profile_candidate": getattr(result, "suspect_profile", {}),
            "incomplete_tracks": list(result.incomplete_tracks),
            "warnings": list(result.warnings),
            "sources": list(result.sources),
        }
        (root / "summary.json").write_text(json.dumps(summary_data, ensure_ascii=False, indent=2), encoding="utf-8")

        # 4. 產出 transactions.json
        tx_data = {
            "available": summary_data["data_availability"]["transactions"]["available"],
            "status": summary_data["data_availability"]["transactions"]["status"],
            "records": tx_items,
        }
        (root / "transactions.json").write_text(json.dumps(tx_data, ensure_ascii=False, indent=2), encoding="utf-8")

        # 5. 產出 token_transfers.json
        tr_data = {
            "available": summary_data["data_availability"]["token_transfers"]["available"],
            "status": summary_data["data_availability"]["token_transfers"]["status"],
            "records": tr_items,
        }
        (root / "token_transfers.json").write_text(json.dumps(tr_data, ensure_ascii=False, indent=2), encoding="utf-8")

        # 6. 產出 internal_transactions.json
        itx_data = {
            "available": summary_data["data_availability"]["internal_transactions"]["available"],
            "status": summary_data["data_availability"]["internal_transactions"]["status"],
            "reason": summary_data["data_availability"]["internal_transactions"].get("reason", ""),
            "records": itx_items,
        }
        (root / "internal_transactions.json").write_text(json.dumps(itx_data, ensure_ascii=False, indent=2), encoding="utf-8")

        # 7. 產出 traces_and_logs.json
        traces_data = {
            "available": summary_data["data_availability"]["contract_logs"]["available"],
            "status": summary_data["data_availability"]["contract_logs"]["status"],
            "records": log_items,
            "flow_events": [e.to_dict() for e in getattr(result, "flow_events", [])],
        }
        (root / "traces_and_logs.json").write_text(json.dumps(traces_data, ensure_ascii=False, indent=2), encoding="utf-8")

        # 8. 產出 labels.json 與 contracts.json
        (root / "labels.json").write_text(json.dumps(labels_map, ensure_ascii=False, indent=2), encoding="utf-8")
        (root / "contracts.json").write_text(json.dumps(contracts_map, ensure_ascii=False, indent=2), encoding="utf-8")

        # 9. 產出 diagnostic.log
        diag_lines = list(getattr(result, "diagnostic_logs", []))
        if not diag_lines:
            diag_lines.append(f"[{datetime.now(timezone.utc).isoformat()}] 查詢執行完成，狀態：{result.analysis_status}")
            diag_lines.append(f"查詢目標：{result.query}，網路：{result.network}")
            for k, v in summary_data["data_availability"].items():
                diag_lines.append(f"資料來源【{k}】：available={v.get('available')}, status={v.get('status')}, records={v.get('record_count')}")
            if result.incomplete_tracks:
                diag_lines.append(f"截斷或未完成軌道：{', '.join(result.incomplete_tracks)}")
        (root / "diagnostic.log").write_text("\n".join(diag_lines), encoding="utf-8")

        # 10. 產出 PROMPT.txt
        prompt_content = f"""請分析附件中的鏈上法證資料包。

目標地址：
{result.query}

所屬鏈別：
{result.network} (Chain ID: 137)

查詢時間：
{summary_data['export_time_utc']}

分析目的：
1. 整理直接入金來源（Inbound）。
2. 整理直接出金去向（Outflow）。
3. 辨識附件中已有鏈上證據或公開標籤支持的交易所／服務商（VASP）。
4. 如涉及 Relay / Bridge，分析可能之來源鏈（如 BNB Chain、Ethereum）與跨鏈特徵。
5. 嘗試整理來源鏈上游出資地址。
6. 清楚區分可信度等級：
   - 已確認 (Confirmed，具明確 Tx Hash、Request ID 或精確日誌)
   - 高度相關 (Strong Candidate，時間窗口與精確金額相符)
   - 候選 (Candidate，僅金額或時間接近)
   - 無法確認 (Unresolved，多跳模糊或缺乏底層證據)
7. 不得只以時間接近或金額接近即草率認定同源。
8. 所有關聯結論請務必嚴格引用底層鏈上證據：
   - Chain
   - Tx Hash
   - Address
   - Block Number
   - Event / Method
   - Token Contract
   - Amount
9. 資料不足時明確標示資料不足（請參閱 summary.json 中各項 data_availability 狀態），不得自行假想補充。
10. 若發現 Collector 可能漏資料，請根據 diagnostic.log 指出可能發生在哪一層：
    Provider / Pagination / Parser / Normalize / Filter / Candidate Matching。
"""
        (root / "PROMPT.txt").write_text(prompt_content, encoding="utf-8")

        # 11. 產出 README.txt
        readme_content = f"""======================================================================
Blockchain Evidence Collector - Agent Analysis Bundle
======================================================================

本資料包由 Blockchain Evidence Collector 自動採集並打包，專為 Antigravity、
Codex、ChatGPT 或其他具備檔案分析能力的 Agent 設計。

【目標資訊】
- 目標地址：{result.query}
- 網路鏈別：{result.network}
- 採集狀態：{result.analysis_status}
- 匯出時間：{summary_data['export_time_utc']}

【檔案結構說明】
- PROMPT.txt                 : 預置標準分析 Prompt，可直接複製提供給 Agent 進行分析。
- summary.json               : 採集總覽、資料可用性（Data Availability）、統計計數與候選清單。
- transactions.json          : 主鏈交易紀錄（Normal Transactions）。
- token_transfers.json       : 標準化代幣轉帳（ERC-20 Transfers）。
- internal_transactions.json : 內部交易紀錄（Internal Transactions / Contract Calls）。
- traces_and_logs.json       : 合約事件日誌與原始 FlowEvent 串流。
- labels.json                : 本次金流涉及地址之公開標籤與交易所識別清冊。
- contracts.json             : 本次金流涉及合約之地址與代幣中繼資料。
- diagnostic.log             : 採集過程審計日誌、分頁完整性與過濾原因診斷記錄。

【法證與資料完整性宣告】
本資料包所列資料均源自公開區塊鏈 RPC 與 Explorer API。若 summary.json 中某項目之
available 為 false，代表該資料類型未成功取得（例如端點未配置或無此索引），絕非鏈上 0 筆。
======================================================================
"""
        (root / "README.txt").write_text(readme_content, encoding="utf-8")

        # 打包為 ZIP
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(value for value in root.rglob("*") if value.is_file()):
                archive.write(item, item.relative_to(root).as_posix())
