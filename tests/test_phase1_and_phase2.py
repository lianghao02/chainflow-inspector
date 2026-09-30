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
            path_category="交易所直提", line_style="solid", event_role="補款", pair_verified=True,
        )
        s_moonpay = TraceStep(
            "地址入金", 1, "0xmoonpay_tx", "2024-05-15 11:00:00", "USDC", "200",
            "0xmoonpay_addr", "0xtarget", "0xmoonpay_addr",
            "入金服務商", "MoonPay", "Explorer", "高度可能", "僅資金關聯",
            path_category="法幣／信用卡入金服務商", line_style="solid", event_role="補款", pair_verified=True,
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
        by_provider = {candidate.service_provider: candidate for candidate in candidates}
        self.assertEqual(by_provider["Binance"].inquiry_value, "交易所提幣帳戶函調候選")
        self.assertEqual(by_provider["MoonPay"].inquiry_value, "可函調 KYC")
        self.assertTrue(all(c.association_level == "逐筆本金" for c in candidates))

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

    def test_inspect_initial_gas_funder(self):
        provider = MagicMock()
        provider.settings = Settings()
        provider.address_native_transfers_before.return_value = [
            {
                "hash": "0xgas_tx",
                "from": {"hash": "0xokx_hot", "name": "OKX 180"},
                "to": {"hash": "0xeoa_target"},
                "value": "15.5",
                "timestamp": "2024-05-10T10:00:00Z",
                "block_number": 50000000,
            }
        ]
        provider.transaction_details.return_value = None
        analyzer = Analyzer(provider)
        res = AnalysisResult(query="0xeoa_target")

        hit = analyzer._inspect_initial_gas_funder(res, "0xeoa_target", cutoff=1800000000, hop=2)
        self.assertTrue(hit)
        self.assertEqual(len(res.steps), 1)
        step = res.steps[0]
        self.assertEqual(step.direction, "手續費供資")
        self.assertEqual(step.classification, "交易所")
        self.assertEqual(step.line_style, "dotted")
        self.assertIn("OKX", step.label)

        # 檢驗函調清單提煉是否成功納入此手續費開戶來源
        cands = build_subpoena_candidates(res)
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0].service_provider, "OKX")
        self.assertEqual(cands[0].inquiry_value, "交易所提幣帳戶函調候選")
        self.assertEqual(cands[0].association_level, "輔助線索")
        self.assertIn("手續費出資來源", cands[0].limitations)

    def test_append_eoa_recursive_upstream(self):
        provider = MagicMock()
        provider.settings = Settings()
        # 無原生 POL
        provider.address_native_transfers_before.return_value = []
        
        # eoa_1 收到 eoa_2 轉帳 100 USDC
        def mock_transfers(addr, max_pages=3):
            if addr == "0xeoa_1":
                return [{
                    "transaction_hash": "0xtx_1",
                    "from": {"hash": "0xeoa_2"},
                    "to": {"hash": "0xeoa_1"},
                    "timestamp": "2024-05-12T10:00:00Z",
                    "token": {"symbol": "USDC", "decimals": 6},
                    "total": {"value": "100000000"},
                }]
            elif addr == "0xeoa_2":
                return [{
                    "transaction_hash": "0xtx_2",
                    "from": {"hash": "0xbinance_hot", "name": "Binance: Hot Wallet"},
                    "to": {"hash": "0xeoa_2"},
                    "timestamp": "2024-05-11T10:00:00Z",
                    "token": {"symbol": "USDC", "decimals": 6},
                    "total": {"value": "100000000"},
                }]
            return []

        provider.address_token_transfers.side_effect = mock_transfers
        analyzer = Analyzer(provider)
        res = AnalysisResult(query="0xpoly_target")

        analyzer._append_eoa_recursive_upstream(
            res,
            eoa_address="0xeoa_1",
            cutoff=1800000000,
            current_hop=2,
            max_hops=4,
            expected_token="USDC",
        )

        # 應有 2 步：eoa_2 -> eoa_1 (hop 2)，以及 binance -> eoa_2 (hop 3)
        self.assertEqual(len(res.steps), 2)
        step_eoa2 = res.steps[0]
        step_binance = res.steps[1]

        self.assertEqual(step_eoa2.hop, 2)
        self.assertEqual(step_eoa2.from_address, "0xeoa_2")
        self.assertEqual(step_eoa2.classification, "非託管個人錢包")

        self.assertEqual(step_binance.hop, 3)
        self.assertEqual(step_binance.from_address, "0xbinance_hot")
        self.assertEqual(step_binance.classification, "交易所")
        self.assertIn("Binance", step_binance.label)

        # 檢驗函調清單：命中幣安為 [可函調 KYC]，eoa_2 為 [僅供上游追蹤]
        cands = build_subpoena_candidates(res)
        self.assertEqual(len(cands), 2)
        binance_cand = next(c for c in cands if c.service_provider == "Binance")
        self.assertEqual(binance_cand.inquiry_value, "交易所提幣帳戶函調候選")
        self.assertEqual(binance_cand.association_level, "逐筆本金")

    def test_inspect_initial_gas_funder_earliest_block_sort(self):
        """驗證初始 POL 手續費來源必定按區塊高度升序取歷史最早一筆，而非無序或最新一筆。"""
        provider = MagicMock()
        provider.settings = Settings()
        # 回傳兩筆：第 1 筆區塊較大 (最新，個人轉入)，第 2 筆區塊較小 (最早，OKX 交易所提幣開戶)
        provider.address_native_transfers_before.return_value = [
            {
                "hash": "0xlate_tx",
                "from": {"hash": "0xrandom_friend"},
                "to": {"hash": "0xeoa_target"},
                "value": "2.0",
                "timestamp": "2024-06-01T10:00:00Z",
                "block_number": 55000000,
            },
            {
                "hash": "0xearliest_tx",
                "from": {"hash": "0xokx_hot", "name": "OKX: Hot Wallet"},
                "to": {"hash": "0xeoa_target"},
                "value": "10.0",
                "timestamp": "2024-01-01T10:00:00Z",
                "block_number": 50000000,
            },
        ]
        provider.transaction_details.return_value = None
        analyzer = Analyzer(provider)
        res = AnalysisResult(query="0xeoa_target")

        hit = analyzer._inspect_initial_gas_funder(res, "0xeoa_target", cutoff=1800000000, hop=2)
        self.assertTrue(hit)
        self.assertEqual(len(res.steps), 1)
        step = res.steps[0]
        # 必須命中 block 50000000 的最早一筆 0xearliest_tx
        self.assertEqual(step.tx_hash, "0xearliest_tx")
        self.assertEqual(step.direction, "手續費供資")
        self.assertEqual(step.line_style, "dotted")
        self.assertIn("OKX", step.label)

    def test_append_eoa_recursive_upstream_amount_mismatch_downgrades(self):
        """驗證當金額不符時，EOA 向上遞迴不會誤標為逐筆本金，而是降級為較早資金關聯 (dashed) 且僅供上游追蹤。"""
        provider = MagicMock()
        provider.settings = Settings()
        provider.address_native_transfers_before.return_value = []

        # 預期轉出 5000 USDC，但上游交易所轉入只有 10 USDC（金額差距過大，明顯非本案本金）
        provider.address_token_transfers.return_value = [{
            "transaction_hash": "0xmismatch_tx",
            "from": {"hash": "0xbinance_hot", "name": "Binance: Hot Wallet"},
            "to": {"hash": "0xeoa_target"},
            "timestamp": "2024-05-11T10:00:00Z",
            "token": {"symbol": "USDC", "decimals": 6},
            "total": {"value": "10000000"},  # 10 USDC
        }]
        analyzer = Analyzer(provider)
        res = AnalysisResult(query="0xpoly_target")

        analyzer._append_eoa_recursive_upstream(
            res,
            eoa_address="0xeoa_target",
            cutoff=1800000000,
            current_hop=2,
            max_hops=3,
            expected_token="USDC",
            expected_amount="5000.0",  # 預期 5000
        )

        self.assertEqual(len(res.steps), 1)
        step = res.steps[0]
        # 由於金額嚴重不符，必須為 dashed 虛線，且 pair_verified 為 False
        self.assertEqual(step.line_style, "dashed")
        self.assertFalse(step.pair_verified)
        self.assertIn("非逐筆本金", step.notes)

        # 檢驗函調清單：不可標為 [可函調 KYC]，應降級為 [僅供上游追蹤]
        cands = build_subpoena_candidates(res)
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0].inquiry_value, "僅供上游追蹤")
        self.assertEqual(cands[0].association_level, "輔助線索")

    def test_outbound_exchange_cashout_subpoena_candidate(self):
        s_outflow = TraceStep(
            direction="出金目的鏈後續轉出候選",
            hop=3,
            tx_hash="0x" + "c" * 64,
            timestamp="2024-05-15 15:30:00 +0800",
            token="USDC",
            amount="64.5",
            from_address="0x" + "1" * 40,
            to_address="0x" + "2" * 40,
            address="0x" + "2" * 40,
            classification="交易所",
            label="Binance Hot Wallet 20",
            label_source="BscScan 公開標籤",
            confidence="高度可能",
            relation="僅資金關聯",
            notes="出金轉至幣安充值",
            chain="BNB Chain",
            chain_id=56,
            path_role="出金",
        )
        res = AnalysisResult(query="0x" + "1" * 40, steps=[s_outflow])
        cands = build_subpoena_candidates(res)
        self.assertEqual(len(cands), 1)
        cand = cands[0]
        self.assertEqual(cand.service_provider, "Binance")
        self.assertEqual(cand.service_type, "中心化交易所 (充值入帳)")
        self.assertEqual(cand.inquiry_value, "交易所充值帳戶函調候選")
        self.assertEqual(cand.association_level, "出金變現")
        self.assertIn("出金／變現充值地址", cand.limitations)

    def test_determine_suspect_profiles(self):
        from chain_fund_tracer.analysis import determine_suspect_profile

        # 1. 新手直充型
        s_novice = TraceStep(
            direction="地址入金", hop=1, tx_hash="0x" + "1" * 64, timestamp="2024-05-15",
            token="USDC", amount="1000", from_address="0x" + "a" * 40, to_address="0x" + "b" * 40,
            address="0x" + "a" * 40, classification="交易所", label="MAX Exchange",
            label_source="公開標籤", confidence="已確認", relation="直接交易",
            path_role="入金", line_style="solid", pair_verified=True, event_role="補款",
        )
        res1 = AnalysisResult(query="0x" + "b" * 40, steps=[s_novice])
        prof1 = determine_suspect_profile(res1)
        self.assertEqual(prof1["portrait_id"], "novice_direct")
        self.assertIn("新手直充型", prof1["portrait_title"])
        self.assertIn("極高", prof1["breakthrough_rating"])
        self.assertIn("MAX Exchange", prof1["inbound_exchange"])

        # 2. 官網跨鏈型
        s_relay_src = TraceStep(
            direction="Relay 來源鏈", hop=2, tx_hash="0x" + "2" * 64, timestamp="2024-05-15",
            token="USDC", amount="500", from_address="0x" + "c" * 40, to_address="0x" + "d" * 40,
            address="0x" + "c" * 40, classification="外部錢包", label="出資錢包",
            label_source="Relay", confidence="已確認", relation="跨鏈投入",
            path_role="入金", chain="BNB Chain", chain_id=56, relay_request_id="req-1",
            relay_leg="source", pair_verified=True,
        )
        res2 = AnalysisResult(query="0x" + "e" * 40, steps=[s_relay_src])
        prof2 = determine_suspect_profile(res2)
        self.assertEqual(prof2["portrait_id"], "cross_chain")
        self.assertIn("官網跨鏈型", prof2["portrait_title"])
        self.assertIn("BNB Chain", prof2["inbound_exchange"])
        self.assertIn("Relay 官方當作調證終點", prof2["limitations"])

        # 3. 獲利出金退場型
        s_cashout = TraceStep(
            direction="出金目的鏈後續轉出候選", hop=3, tx_hash="0x" + "3" * 64, timestamp="2024-05-15",
            token="USDC", amount="200", from_address="0x" + "e" * 40, to_address="0x" + "f" * 40,
            address="0x" + "f" * 40, classification="交易所", label="Binance Hot Wallet",
            label_source="BscScan 公開標籤", confidence="已確認", relation="僅資金關聯",
            path_role="出金", chain="BNB Chain", chain_id=56,
        )
        res3 = AnalysisResult(query="0x" + "e" * 40, steps=[s_cashout])
        prof3 = determine_suspect_profile(res3)
        self.assertEqual(prof3["portrait_id"], "profit_cashout")
        self.assertIn("獲利出金退場型", prof3["portrait_title"])
        self.assertIn("Binance", prof3["outbound_exchange"])

        # 4. 幣圈囤幣（非託管私鑰）型
        s_eoa = TraceStep(
            direction="地址入金", hop=1, tx_hash="0x" + "4" * 64, timestamp="2024-05-15",
            token="USDC", amount="300", from_address="0x" + "7" * 40, to_address="0x" + "8" * 40,
            address="0x" + "7" * 40, classification="外部錢包", label="個人錢包",
            label_source="無公開標籤", confidence="未知", relation="僅資金關聯",
            path_role="入金", path_category="外部錢包轉入",
        )
        res4 = AnalysisResult(query="0x" + "8" * 40, steps=[s_eoa])
        prof4 = determine_suspect_profile(res4)
        self.assertEqual(prof4["portrait_id"], "eoa_hodler")
        self.assertIn("幣圈囤幣", prof4["portrait_title"])

        # 5. 平台內部合約型
        s_internal = TraceStep(
            direction="地址入金", hop=1, tx_hash="0x" + "5" * 64, timestamp="2024-05-15",
            token="pUSD", amount="19.84", from_address="0x0000000000000000000000000000000000000000",
            to_address="0x" + "9" * 40, address="0x" + "9" * 40, classification="代幣鑄造 (Mint)",
            label="零地址", label_source="合約", confidence="已確認", relation="內部事件",
            path_role="內部", event_role="代幣鑄造", path_category="Polymarket 平台內部回款／贖回",
        )
        res5 = AnalysisResult(query="0x" + "9" * 40, steps=[s_internal])
        prof5 = determine_suspect_profile(res5)
        self.assertEqual(prof5["portrait_id"], "internal_contract")
        self.assertIn("平台內部合約", prof5["portrait_title"])


if __name__ == "__main__":
    unittest.main()
