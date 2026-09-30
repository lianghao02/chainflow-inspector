from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import AnalysisResult


@dataclass
class HistoryEntry:
    id: str
    query: str
    mode: str
    timestamp: str
    display_title: str
    steps_count: int
    vasp_label: str
    snapshot_file: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HistoryEntry:
        valid_keys = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in valid_keys})


def _short_query(value: str) -> str:
    val = value.strip()
    return f"{val[:8]}...{val[-6:]}" if len(val) > 16 else val


def get_history_dir() -> Path:
    """取得可攜式歷史紀錄目錄；優先使用專案目錄，無寫入權限則 fallback 至 AppData/Home。"""
    try:
        primary = Path(__file__).resolve().parent.parent / "history"
        primary.mkdir(parents=True, exist_ok=True)
        # 測試寫入權限
        test_file = primary / ".write_test"
        test_file.touch()
        test_file.unlink()
        return primary
    except (OSError, PermissionError):
        pass

    fallback = Path.home() / ".chain_fund_tracer" / "history"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def index_file_path() -> Path:
    return get_history_dir() / "history_index.json"


def list_history_entries() -> list[HistoryEntry]:
    """讀取歷史紀錄清單，由新到舊排列。"""
    path = index_file_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [HistoryEntry.from_dict(item) for item in data if isinstance(item, dict)]
        return []
    except (json.JSONDecodeError, OSError, TypeError):
        return []


def save_history_entry(result: AnalysisResult, mode: str = "polymarket") -> HistoryEntry:
    """儲存本次查詢的完整快照，並更新歷史清單（最多保留 50 筆）。"""
    h_dir = get_history_dir()
    now_dt = datetime.now(timezone(timedelta(hours=8)))
    timestamp_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    timestamp_key = int(time.time() * 1000)

    # 提煉主要 VASP 標籤
    vasp_hit = "無公開 VASP"
    for s in result.steps:
        if s.classification in ("交易所", "VASP") and s.label and "Router" not in s.label:
            vasp_hit = s.label
            break

    slug = re.sub(r"[^a-zA-Z0-9]+", "_", result.query.strip())[:14].strip("_")
    entry_id = f"{slug}_{timestamp_key}"
    snapshot_filename = f"{entry_id}.json"

    short_q = _short_query(result.query)
    mode_name = "Polymarket" if mode == "polymarket" else "一般"
    display_title = f"{short_q} | {vasp_hit} | {mode_name} ({len(result.steps)} 步) | {timestamp_str}"

    entry = HistoryEntry(
        id=entry_id,
        query=result.query.strip(),
        mode=mode,
        timestamp=timestamp_str,
        display_title=display_title,
        steps_count=len(result.steps),
        vasp_label=vasp_hit,
        snapshot_file=snapshot_filename,
    )

    # 1. 寫入快照檔
    snapshot_path = h_dir / snapshot_filename
    snapshot_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    # 2. 更新 index.json
    current_list = list_history_entries()
    # 移除相同 id，保留其他，並排在最前面
    new_list = [entry] + [item for item in current_list if item.id != entry_id]

    # 最多保留 50 筆，其餘清除對應快照
    if len(new_list) > 50:
        evicted = new_list[50:]
        new_list = new_list[:50]
        for old_item in evicted:
            old_file = h_dir / old_item.snapshot_file
            if old_file.is_file():
                try:
                    old_file.unlink()
                except OSError:
                    pass

    index_file_path().write_text(
        json.dumps([item.to_dict() for item in new_list], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return entry


def load_history_snapshot(entry_id: str) -> AnalysisResult | None:
    """由快照 ID 還原 AnalysisResult。"""
    h_dir = get_history_dir()
    current_list = list_history_entries()
    target_entry = next((item for item in current_list if item.id == entry_id), None)
    if not target_entry:
        return None

    snapshot_path = h_dir / target_entry.snapshot_file
    if not snapshot_path.is_file():
        return None

    try:
        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return AnalysisResult.from_dict(data)
    except (json.JSONDecodeError, OSError, TypeError):
        return None
    return None


def clear_history() -> None:
    """清空所有本機歷史紀錄與快照。"""
    h_dir = get_history_dir()
    for item in list_history_entries():
        f = h_dir / item.snapshot_file
        if f.is_file():
            try:
                f.unlink()
            except OSError:
                pass
    idx = index_file_path()
    if idx.is_file():
        try:
            idx.unlink()
        except OSError:
            pass


def delete_history_entry(entry_id: str) -> bool:
    """刪除指定 ID 之歷史紀錄項目及其快照檔案。"""
    h_dir = get_history_dir()
    current_list = list_history_entries()
    target_entry = next((item for item in current_list if item.id == entry_id), None)
    if not target_entry:
        return False

    snapshot_path = h_dir / target_entry.snapshot_file
    if snapshot_path.is_file():
        try:
            snapshot_path.unlink()
        except OSError:
            pass

    new_list = [item for item in current_list if item.id != entry_id]
    index_file_path().write_text(
        json.dumps([item.to_dict() for item in new_list], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return True


load_history_entry = load_history_snapshot

