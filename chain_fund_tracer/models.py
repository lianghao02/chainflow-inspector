from __future__ import annotations
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

@dataclass
class Transfer:
    tx_hash: str
    timestamp: str = ""
    token: str = "原生幣"
    amount: str = ""
    from_address: str = ""
    to_address: str = ""
    token_type: str = "原生幣"
    source: str = "RPC"
    token_contract: str = ""
    log_index: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Transfer:
        valid_keys = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in valid_keys})

@dataclass
class TraceStep:
    direction: str
    hop: int
    tx_hash: str
    timestamp: str
    token: str
    amount: str
    from_address: str
    to_address: str
    address: str
    classification: str
    label: str
    label_source: str
    confidence: str
    relation: str
    notes: str = ""
    chain: str = ""
    block_number: str = ""
    log_index: str = ""
    path_role: str = "入金"
    event_role: str = "轉帳"
    explorer_url: str = ""
    evidence_id: str = ""
    role_confidence: str = ""
    relation_confidence: str = ""
    deposit_info: dict[str, str] = field(default_factory=dict)
    relay_request_id: str = ""
    relay_leg: str = ""
    chain_id: int = 0
    token_contract: str = ""
    evidence_source: str = ""
    pair_verified: bool = False
    trade_info: dict[str, Any] = field(default_factory=dict)
    line_style: str = "solid"
    path_category: str = "未能分類"

    def __post_init__(self) -> None:
        if not self.role_confidence:
            if self.classification in ("交易所", "VASP") and self.label and "Router" not in self.label:
                self.role_confidence = "標籤線索（依來源查核）"
            elif any(k in self.label for k in ("Router", "DEX", "Solver", "Depository", "合約", "pUSD")):
                self.role_confidence = "合約／服務角色線索（待查核）"
            elif self.confidence:
                self.role_confidence = self.confidence
            else:
                self.role_confidence = "待查證（鏈上無公開標籤）"
        if not self.relation_confidence:
            if self.relation:
                self.relation_confidence = self.relation
            elif self.confidence:
                self.relation_confidence = self.confidence
            else:
                self.relation_confidence = "僅資金關聯"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TraceStep:
        valid_keys = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in valid_keys})

@dataclass
class SubpoenaCandidate:
    service_provider: str
    service_type: str
    association_level: str
    chain: str
    from_address: str
    to_address: str
    tx_hash: str
    datetime_tw: str
    asset: str
    amount: str
    label_basis: str
    inquiry_value: str
    limitations: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SubpoenaCandidate:
        valid_keys = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in valid_keys})

@dataclass
class AnalysisResult:
    query: str
    network: str = "Polygon"
    summary: list[str] = field(default_factory=list)
    transactions: list[dict[str, Any]] = field(default_factory=list)
    transfers: list[Transfer] = field(default_factory=list)
    steps: list[TraceStep] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    evidence_records: list[dict[str, Any]] = field(default_factory=list)
    time_filter: dict[str, Any] = field(default_factory=dict)
    csv_index: dict[str, Any] = field(default_factory=dict)
    subpoena_candidates: list[SubpoenaCandidate] = field(default_factory=list)
    query_tracks: dict[str, dict[str, Any]] = field(default_factory=dict)
    analysis_status: str = "complete"
    incomplete_tracks: list[str] = field(default_factory=list)

    def add_evidence(self, name: str, source: str, data: Any) -> None:
        """保存本次分析取得的資料快照；雜湊於匯出證據包時產生。"""
        if any(item.get("name") == name and item.get("source") == source for item in self.evidence_records):
            return
        self.evidence_records.append({
            "name": name,
            "source": source,
            "acquired_at": datetime.now(timezone.utc).isoformat(),
            "data": data,
        })

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "network": self.network,
            "summary": list(self.summary),
            "transactions": list(self.transactions),
            "transfers": [t.to_dict() for t in self.transfers],
            "steps": [s.to_dict() for s in self.steps],
            "warnings": list(self.warnings),
            "sources": list(self.sources),
            "evidence_records": list(self.evidence_records),
            "time_filter": dict(self.time_filter),
            "csv_index": dict(self.csv_index),
            "subpoena_candidates": [c.to_dict() for c in self.subpoena_candidates],
            "query_tracks": dict(self.query_tracks),
            "analysis_status": self.analysis_status,
            "incomplete_tracks": list(self.incomplete_tracks),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnalysisResult:
        transfers = [Transfer.from_dict(t) if isinstance(t, dict) else t for t in data.get("transfers", [])]
        steps = [TraceStep.from_dict(s) if isinstance(s, dict) else s for s in data.get("steps", [])]
        subpoena_candidates = [
            SubpoenaCandidate.from_dict(c) if isinstance(c, dict) else c
            for c in data.get("subpoena_candidates", [])
        ]
        return cls(
            query=data.get("query", ""),
            network=data.get("network", "Polygon"),
            summary=list(data.get("summary", [])),
            transactions=list(data.get("transactions", [])),
            transfers=transfers,
            steps=steps,
            warnings=list(data.get("warnings", [])),
            sources=list(data.get("sources", [])),
            evidence_records=list(data.get("evidence_records", [])),
            time_filter=dict(data.get("time_filter", {})),
            csv_index=dict(data.get("csv_index", {})),
            subpoena_candidates=subpoena_candidates,
            query_tracks=dict(data.get("query_tracks", {})),
            analysis_status=str(data.get("analysis_status", "complete")),
            incomplete_tracks=list(data.get("incomplete_tracks", [])),
        )

def timestamp_to_text(value: Any) -> str:
    try:
        if value is None or value == "":
            return ""
        if isinstance(value, str):
            val_clean = value.strip()
            if re.search(r"[+-]\d{4}$", val_clean):
                return val_clean
            if "T" in val_clean:
                parsed = datetime.fromisoformat(val_clean.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    return ""
                return parsed.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S %z")
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
                try:
                    dt = datetime.strptime(val_clean, fmt).replace(tzinfo=timezone.utc)
                    return dt.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S %z")
                except ValueError:
                    pass
        number = int(str(value), 16) if str(value).startswith("0x") else int(value)
        return datetime.fromtimestamp(number, tz=timezone.utc).astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S %z")
    except (TypeError, ValueError, OSError): return ""
