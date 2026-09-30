from __future__ import annotations
import csv
import os
import tempfile
import unittest
from unittest.mock import patch
from chain_fund_tracer.csv_loader import inspect_and_load_polygonscan_csv, compute_file_sha256
from chain_fund_tracer.analysis import Analyzer
from chain_fund_tracer.providers import PolygonProvider
from chain_fund_tracer.config import Settings
from chain_fund_tracer.orbscan import OrbscanTradeInfo


class CsvLoaderTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    def _create_csv(self, filename: str, rows: list[list[str]], header: list[str] | None = None, encoding: str = "utf-8") -> str:
        if header is None:
            header = [
                "Transaction Hash", "Blockno", "UnixTimestamp", "DateTime (UTC)",
                "From", "To", "TokenValue", "USDValueDayOfTx", "ContractAddress",
                "TokenName", "TokenSymbol"
            ]
        path = os.path.join(self.temp_dir.name, filename)
        with open(path, "w", encoding=encoding, newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(rows)
        return path

    def test_csv_loader_parses_polygonscan_format_and_conservative_classes(self):
        target = "0x470e9f2cab6bc3e84074dd29934a50cacc71a01f"
        zero = "0x0000000000000000000000000000000000000000"
        internal_ctf = "0xc5d563a36ae78145c45a50134d48a1215220f80a"
        external_wallet = "0x1111111111111111111111111111111111111111"

        rows = [
            # 1. 零地址鑄造
            ["0xaaa1", "80001", "1760000001", "2026-05-13 08:50:05", zero, target, "100.5", "$100.5", "0xc011", "pUSD Token", "pUSD"],
            # 2. 已知 Polymarket 內部合約下注/回款
            ["0xaaa2", "80002", "1760000002", "2026-05-13 09:00:00", internal_ctf, target, "50.0", "$50.0", "0xc011", "pUSD Token", "pUSD"],
            # 3. 外部轉入候選
            ["0xaaa3", "80003", "1760000003", "2026-05-13 10:00:00", external_wallet, target, "1,500.25", "$1500.25", "0x2791", "USD Coin", "USDC.e"],
            # 4. 目標地址出金
            ["0xaaa4", "80004", "1760000004", "2026-05-13 11:00:00", target, external_wallet, "200.0", "$200.0", "0x2791", "USD Coin", "USDC.e"],
            # 5. 與目標無關交易 (應被忽略)
            ["0xaaa5", "80005", "1760000005", "2026-05-13 12:00:00", "0x9999", "0x8888", "10.0", "$10.0", "0x2791", "USD Coin", "USDC.e"],
        ]

        csv_path = self._create_csv("sample.csv", rows)
        data = inspect_and_load_polygonscan_csv(csv_path, target)

        self.assertEqual(data["file_name"], "sample.csv")
        self.assertEqual(len(data["sha256"]), 64)
        self.assertEqual(data["total_rows"], 5)
        self.assertFalse(data["is_truncated"])
        self.assertEqual(data["inbound_count"], 3)
        self.assertEqual(data["outbound_count"], 1)
        self.assertEqual(data["time_range"], "2026-05-13 16:50:05 +0800 至 2026-05-13 20:00:00 +0800")
        self.assertEqual(data["mint_candidates_count"], 1)
        self.assertEqual(data["external_candidates_count"], 1)
        self.assertEqual(data["internal_count"], 1)

        # 候選只應包含鑄造與外部轉入 (排除內部合約與出金)
        candidates = data["candidates"]
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["hash"], "0xaaa1")
        self.assertEqual(candidates[0]["category"], "零地址鑄造候選")
        self.assertEqual(candidates[0]["amount"], "100.5")

        self.assertEqual(candidates[1]["hash"], "0xaaa3")
        self.assertEqual(candidates[1]["category"], "外部轉入候選")
        self.assertEqual(candidates[1]["amount"], "1500.25")

    def test_csv_loader_detects_truncation_at_5000_rows(self):
        target = "0x470e9f2cab6bc3e84074dd29934a50cacc71a01f"
        dummy_row = ["0xbbb1", "80000", "1760000000", "2026-05-13 00:00:00", "0x0000000000000000000000000000000000000000", target, "1.0", "$1.0", "0xc011", "pUSD", "pUSD"]
        # 建立 5000 筆假資料
        rows = [dummy_row] * 5000
        csv_path = self._create_csv("truncated.csv", rows)

        data = inspect_and_load_polygonscan_csv(csv_path, target)
        self.assertEqual(data["total_rows"], 5000)
        self.assertTrue(data["is_truncated"])

    def test_csv_loader_supports_bom_utf8_sig(self):
        target = "0x470e9f2cab6bc3e84074dd29934a50cacc71a01f"
        rows = [["0xccc1", "80001", "1760000001", "2026-05-13 08:50:05", "0x0000000000000000000000000000000000000000", target, "10.0", "$10.0", "0xc011", "pUSD", "pUSD"]]
        csv_path = self._create_csv("bom.csv", rows, encoding="utf-8-sig")

        data = inspect_and_load_polygonscan_csv(csv_path, target)
        self.assertEqual(data["mint_candidates_count"], 1)
        self.assertEqual(data["candidates"][0]["hash"], "0xccc1")

    def test_csv_mode_keeps_betting_hashes_and_reports_market(self):
        target = "0x470e9f2cab6bc3e84074dd29934a50cacc71a01f"
        exchange = "0xe111180000d2663c0091e4f400237545b87b996b"
        source = "0x1111111111111111111111111111111111111111"
        funding_tx = "0x" + "1" * 64
        betting_tx = "0x" + "2" * 64
        rows = [
            [funding_tx, "80001", "1760000001", "2026-05-13 08:50:05", source, target, "20.0", "$20", "0xc011", "pUSD", "pUSD"],
            [betting_tx, "80002", "1760000061", "2026-05-13 08:51:05", target, exchange, "8.0", "$8", "0xc011", "pUSD", "pUSD"],
        ]
        csv_path = self._create_csv("with_bet.csv", rows)
        indexed = inspect_and_load_polygonscan_csv(csv_path, target)
        self.assertEqual(indexed["betting_candidates_count"], 1)
        self.assertEqual(indexed["betting_candidates"][0]["hash"], betting_tx)

        class FakeProvider(PolygonProvider):
            def __init__(self):
                super().__init__(Settings())
            def receipt(self, hash_val: str):
                if hash_val != betting_tx:
                    return {"status": "0x1", "logs": []}
                pad = lambda addr: "0x" + "0" * 24 + addr.removeprefix("0x")
                return {"status": "0x1", "logs": [
                    {
                        "address": "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb",
                        "topics": ["0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef", pad(target), pad(exchange)],
                        "data": hex(8_000_000), "logIndex": "0x1",
                    },
                    {
                        "address": "0x4d97dcd97ec945f40cf65f87097ace5ea0476045",
                        "topics": ["0xc3d58168c5ae7397731d063d5bbf3d657854427343f4c083240f7aacaa2d0f62", pad(exchange), pad(exchange), pad(target)],
                        "data": "0x" + f"{123:064x}" + f"{10_000_000:064x}", "logIndex": "0x2",
                    },
                ]}
            def relay_request_by_hash(self, hash_val: str):
                return None

        semantic = OrbscanTradeInfo(
            market_title="測試預測題目", trader=target, role="Taker (吃單方)", side="買進 (BUY)",
            outcome="Yes", shares="10.000000", price_cents="80.0¢", price_usd="$0.800000",
            fee="未取得", value="$8.00", timestamp="", tx_hash=betting_tx,
            source="Polymarket Data API 精確交易配對",
        )
        with patch("chain_fund_tracer.orbscan.fetch_orbscan_trade", return_value=semantic):
            result = Analyzer(FakeProvider()).analyze_polymarket_funding(target, max_hops=3, csv_path=csv_path)
        bet_step = next(step for step in result.steps if step.direction == "Polymarket 投注")
        self.assertEqual(bet_step.trade_info["market_title"], "測試預測題目")
        self.assertEqual(bet_step.trade_info["outcome"], "Yes")
        self.assertEqual(bet_step.trade_info["collateral_amount"], "8.000000")
        self.assertTrue(any("投注明細：測試預測題目" in line for line in result.summary))

    def test_csv_loader_rejects_missing_headers_and_invalid_files(self):
        target = "0x470e9f2cab6bc3e84074dd29934a50cacc71a01f"
        # 缺少 TokenValue 欄位
        invalid_header = ["Transaction Hash", "From", "To"]
        bad_path = self._create_csv("bad.csv", [["0x1", "0x2", "0x3"]], header=invalid_header)

        with self.assertRaises(ValueError) as ctx:
            inspect_and_load_polygonscan_csv(bad_path, target)
        self.assertIn("缺少必要欄位", str(ctx.exception))

        # 不存在的檔案
        with self.assertRaises(FileNotFoundError):
            inspect_and_load_polygonscan_csv("non_existent_file.csv", target)

    def test_analyzer_integration_with_csv_index(self):
        target = "0x470e9f2cab6bc3e84074dd29934a50cacc71a01f"
        zero = "0x0000000000000000000000000000000000000000"
        tx_hash = "0x1111222233334444555566667777888899990000aaaabbbbccccddddeeeeffff"

        rows = [
            [tx_hash, "88888", "1760000001", "2026-05-13 08:50:05", zero, target, "25.0", "$25.0", "0xc011", "pUSD", "pUSD"]
        ]
        csv_path = self._create_csv("test_import.csv", rows)

        # 模擬 Receipt 返回 USDC 底層轉帳
        class FakeProvider(PolygonProvider):
            def __init__(self):
                super().__init__(Settings())
            def receipt(self, hash_val: str):
                return {
                    "status": "0x1",
                    "logs": [
                        {
                            "address": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174", # USDC.e
                            "topics": [
                                "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
                                "0x0000000000000000000000009999999999999999999999999999999999999999", # payer
                                "0x000000000000000000000000c011a7e12a19f7b1f670d46f03b03f3342e82dfb", # pUSD contract
                            ],
                            "data": "0x00000000000000000000000000000000000000000000000000000000017d7840", # 25.0 USDC.e (25 * 10^6)
                            "logIndex": "0x4",
                        },
                        {
                            "address": "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb", # pUSD
                            "topics": [
                                "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
                                "0x0000000000000000000000000000000000000000000000000000000000000000", # mint from 0x0
                                "0x000000000000000000000000470e9f2cab6bc3e84074dd29934a50cacc71a01f", # to target
                            ],
                            "data": "0x00000000000000000000000000000000000000000000000000000000017d7840",
                            "logIndex": "0x6",
                        }
                    ]
                }
            def relay_request_by_hash(self, hash_val: str):
                return None

        analyzer = Analyzer(FakeProvider())
        result = analyzer.analyze_polymarket_funding(target, max_hops=3, csv_path=csv_path)

        # 驗證元資料與報告
        self.assertTrue(result.csv_index)
        self.assertEqual(result.csv_index["file_name"], "test_import.csv")
        self.assertIn("歷史 CSV 索引", " ".join(result.summary))
        self.assertIn("使用者提供之歷史 CSV 索引", " ".join(result.warnings))

        # 驗證步驟證據
        step_types = [s.direction for s in result.steps]
        self.assertIn("地址入金", step_types)
        self.assertIn("pUSD 底層入金", step_types)

        mint_step = next(s for s in result.steps if s.direction == "pUSD 底層入金")
        self.assertEqual(mint_step.from_address.lower(), "0x9999999999999999999999999999999999999999")
        self.assertEqual(mint_step.evidence_source, "RPC Receipt Transfer 解碼（鏈上核實）")
        self.assertIn("可確認同筆交易中支付底層 USDC.e 的鏈上來源地址，但不等於確認自然人或帳戶控制者", mint_step.notes)


if __name__ == "__main__":
    unittest.main()
