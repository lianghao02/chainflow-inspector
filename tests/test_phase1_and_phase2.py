import unittest
from unittest.mock import MagicMock

from chain_fund_tracer.analysis import Analyzer, classify_path_category, build_subpoena_candidates
from chain_fund_tracer.config import Settings
from chain_fund_tracer.controller import Controller
from chain_fund_tracer.models import AnalysisResult, SubpoenaCandidate, TraceStep, Transfer
from chain_fund_tracer.providers import PolygonProvider


class TestPhase1AndPhase2(unittest.TestCase):
    def test_subpoena_candidate_model(self):
        cand = SubpoenaCandidate(
            service_provider="Binance",
            service_type="中心化交易所",
            association_level="逐筆本金",
            chain="Polygon",
            from_address="0xe2fc31f816a9b94326492132018c3aecc4a93ae1",
            to_address="0xcceb22d524e186153cffe79f13c0aeb75889f030",
            tx_hash="0x" + "a" * 64,
            datetime_tw="2024-05-15 12:00:00 +0800",
            asset="USDC",
            amount="1000",
            label_basis="Explorer 公開標籤",
            inquiry_value="可函調 KYC",
            limitations="交易所熱錢包提幣",
        )
        data = cand.to_dict()
        self.assertEqual(data["service_provider"], "Binance")
        self.assertEqual(data["inquiry_value"], "可函調 KYC")

        restored = SubpoenaCandidate.from_dict(data)
        self.assertEqual(restored.service_provider, "Binance")
        self.assertEqual(restored.limitations, "交易所熱錢包提幣")

    def test_analysis_result_serialization_with_subpoena_and_tracks(self):
        cand = SubpoenaCandidate(
            service_provider="OKX",
            service_type="中心化交易所",
            association_level="逐筆本金",
            chain="Polygon",
            from_address="0x" + "1" * 40,
            to_address="0x" + "2" * 40,
            tx_hash="0x" + "b" * 64,
            datetime_tw="2024-05-15 12:00:00 +0800",
            asset="USDC",
            amount="500",
            label_basis="公開標籤",
            inquiry_value="可函調 KYC",
            limitations="",
        )
        tracks = {
            "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359": {
                "token": "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",
                "symbol": "USDC",
                "status": "truncated",
                "pages_scanned": 15,
                "items_count": 750,
                "is_truncated": True,
            }
        }
        res = AnalysisResult(
            query="0x" + "2" * 40,
            subpoena_candidates=[cand],
            query_tracks=tracks,
        )
        data = res.to_dict()
        self.assertEqual(len(data["subpoena_candidates"]), 1)
        self.assertIn("0x3c499c542cef5e3811e1192ce70d8cc03d5c3359", data["query_tracks"])

        restored = AnalysisResult.from_dict(data)
        self.assertEqual(len(restored.subpoena_candidates), 1)
        self.assertEqual(restored.subpoena_candidates[0].service_provider, "OKX")
        self.assertTrue(restored.query_tracks["0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"]["is_truncated"])

    def test_classify_path_category_rules(self):
        # 1. 交易所直提
        s1 = TraceStep("地址入金", 1, "0x1", "2024-05-15", "USDC", "100", "0xfrom", "0xto", "0xfrom", "交易所", "Binance: Hot Wallet", "Explorer", "高度可能", "直接轉帳")
        self.assertEqual(classify_path_category(s1), "交易所直提")

        # 2. 跨鏈橋／Relay
        s2 = TraceStep("跨鏈入金", 1, "0x2", "2024-05-15", "USDC", "100", "0xfrom", "0xto", "0xfrom", "Bridge", "Relay Depository", "Relay", "已確認", "跨鏈履約", relay_request_id="req-123")
        self.assertEqual(classify_path_category(s2), "跨鏈橋／Relay")

        # 3. 法幣／信用卡入金服務商
        s3 = TraceStep("地址入金", 1, "0x3", "2024-05-15", "USDC", "100", "0xfrom", "0xto", "0xfrom", "入金服務商", "MoonPay", "Explorer", "高度可能", "直接轉帳")
        self.assertEqual(classify_path_category(s3), "法幣／信用卡入金服務商")

        # 4. DEX 兌換
        s4 = TraceStep("地址入金", 1, "0x4", "2024-05-15", "USDC", "100", "0xfrom", "0xto", "0xfrom", "DEX", "Uniswap V3 Router", "Explorer", "高度可能", "兌換轉帳")
        self.assertEqual(classify_path_category(s4), "DEX 兌換")

        # 5. Polymarket 平台內部回款／贖回
        s5 = TraceStep("Polymarket 投注", 0, "0x5", "2024-05-15", "pUSD", "100", "0xfrom", "0x4d97dcd97ec945f40cf65f87097ace5ea0476045", "0xfrom", "Polymarket", "Conditional Tokens", "合約", "已確認", "投注", path_role="內部")
        self.assertEqual(classify_path_category(s5), "Polymarket 平台內部回款／贖回")

        # 6. 外部錢包轉入
        s6 = TraceStep("地址入金", 1, "0x6", "2024-05-15", "USDC", "100", "0xuser", "0xto", "0xuser", "未知地址", "", "無公開標籤", "未知", "僅資金關聯")
        self.assertEqual(classify_path_category(s6), "外部錢包轉入")

    def test_build_subpoena_candidates(self):
        s_binance = TraceStep(
            "地址入金", 1, "0xbinance_tx", "2024-05-15 10:00:00", "USDC", "5000",
            "0xbinance_addr", "0xtarget", "0xbinance_addr",
            "交易所", "Binance 14", "Explorer", "高度可能", "僅資金關聯",
            path_category="交易所直提", line_style="solid", event_role="補款",
        )
        s_moonpay = TraceStep(
            "地址入金", 1, "0xmoonpay_tx", "2024-05-15 11:00:00", "USDC", "200",
            "0xmoonpay_addr", "0xtarget", "0xmoonpay_addr",
            "入金服務商", "MoonPay", "Explorer", "高度可能", "僅資金關聯",
            path_category="法幣／信用卡入金服務商", line_style="solid", event_role="補款",
        )
        s_internal = TraceStep(
            "Polymarket 投注", 0, "0xbet_tx", "2024-05-15 12:00:00", "pUSD", "50",
            "0xtarget", "0xinternal", "0xtarget",
            "Polymarket", "Polymarket CTF", "合約", "已確認", "直接交易",
            path_category="Polymarket 平台內部回款／贖回",
        )

        res = AnalysisResult(query="0xtarget", steps=[s_binance, s_moonpay, s_internal])
        candidates = build_subpoena_candidates(res)

        # 內部回款應被排除，剩下 2 筆
        self.assertEqual(len(candidates), 2)
        # 且兩者皆為「可函調 KYC」
        for c in candidates:
            self.assertEqual(c.inquiry_value, "可函調 KYC")
            self.assertEqual(c.association_level, "逐筆本金")

    def test_controller_initialization_and_settings(self):
        ctrl = Controller()
        init_data = ctrl.get_init_data()
        self.assertIn("settings", init_data)
        self.assertIn("rpc_url", init_data["settings"])
        self.assertIn("core_inbound_tokens", init_data["settings"])
        self.assertIsInstance(init_data["history"], list)

        # 測試 save_settings
        res = ctrl.save_settings({"max_hops": 3, "max_history_pages": 12})
        self.assertTrue(res["success"])
        self.assertEqual(ctrl.settings.max_hops, 3)
        self.assertEqual(ctrl.settings.max_history_pages, 12)


if __name__ == "__main__":
    unittest.main()
