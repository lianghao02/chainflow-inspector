import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chain_fund_tracer.history import (
    HistoryEntry,
    clear_history,
    list_history_entries,
    load_history_snapshot,
    save_history_entry,
)
from chain_fund_tracer.models import AnalysisResult, TraceStep, Transfer


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.patcher = patch("chain_fund_tracer.history.get_history_dir", return_value=Path(self.temp_dir.name))
        self.patcher.start()

        self.step = TraceStep(
            direction="外部入金主路徑",
            hop=1,
            tx_hash="0x" + "a" * 64,
            timestamp="2026-09-23 10:00:00 +0800",
            token="USDT",
            amount="100.000000",
            from_address="0x" + "1" * 40,
            to_address="0x" + "2" * 40,
            address="0x" + "1" * 40,
            classification="交易所",
            label="Binance: Withdrawals 7",
            label_source="BscScan 公開標籤",
            confidence="高度可能",
            relation="僅資金關聯",
            trade_info={"action": "買進 (BUY)", "shares": "10"},
        )
        self.transfer = Transfer(
            tx_hash="0x" + "a" * 64,
            token="USDT",
            amount="100",
            from_address="0x" + "1" * 40,
            to_address="0x" + "2" * 40,
        )
        self.result = AnalysisResult(
            query="0x" + "2" * 40,
            network="Polygon",
            summary=["測試摘要"],
            steps=[self.step],
            transfers=[self.transfer],
            warnings=["測試警告"],
        )

    def tearDown(self):
        self.patcher.stop()
        self.temp_dir.cleanup()

    def test_save_and_list_history(self):
        self.assertEqual(len(list_history_entries()), 0)
        entry = save_history_entry(self.result, "polymarket")
        self.assertIsNotNone(entry.id)
        self.assertIn("Binance", entry.display_title)
        self.assertEqual(entry.vasp_label, "Binance: Withdrawals 7")
        self.assertEqual(entry.steps_count, 1)

        entries = list_history_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].id, entry.id)
        self.assertEqual(entries[0].query, self.result.query)

    def test_load_history_snapshot_restores_complete_result(self):
        entry = save_history_entry(self.result, "polymarket")
        restored = load_history_snapshot(entry.id)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.query, self.result.query)
        self.assertEqual(restored.network, "Polygon")
        self.assertEqual(len(restored.steps), 1)
        self.assertEqual(restored.steps[0].tx_hash, self.step.tx_hash)
        self.assertEqual(restored.steps[0].trade_info, {"action": "買進 (BUY)", "shares": "10"})
        self.assertEqual(len(restored.transfers), 1)
        self.assertEqual(restored.transfers[0].token, "USDT")
        self.assertEqual(restored.summary, ["測試摘要"])
        self.assertEqual(restored.warnings, ["測試警告"])

    def test_clear_history(self):
        save_history_entry(self.result, "polymarket")
        self.assertEqual(len(list_history_entries()), 1)
        clear_history()
        self.assertEqual(len(list_history_entries()), 0)


if __name__ == "__main__":
    unittest.main()
