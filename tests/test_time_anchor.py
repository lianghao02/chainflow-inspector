from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from chain_fund_tracer.config import Settings
from chain_fund_tracer.providers import (
    PolygonProvider,
    parse_time_anchor,
    TAIWAN_TZ,
)
from chain_fund_tracer.analysis import Analyzer
from chain_fund_tracer.models import AnalysisResult


class TimeAnchorTests(unittest.TestCase):
    def test_parse_time_anchor_standard_date(self):
        # 2024-05-15 結束時間預設為當日 23:59:59 (UTC+8)
        ts_end = parse_time_anchor("2024-05-15", is_end_time=True)
        self.assertIsNotNone(ts_end)
        # 換算回 datetime 檢查
        from datetime import datetime
        dt = datetime.fromtimestamp(ts_end, tz=TAIWAN_TZ)
        self.assertEqual(dt.year, 2024)
        self.assertEqual(dt.month, 5)
        self.assertEqual(dt.day, 15)
        self.assertEqual(dt.hour, 23)
        self.assertEqual(dt.minute, 59)
        self.assertEqual(dt.second, 59)

        # 起始時間預設為當日 00:00:00
        ts_start = parse_time_anchor("2024-05-15", is_end_time=False)
        dt_start = datetime.fromtimestamp(ts_start, tz=TAIWAN_TZ)
        self.assertEqual(dt_start.hour, 0)
        self.assertEqual(dt_start.minute, 0)
        self.assertEqual(dt_start.second, 0)

    def test_parse_time_anchor_slashes_and_dots(self):
        ts1 = parse_time_anchor("2024/05/15")
        ts2 = parse_time_anchor("2024.05.15")
        self.assertEqual(ts1, ts2)

    def test_parse_time_anchor_with_time(self):
        ts = parse_time_anchor("2024-05-15 14:30")
        from datetime import datetime
        dt = datetime.fromtimestamp(ts, tz=TAIWAN_TZ)
        self.assertEqual(dt.hour, 14)
        self.assertEqual(dt.minute, 30)

    def test_parse_time_anchor_empty_and_invalid(self):
        self.assertIsNone(parse_time_anchor(""))
        self.assertIsNone(parse_time_anchor("   "))
        self.assertIsNone(parse_time_anchor(None))

        with self.assertRaises(ValueError) as ctx:
            parse_time_anchor("invalid-date-string")
        self.assertIn("無法解析時間格式", str(ctx.exception))

    def test_timestamp_to_block_number_binary_search(self):
        provider = PolygonProvider(Settings())

        # 模擬 RPC：最新區塊為 60,000,000，時間戳為 1727000000
        # 每區塊間隔 2 秒：block_time(n) = 1727000000 - (60000000 - n) * 2
        def mock_rpc(method, params):
            if method == "eth_blockNumber":
                return hex(60_000_000)
            if method == "eth_getBlockByNumber":
                blk_num = int(params[0], 16) if params[0].startswith("0x") else int(params[0])
                time_val = 1727000000 - (60_000_000 - blk_num) * 2
                return {"timestamp": hex(time_val)}
            return None

        provider.rpc = MagicMock(side_effect=mock_rpc)

        # 查詢 500,000 秒前的時間戳（對應約 250,000 個區塊之前，即 59,750,000）
        target_ts = 1727000000 - 500_000
        found_block = provider.timestamp_to_block_number(target_ts)

        # 檢查二分逼近誤差在 20 個區塊以內
        self.assertAlmostEqual(found_block, 59_750_000, delta=25)

    def test_timestamp_to_block_number_bounds(self):
        provider = PolygonProvider(Settings())
        provider.rpc = MagicMock(return_value=hex(60_000_000))
        provider.block_timestamp = MagicMock(return_value="1727000000")

        # 未來時間：應回傳最新區塊 60,000,000
        future_block = provider.timestamp_to_block_number(1800000000)
        self.assertEqual(future_block, 60_000_000)

        # 創世前時間：應回傳 1
        past_block = provider.timestamp_to_block_number(1000000000)
        self.assertEqual(past_block, 1)

    def test_address_token_transfers_with_block_bounds(self):
        provider = PolygonProvider(Settings())

        sample_items = [
            {"block_number": "60000050", "hash": "0x1"},
            {"block_number": "60000020", "hash": "0x2"},  # 在範圍內
            {"block_number": "60000010", "hash": "0x3"},  # 在範圍內
            {"block_number": "59999900", "hash": "0x4"},
        ]

        with patch("chain_fund_tracer.providers.fetch_json", return_value={"items": sample_items}):
            # 限定區塊 60000000 到 60000030
            res = provider.address_token_transfers("0xabc", start_block=60000000, end_block=60000030)
            hashes = [x["hash"] for x in res]
            self.assertEqual(hashes, ["0x2", "0x3"])

    def test_analyzer_address_time_anchor_filtering(self):
        provider = PolygonProvider(Settings())
        analyzer = Analyzer(provider)

        TARGET = "0x" + "1" * 40
        SOURCE_OLD = "0x" + "2" * 40
        SOURCE_NEW = "0x" + "3" * 40

        # 模擬 5 個月前的入金（ts=1715000000）與近期的入金（ts=1726000000）
        sample_transfers = [
            {
                "hash": "0xnew",
                "time": "1726000000",
                "timestamp": "2024-09-10T10:00:00Z",
                "token": {"address": "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb", "symbol": "pUSD", "decimals": "6"},
                "from": {"hash": SOURCE_NEW},
                "to": {"hash": TARGET},
                "total": {"value": "500000000"},
                "block_number": "61000000",
            },
            {
                "hash": "0xold",
                "time": "1715000000",
                "timestamp": "2024-05-06T10:00:00Z",
                "token": {"address": "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb", "symbol": "pUSD", "decimals": "6"},
                "from": {"hash": SOURCE_OLD},
                "to": {"hash": TARGET},
                "total": {"value": "200000000"},
                "block_number": "56000000",
            },
        ]

        provider.address_token_transfers = MagicMock(return_value=sample_transfers)
        provider.timestamp_to_block_number = MagicMock(return_value=57000000)
        provider.block_info = MagicMock(return_value={
            "number": 57000000,
            "hash": "0x" + "a" * 64,
            "timestamp": 1715788799,
        })

        # 錨定在 2024-05-15 (ts 約 1715788799)
        as_of = parse_time_anchor("2024-05-15")
        result = analyzer.analyze_polymarket_funding(
            TARGET, max_hops=1, as_of_time=as_of, time_filter_raw="2024-05-15"
        )

        # 驗證新入金（0xnew，ts=1726000000）被過濾，只保留 5 個月前的入金（0xold，ts=1715000000）
        step_hashes = [s.tx_hash for s in result.steps]
        self.assertIn("0xold", step_hashes)
        self.assertNotIn("0xnew", step_hashes)

        # 驗證摘要與 time_filter 元資料
        self.assertIn("歷史時間錨定", "\n".join(result.summary))
        self.assertEqual(result.time_filter.get("raw_input"), "2024-05-15")
        self.assertEqual(result.time_filter.get("end_block"), 57000000)

    def test_time_cache_does_not_pollute_hour(self):
        provider = PolygonProvider(Settings())
        def mock_rpc(method, params):
            if method == "eth_blockNumber":
                return hex(60_000_000)
            if method == "eth_getBlockByNumber":
                blk_num = int(params[0], 16) if params[0].startswith("0x") else int(params[0])
                time_val = 1727000000 - (60_000_000 - blk_num) * 2
                return {"timestamp": hex(time_val), "hash": f"0xhash_{blk_num}"}
            return None
        provider.rpc = MagicMock(side_effect=mock_rpc)

        ts_1430 = 1726000000 + 1800  # 14:30
        ts_1400 = 1726000000         # 14:00
        blk_1430 = provider.timestamp_to_block_number(ts_1430)
        blk_1400 = provider.timestamp_to_block_number(ts_1400)
        self.assertNotEqual(blk_1430, blk_1400)
        self.assertGreater(blk_1430, blk_1400)

    def test_strict_cutoff_ceiling(self):
        provider = PolygonProvider(Settings())
        base_ts = 1720000000
        def mock_rpc(method, params):
            if method == "eth_blockNumber":
                return hex(60_000_100)
            if method == "eth_getBlockByNumber":
                blk = int(params[0], 16) if params[0].startswith("0x") else int(params[0])
                return {"timestamp": hex(base_ts + (blk - 60_000_000) * 2), "hash": f"0x{blk}"}
            return None
        provider.rpc = MagicMock(side_effect=mock_rpc)
        # Target timestamp = base_ts + 15
        # blk 60_000_007 的 ts = base_ts + 14 <= base_ts + 15
        # blk 60_000_008 的 ts = base_ts + 16 > base_ts + 15
        # 嚴格 floor 必須回傳 60_000_007，絕不可挑到 60_000_008
        found = provider.timestamp_to_block_number(base_ts + 15)
        self.assertEqual(found, 60_000_007)
        info = provider.block_info(found)
        self.assertLessEqual(info["timestamp"], base_ts + 15)

    def test_strict_cutoff_converges_with_irregular_block_intervals(self):
        provider = PolygonProvider(Settings())
        genesis_ts = 1590858000

        def mock_rpc(method, params):
            if method == "eth_blockNumber":
                return hex(1_000_000)
            if method == "eth_getBlockByNumber":
                blk = int(params[0], 16) if params[0].startswith("0x") else int(params[0])
                if blk <= 900_000:
                    timestamp = genesis_ts + blk // 9_000
                else:
                    timestamp = genesis_ts + 100 + (blk - 900_000) * 10
                return {"timestamp": hex(timestamp), "hash": f"0x{blk}"}
            return None

        provider.rpc = MagicMock(side_effect=mock_rpc)
        found = provider.timestamp_to_block_number(genesis_ts + 99)

        # 即使區塊時間分布高度不均，仍須收斂到最後一個未超過截止時間的區塊。
        self.assertEqual(found, 899_999)
        self.assertLessEqual(provider.block_info(found)["timestamp"], genesis_ts + 99)
        self.assertGreater(provider.block_info(found + 1)["timestamp"], genesis_ts + 99)

    def test_analyzer_fail_fast_on_time_conversion_error(self):
        from chain_fund_tracer.providers import ProviderError
        provider = PolygonProvider(Settings())
        provider.timestamp_to_block_number = MagicMock(side_effect=ProviderError("RPC 斷線無法計算區塊"))
        analyzer = Analyzer(provider)
        with self.assertRaises(ProviderError) as ctx:
            analyzer.analyze_polymarket_funding("0x" + "1" * 40, as_of_time=1715000000)
        self.assertIn("歷史時間轉區塊失敗", str(ctx.exception))

    def test_general_mode_warns_on_time_filter(self):
        provider = PolygonProvider(Settings())
        provider.address_transactions = MagicMock(return_value=[])
        analyzer = Analyzer(provider)
        result = analyzer.analyze("0x" + "1" * 40, as_of_time=1715000000, time_filter_raw="2024-05-15")
        self.assertTrue(any("時間錨定目前僅適用於 Polymarket" in w for w in result.warnings))

    def test_exporters_preserve_time_filter_evidence(self):
        import tempfile
        from pathlib import Path
        import csv
        import json
        import zipfile
        from chain_fund_tracer.exporters import export_csv, export_evidence_package
        from chain_fund_tracer.svg_exporter import export_svg
        from chain_fund_tracer.models import AnalysisResult, TraceStep

        result = AnalysisResult(query="0x" + "1" * 40)
        result.time_filter = {
            "raw_input": "2024-05-15",
            "timezone": "Asia/Taipei (UTC+8)",
            "cutoff_text": "2024-05-15 23:59:59 +0800",
            "end_block": 57000000,
            "end_block_hash": "0xblockhash123",
        }
        result.steps.append(TraceStep(
            "地址入金", 1, "0xtx1", "2024-05-15 12:00:00", "pUSD", "100.0",
            "0xfrom", "0xto", "0xfrom", "Polymarket", "Exchange", "內建", "已確認", "僅資金關聯", "筆記"
        ))

        with tempfile.TemporaryDirectory() as tmp:
            # CSV 測試
            csv_file = Path(tmp) / "test.csv"
            export_csv(result, str(csv_file))
            with open(csv_file, encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                row = next(reader)
                self.assertEqual(row["time_filter_cutoff"], "2024-05-15 23:59:59 +0800")
                self.assertEqual(row["time_filter_block"], "57000000")

            # ZIP 證據包測試
            zip_file = Path(tmp) / "evidence.zip"
            export_evidence_package(result, str(zip_file))
            with zipfile.ZipFile(zip_file, "r") as zf:
                manifest_data = json.loads(zf.read("manifest.json").decode("utf-8"))
                self.assertIn("time_filter", manifest_data)
                self.assertEqual(manifest_data["time_filter"]["end_block"], 57000000)
                self.assertEqual(manifest_data["time_filter"]["end_block_hash"], "0xblockhash123")

            # SVG 測試
            svg_file = Path(tmp) / "test.svg"
            export_svg(result, str(svg_file))
            svg_text = svg_file.read_text(encoding="utf-8")
            self.assertIn("歷史條件", svg_text)
            self.assertIn("57000000", svg_text)


if __name__ == "__main__":
    unittest.main()
