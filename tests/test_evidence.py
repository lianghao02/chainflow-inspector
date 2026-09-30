import copy
import csv
import json
import tempfile
import unittest
import hashlib
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from chain_fund_tracer.analysis import Analyzer
from chain_fund_tracer.config import Settings
from chain_fund_tracer.explanations import explain_step, plain_summary
from chain_fund_tracer.exporters import export_csv, export_evidence_package, export_text
from chain_fund_tracer.flow_graph import build_flow_graph, bridge_elapsed, infer_node_role, ROLE_EXCHANGE, ROLE_DEX
from chain_fund_tracer.models import AnalysisResult, TraceStep, timestamp_to_text
from chain_fund_tracer.outflow import append_relay_outflows
from chain_fund_tracer.providers import PolygonProvider, ProviderError
from chain_fund_tracer.relay_evidence import select_request, exact_pair, destination_fills, amount_text, same_chain_request_match
from chain_fund_tracer.wallet_resolver import resolve_wallet

A, B, C = ("0x" + char * 40 for char in "abc")
SOURCE, DEST = ("0x" + char * 64 for char in "12")
TOKEN = "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d"
BINANCE = "0xe2fc31f816a9b94326492132018c3aecc4a93ae1"
RELAY = "0x4cd00e387622c35bddb9b4c962c136462338bc31"


def fixture():
    # 合成測試資料，不是案件證據；刻意保留目的鏈較早的時間戳。
    return {"version": 2, "request": {"id": "fixture-request", "status": "success", "recipient": B, "data": {
        "inTxs": [{"hash": SOURCE, "chainId": 137, "timestamp": 100, "status": "success"}],
        "outTxs": [{"hash": DEST, "chainId": 56, "timestamp": 99, "status": "success", "block": 12,
                    "data": {"from": C}, "stateChanges": [
                        {"address": A, "change": {"balanceDiff": "-64002895419929017800", "data": {"tokenAddress": TOKEN}}},
                        {"address": B, "change": {"balanceDiff": "64002895419929017800", "data": {"tokenAddress": TOKEN}}},
                    ]}],
        "metadata": {"currencyOut": {"currency": {"chainId": 56, "address": TOKEN, "symbol": "USDC", "decimals": 18}}},
    }}}


def same_chain_fixture():
    return {
        "version": 2,
        "request": {
            "id": "same-chain-req-123",
            "status": "success",
            "user": A,
            "recipient": B,
            "createdAt": "2026-09-28T08:47:06.000Z",
            "data": {
                "inTxs": [{"txHash": SOURCE, "chainId": 137, "status": "success"}],
                "outTxs": [{}],
                "metadata": {
                    "sender": A,
                    "recipient": B,
                    "currencyIn": {"currency": {"chainId": 137, "address": "0xusdc", "symbol": "USDC", "decimals": 6}, "amountFormatted": "100.0"},
                    "currencyOut": {"currency": {"chainId": 137, "address": "0xpusd", "symbol": "pUSD", "decimals": 6}, "amountFormatted": "99.991114"},
                }
            }
        }
    }



def step(**values):
    item = TraceStep("Relay 出金", 1, SOURCE, timestamp_to_text(100), "USDC.e", "64.062883", C, RELAY, RELAY,
                     "Bridge", "Relay Depository", "公開標籤", "高度可能", "僅資金關聯", chain="Polygon", chain_id=137, path_role="出金")
    for key, value in values.items():
        setattr(item, key, value)
    return item


class RelayEvidenceTests(unittest.TestCase):
    def test_select_exact_request_not_first_result(self):
        correct = fixture()["request"]
        wrong = {"id": "other", "data": {"inTxs": [{"hash": "wrong"}]}}
        self.assertIs(select_request([wrong, correct], SOURCE), correct)
        self.assertIsNone(select_request([correct, copy.deepcopy(correct)], SOURCE))
        self.assertIsNone(select_request([wrong], SOURCE))

    def test_pair_requires_correct_legs(self):
        self.assertTrue(exact_pair(fixture(), SOURCE, DEST))
        self.assertFalse(exact_pair(fixture(), DEST, SOURCE))
        self.assertFalse(exact_pair(fixture(), "", ""))

    def test_multiple_inputs_and_unsupported_chains_are_rejected(self):
        value = fixture()
        value["request"]["data"]["inTxs"].append({"hash": "other", "status": "success"})
        self.assertEqual(destination_fills(value, SOURCE), [])
        value = fixture()
        value["request"]["data"]["outTxs"][0]["chainId"] = 728126428
        value["request"]["data"]["metadata"]["currencyOut"]["currency"]["chainId"] = 728126428
        self.assertEqual(destination_fills(value, SOURCE), [])

    def test_fill_preserves_precision_not_executor(self):
        fill = destination_fills(fixture(), SOURCE)[0]
        self.assertEqual(fill["amount"], "64.0028954199290178")
        self.assertEqual(fill["from"], A)
        self.assertEqual(fill["to"], B)
        self.assertEqual(fill["time"], 99)
        self.assertNotEqual(fill["from"], C)

    def test_v3_requires_actual_not_quote(self):
        value = fixture()
        value["version"] = 3
        data = value["request"]["data"]
        for key in ("inTxs", "outTxs"):
            for tx in data[key]:
                tx["txHash"] = tx.pop("hash")
        currency = data["metadata"]["currencyOut"]
        data["route"] = {"quoted": {"destination": {"outputCurrency": currency}}}
        self.assertEqual(destination_fills(value, SOURCE), [])
        data["route"]["actual"] = {"destination": {"outputCurrency": currency}}
        self.assertEqual(len(destination_fills(value, SOURCE)), 1)

    def test_pending_refunded_ambiguous_no_fill(self):
        for status in ("pending", "refunded", "failure"):
            value = fixture()
            value["request"]["status"] = status
            self.assertEqual(destination_fills(value, SOURCE), [])
        value = fixture()
        value["request"]["data"]["outTxs"][0]["stateChanges"].append(
            {"address": C, "change": {"balanceDiff": "-1", "data": {"tokenAddress": TOKEN}}})
        self.assertEqual(destination_fills(value, SOURCE), [])

    def test_mismatched_recipient_token_and_hash_are_not_used(self):
        for field, replacement in (("recipient", C),):
            value = fixture()
            value["request"][field] = replacement
            self.assertEqual(destination_fills(value, SOURCE), [])
        self.assertEqual(destination_fills(fixture(), "wrong"), [])
        self.assertEqual(amount_text("NaN", 6), "")
        self.assertEqual(amount_text("100", None), "")

    def test_same_chain_request_match_success_and_failures(self):
        fix = same_chain_fixture()
        # 成功比對：即使金額有換匯/手續費差額 (100.0 vs 99.991114)，亦應精確配對並保存審計欄位
        matched = same_chain_request_match(fix, SOURCE, expected_recipient=B)
        self.assertIsNotNone(matched)
        self.assertEqual(matched["request_id"], "same-chain-req-123")
        self.assertEqual(matched["input_amount"], "100.0")
        self.assertEqual(matched["output_amount"], "99.991114")
        self.assertEqual(matched["sender"], A)
        self.assertEqual(matched["recipient"], B)
        self.assertEqual(matched["origin_chain_id"], 137)
        self.assertEqual(matched["destination_chain_id"], 137)

        # 失敗情境：Tx Hash 不符
        self.assertIsNone(same_chain_request_match(fix, DEST, expected_recipient=B))
        # 失敗情境：Recipient 不符
        self.assertIsNone(same_chain_request_match(fix, SOURCE, expected_recipient=C))
        # 失敗情境：狀態非 success
        bad_status = copy.deepcopy(fix)
        bad_status["request"]["status"] = "pending"
        self.assertIsNone(same_chain_request_match(bad_status, SOURCE, expected_recipient=B))
        # 失敗情境：跨鏈非同鏈 (origin != dest)
        cross_chain = copy.deepcopy(fix)
        cross_chain["request"]["data"]["metadata"]["currencyOut"]["currency"]["chainId"] = 56
        self.assertIsNone(same_chain_request_match(cross_chain, SOURCE, expected_recipient=B))
        # 失敗情境：Receipt Transfer 比對不符
        dummy_transfer = [{"to": C, "token": "pUSD"}]
        self.assertIsNone(same_chain_request_match(fix, SOURCE, expected_recipient=B, receipt_transfers=dummy_transfer))
        # 成功情境：Receipt Transfer 比對相符
        good_transfer = [{"to": B, "token": "pUSD"}]
        self.assertIsNotNone(same_chain_request_match(fix, SOURCE, expected_recipient=B, receipt_transfers=good_transfer))


    def test_outflow_follows_time_order_and_marks_mixed_funds(self):
        provider = PolygonProvider(Settings())
        provider.relay_request_by_hash = Mock(return_value=fixture())
        provider.chain_receipt = Mock(return_value={"logs": [{
            "address": TOKEN,
            "topics": [
                "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
                "0x" + "0" * 24 + A[2:], "0x" + "0" * 24 + B[2:],
            ],
            "data": hex(64_002_895_419_929_017_800), "logIndex": "0x7",
        }]})
        event = {"token": {"address": TOKEN, "decimals": 18}, "from": {"hash": B}, "to": {"hash": BINANCE},
                 "timestamp": 101, "transaction_hash": "0x" + "3" * 64, "total": {"value": "1000000000000000000"}, "log_index": 1}
        old = copy.deepcopy(event)
        old["timestamp"] = 98
        provider.chain_token_transfers = Mock(return_value=[old, event])
        result = AnalysisResult(query=C, steps=[step()])
        append_relay_outflows(Analyzer(provider), result, 5)
        self.assertEqual(len(result.steps), 3)
        self.assertTrue(result.steps[0].pair_verified)
        self.assertIn("混合", result.steps[-1].notes)
        self.assertIn("Binance", result.steps[-1].label)
        self.assertIn("Receipt Transfer Log", result.steps[1].evidence_source)
        self.assertEqual(result.steps[1].log_index, "7")
        self.assertEqual(provider.chain_token_transfers.call_count, 1)
        graph = build_flow_graph(result)
        self.assertIn("目的鏈早 約 1 秒", bridge_elapsed(graph.edges[1], graph.edges))
        self.assertIn("出金資料中的交易所標籤：Binance", plain_summary(result.steps))
        self.assertIn("入金資料中的交易所標籤：尚未命中", plain_summary(result.steps))

    def test_network_failure_preserves_existing_evidence(self):
        provider = PolygonProvider(Settings())
        provider.relay_request_by_hash = Mock(side_effect=ProviderError("HTTP 429"))
        original = step()
        result = AnalysisResult(query=C, steps=[original])
        append_relay_outflows(Analyzer(provider), result, 5)
        self.assertEqual(result.steps, [original])
        self.assertIn("429", " ".join(result.warnings))

    def test_provider_rejects_batch_ambiguity(self):
        provider = PolygonProvider(Settings())
        value = fixture()["request"]
        with patch("chain_fund_tracer.providers.fetch_json", return_value={"requests": [value, copy.deepcopy(value)]}):
            with self.assertRaises(ProviderError):
                provider.relay_request_by_hash(SOURCE)


class ExplanationTests(unittest.TestCase):
    def test_label_does_not_spread_to_other_endpoint(self):
        item = step(address=A, from_address=A, to_address=B, classification="交易所", label="Binance", label_source="公開標籤")
        self.assertEqual(infer_node_role(A, item)[0], ROLE_EXCHANGE)
        self.assertNotEqual(infer_node_role(B, item)[0], ROLE_EXCHANGE)
        item.classification, item.label = "DEX", "Binance DEX Router"
        self.assertEqual(infer_node_role(A, item)[0], ROLE_DEX)
        self.assertNotEqual(infer_node_role(B, item)[0], ROLE_DEX)

    def test_same_address_different_chain_not_merged(self):
        graph = build_flow_graph(AnalysisResult(query=C, steps=[step(), step(chain="BNB Chain", chain_id=56)]))
        self.assertEqual(len(graph.nodes), 4)

    def test_deposit_info_has_no_invented_values(self):
        value = step(address=A, from_address=A, classification="Polymarket", label="DepositWallet")
        graph = build_flow_graph(AnalysisResult(query=C, steps=[value]))
        info = graph.nodes[graph.edges[0].source].deposit_info
        self.assertEqual(info["factory()"], "未取得")
        self.assertEqual(info["owner()"], "未取得")

    def test_templates_are_repeatable_and_not_identity_claims(self):
        value = step(from_address="0x" + "0" * 40)
        self.assertEqual(explain_step(value), explain_step(value))
        text = explain_step(value).text()
        self.assertIn("不是零地址匯款", text)
        self.assertIn("身分待查", text)
        self.assertNotIn("鏈上直接證據", text)
        self.assertIn("待查", explain_step(value).initiator)

    def test_exports_include_extra_fields_and_explanations(self):
        value = step(relay_request_id="fixture-request", pair_verified=True, label="=2+2", deposit_info={"owner()": "未取得"})
        result = AnalysisResult(query=C, steps=[value])
        with tempfile.TemporaryDirectory() as folder:
            csv_path, text_path = Path(folder) / "report.csv", Path(folder) / "report.txt"
            export_csv(result, str(csv_path))
            export_text(result, str(text_path))
            with csv_path.open(encoding="utf-8-sig", newline="") as stream:
                row = next(csv.DictReader(stream))
            self.assertEqual(row["relay_request_id"], "fixture-request")
            self.assertEqual(row["label"], "'=2+2")
            self.assertEqual(json.loads(row["deposit_info"])["owner()"], "未取得")
            self.assertIn("這一步代表什麼", text_path.read_text(encoding="utf-8"))
            self.assertIn("Relay Request", text_path.read_text(encoding="utf-8"))

    def test_evidence_package_has_snapshots_and_sha256_manifest(self):
        result = AnalysisResult(query=C, steps=[step()])
        result.add_evidence("receipt", "測試 RPC", {"status": "0x1", "logs": []})
        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder) / "evidence.zip"
            export_evidence_package(result, str(package))
            with zipfile.ZipFile(package) as archive:
                names = set(archive.namelist())
                self.assertIn("analysis.txt", names)
                self.assertIn("steps.csv", names)
                self.assertIn("manifest.json", names)
                evidence_name = next(name for name in names if name.startswith("evidence/"))
                manifest = json.loads(archive.read("manifest.json"))
                indexed = {item["path"]: item for item in manifest["files"]}
                self.assertEqual(indexed[evidence_name]["sha256"], hashlib.sha256(archive.read(evidence_name)).hexdigest())

    def test_taiwan_time_does_not_depend_on_system_timezone(self):
        self.assertEqual(timestamp_to_text(0), "1970-01-01 08:00:00 +0800")
        self.assertEqual(timestamp_to_text("1970-01-01T00:00:00Z"), "1970-01-01 08:00:00 +0800")
        self.assertEqual(timestamp_to_text("1970-01-01T00:00:00"), "")


class WalletResolverTests(unittest.TestCase):
    def test_cancel_before_rpc_leaves_no_partial_result(self):
        provider = Mock()
        with self.assertRaisesRegex(RuntimeError, "cancel"):
            resolve_wallet(provider, A, Mock(side_effect=RuntimeError("cancel")))
        provider.rpc.assert_not_called()

    def test_unknown_interface_remains_unknown_with_block_reference(self):
        provider = Mock()
        def rpc(method, params):
            if method == "eth_chainId": return "0x89"
            if method == "eth_getBlockByNumber": return {"number": "0x1", "hash": SOURCE}
            if method == "eth_getCode": return "0x6000"
            if method == "eth_getStorageAt": return "0x" + "0" * 64
            raise ProviderError("unsupported")
        provider.rpc.side_effect = rpc
        info = resolve_wallet(provider, A)
        self.assertIn("未取得", info["owner()"])
        self.assertEqual(info["是否 Proxy"], "未確認")
        self.assertEqual(info["區塊 Hash"], SOURCE)

    def test_wrong_chain_is_rejected(self):
        provider = Mock()
        provider.rpc.return_value = "0x38"
        with self.assertRaises(ProviderError): resolve_wallet(provider, A)

    def test_standard_proxy_and_interface_reads_keep_fixed_block(self):
        provider = Mock()
        def rpc(method, params):
            if method == "eth_chainId": return "0x89"
            if method == "eth_getBlockByNumber": return {"number": "0x1", "hash": SOURCE}
            if method == "eth_getCode": return "0x363d3d373d3d3d363d73" + A[2:] + "5af43d82803e903d91602b57fd5bf3"
            if method == "web3_sha3": return SOURCE
            if method == "eth_call":
                self.assertEqual(params[1], "0x1")
                return "0x" + "0" * 24 + B[2:]
            raise ProviderError("unsupported")
        provider.rpc.side_effect = rpc
        info = resolve_wallet(provider, A)
        self.assertEqual(info["owner()"], B)
        self.assertEqual(info["Implementation"], A)
        self.assertIn("ERC-1167", info["是否 Proxy"])


class ObjectiveLanguageAndSameChainRelayTests(unittest.TestCase):
    FORBIDDEN_PHRASES = [
        "嫌疑人跳板錢包",
        "真實主操盤錢包",
        "精準符合交易所提幣特徵",
        "Gas 出金點就是全案實名破口",
        "完全可以立案調證",
        "100% 完整閉環",
        "已確認自然人",
    ]

    def test_same_chain_relay_penetration_and_line_styles(self):
        target_addr = "0x" + "b" * 40
        router_addr = "0xb92fe925dc43a0ecde6c8b1a2709c170ec4fff4f"
        user_addr = "0x3ed11b104cc375e3a184d7a87524e8bc36183aec"
        pool_addr = "0xb86950f2a9d8cbb5bdeaff79cc02f499372bfc56"
        moonpay_addr = "0x7afc12c8dd2e6591581d95586eb2c2a4905a12a9"
        okx_addr = "0x3aca1b103fe6dc6d11eda343b3ff25a6450eebeb"

        relay_tx = "0x1a457aa41138e078414ec6eb202689e8cda90eca7e326d95647d8568b4fa9960"
        direct_tx = "0x414212aea3e7312ac480a09e9701e4a7b6d2995f5c331faf4a04259982daedd7"
        moonpay_tx = "0x52053a042d3be61a9f8753c27c2acd6d136f38c75be511712c8b0d021d97111a"
        okx_tx = "0x2da43321d1943e9f67206b18ee33112c9ca2a7e377104710a292f44e0905a43b"

        mock_provider = Mock(spec=PolygonProvider)
        mock_provider.settings = Settings()
        mock_provider.token_history_truncated = False
        mock_provider.receipt.return_value = {
            "logs": [{
                "address": "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb",
                "topics": [
                    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
                    "0x000000000000000000000000b92fe925dc43a0ecde6c8b1a2709c170ec4fff4f",
                    "0x000000000000000000000000" + target_addr[2:],
                ],
                "data": hex(99_991_114),
                "logIndex": "0xc",
            }],
            "status": "0x1",
        }

        # 1. 目標地址歷史轉帳：收到來自 RelayRouterV3 的 99.991114 pUSD
        mock_provider.address_token_transfers.side_effect = lambda addr, **kwargs: (
            [
                {
                    "hash": relay_tx,
                    "timeStamp": "1727513226",
                    "from": {"hash": router_addr, "public_tags": [{"name": "RelayRouterV3"}]},
                    "to": {"hash": target_addr},
                    "token": {"address": "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb", "symbol": "pUSD", "decimals": "6"},
                    "total": {"value": "99991114"},
                    "block_number": "62000000",
                    "log_index": "12",
                }
            ] if addr.lower() == target_addr.lower()
            else (
                # 2. Relay 使用者地址歷史：收到來自 pool_addr 的 100 USDC
                [
                    {
                        "hash": direct_tx,
                        "timeStamp": "1727513130",
                        "from": {"hash": pool_addr},
                        "to": {"hash": user_addr},
                        "token": {"address": "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359", "symbol": "USDC", "decimals": "6"},
                        "total": {"value": "100000000"},
                        "block_number": "61999950",
                    }
                ] if addr.lower() == user_addr.lower() else []
            )
        )

        # 3. Relay Request Mock
        relay_req = {
            "version": 2,
            "request": {
                "id": "0x1790585219e406f9983fda54925bf69a525fcd5908341663ea9ff648fb74ad6b",
                "status": "success",
                "user": user_addr,
                "recipient": target_addr,
                "createdAt": "2026-09-28T08:47:06.000Z",
                "data": {
                    "inTxs": [{"txHash": relay_tx, "chainId": 137, "status": "success"}],
                    "outTxs": [{"txHash": relay_tx, "chainId": 137, "status": "success"}],
                    "metadata": {
                        "sender": user_addr,
                        "recipient": target_addr,
                        "currencyIn": {"currency": {"chainId": 137, "address": "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359", "symbol": "USDC", "decimals": 6}, "amountFormatted": "100.000000"},
                        "currencyOut": {"currency": {"chainId": 137, "address": "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb", "symbol": "pUSD", "decimals": 6}, "amountFormatted": "99.991114"},
                    }
                }
            }
        }
        mock_provider.relay_request_by_hash.return_value = relay_req

        # 4. 中間資金池分頁與標籤 Mock：MoonPay 30,000 USDC
        mock_provider.polygon_token_transfers_before.return_value = [
            {
                "transaction_hash": moonpay_tx,
                "timestamp": "1727217336",
                "from": {
                    "hash": moonpay_addr,
                    "metadata": {"tags": [{"name": "MoonPay 7", "tagType": "name"}]}
                },
                "to": {"hash": pool_addr},
                "token": {"address": "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359", "symbol": "USDC", "decimals": "6"},
                "total": {"value": "30000000000"},
                "block_number": "61800000",
            }
        ]

        # 5. 原生交易 Mock：OKX 180 轉入 200.36 POL
        mock_provider.address_native_transfers_before.return_value = [
            {
                "hash": okx_tx,
                "timestamp": "1727456828",
                "from": {
                    "hash": okx_addr,
                    "metadata": {"tags": [{"name": "OKX 180", "tagType": "name"}]}
                },
                "to": {"hash": pool_addr},
                "value": "200.3600",
                "raw_value": "200360000000000000000",
                "block_number": "61950000",
            }
        ]
        mock_provider.transaction_details.return_value = None

        analyzer = Analyzer(mock_provider)
        result = analyzer._analyze_polymarket_address(target_addr, hops=4)

        # 驗證線型分佈
        line_styles = {s.line_style for s in result.steps}
        self.assertIn("solid", line_styles)
        self.assertIn("dashed", line_styles)
        self.assertIn("dotted", line_styles)

        # 驗證實線（逐筆本金）
        solid_steps = [s for s in result.steps if s.line_style == "solid"]
        self.assertTrue(any("Relay 目的鏈補款" in s.direction for s in solid_steps))
        self.assertTrue(any("Relay 來源鏈" in s.direction for s in solid_steps))
        self.assertTrue(any("來源鏈上游" in s.direction and s.amount == "100.000000" for s in solid_steps))

        # 驗證虛線（較早資金池入金）
        dashed_steps = [s for s in result.steps if s.line_style == "dashed"]
        self.assertEqual(len(dashed_steps), 1)
        self.assertEqual(dashed_steps[0].label, "MoonPay 7")
        self.assertIn("非逐筆歸屬", dashed_steps[0].notes)

        # 驗證點線（原生 POL 供資關聯）
        dotted_steps = [s for s in result.steps if s.line_style == "dotted"]
        self.assertEqual(len(dotted_steps), 1)
        self.assertEqual(dotted_steps[0].label, "OKX 180")
        self.assertIn("非本案本金", dotted_steps[0].notes)

        # 驗證逐筆本金上游僅作中立定性；資金池性質由較早關聯另行說明
        intermediate_step = next(s for s in solid_steps if s.direction == "來源鏈上游")
        self.assertEqual(intermediate_step.classification, "中間地址")
        self.assertEqual(intermediate_step.label, "未分類中間地址")
        self.assertIn("唯一吻合", intermediate_step.notes)

        # 驗證禁止詞彙絕對零出現
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            export_text(result, tmp_path)
            text_report = Path(tmp_path).read_text(encoding="utf-8")
        finally:
            if Path(tmp_path).exists():
                Path(tmp_path).unlink()
        all_text = " ".join([
            text_report,
            *result.summary,
            *result.warnings,
            *(s.notes for s in result.steps),
            *(s.direction for s in result.steps),
            *(s.label for s in result.steps),
        ])
        for forbidden in self.FORBIDDEN_PHRASES:
            self.assertNotIn(forbidden, all_text, f"報告中出現禁止用語：{forbidden}")

        # 驗證摘要只依本次實際命中內容動態生成，且不把資金池歷史入金當成本金
        pool_summary = next(line for line in result.summary if "【資金池服務商線索】" in line)
        self.assertIn("MoonPay 7", pool_summary)
        self.assertIn("OKX 180", pool_summary)
        self.assertIn("非本案本金的逐筆唯一來源", pool_summary)
        source_conclusion = next(line for line in result.summary if "【入金來源結論】" in line)
        self.assertIn("逐筆本金主線尚未命中", source_conclusion)
        self.assertIn("較早資金池或原生幣供資輔助線索", source_conclusion)


if __name__ == "__main__":
    unittest.main()
