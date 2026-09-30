import unittest
from unittest.mock import patch
from chain_fund_tracer.analysis import Analyzer
from chain_fund_tracer.config import Settings
from chain_fund_tracer.providers import PolygonProvider, ProviderError
class FakeProvider(PolygonProvider):
    def __init__(self): super().__init__(Settings())
    def transaction(self, value): return {"hash":value,"from":"0x"+"a"*40,"to":"0x"+"b"*40,"value":"0x0","blockNumber":"0x1"}
    def receipt(self, value): return {"status":"0x1","logs":[]}
    def block_timestamp(self, value): return "0x1"
    def address_transactions(self, value): return []
    def address_token_transfers(self, value): return []
    def relay_request_by_hash(self, value): return None
class AnalysisTests(unittest.TestCase):
    def test_rejects_invalid_query(self):
        with self.assertRaises(ValueError): Analyzer(FakeProvider()).analyze("bad")
    def test_transaction(self): self.assertEqual(Analyzer(FakeProvider()).analyze("0x"+"1"*64).transactions[0]["hash"],"0x"+"1"*64)
    def test_polymarket_label(self): self.assertEqual(Analyzer(FakeProvider()).classify("0x4D97DCd97eC945f40cF65F87097ACe5EA0476045")[0],"Polymarket")
    def test_funding_candidates_keep_external_and_flag_internal(self):
        analyzer=Analyzer(FakeProvider()); target="0x"+"a"*40
        events=[
            {"token":{"address_hash":"0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB","decimals":"6"},"from":{"hash":"0x"+"b"*40},"to":{"hash":target},"total":{"value":"1000000"},"timestamp":"2026-01-01T00:00:00Z","transaction_hash":"0x"+"1"*64},
            {"token":{"address":"0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB","decimals":"6"},"from":{"hash":"0x0000000000000000000000000000000000000000"},"to":{"hash":target},"total":{"value":"2000000"},"timestamp":"2026-01-02T00:00:00Z","transaction_hash":"0x"+"2"*64},
        ]
        items=analyzer._funding_candidates(events,target,1893456000)
        self.assertEqual(len(items),2); self.assertIn("外部補款候選",items[1]["note"]); self.assertIn("平台內部",items[0]["note"])
    def test_token_transfer_history_follows_explorer_cursor(self):
        provider = PolygonProvider(Settings())
        pages = [
            {"items": [{"transaction_hash": "new"}], "next_page_params": {"block_number": 12, "index": 3, "items_count": 50}},
            {"items": [{"transaction_hash": "older"}], "next_page_params": None},
        ]
        with patch("chain_fund_tracer.providers.fetch_json", side_effect=pages) as fetch:
            events = provider.address_token_transfers("0x" + "a" * 40)
        self.assertEqual([item["transaction_hash"] for item in events], ["new", "older"])
        self.assertIn("block_number=12", fetch.call_args_list[1].args[0])
        self.assertFalse(provider.token_history_truncated)

    def test_relay_details_v2(self):
        matched = {"version": 2, "request": {
            "id": "relay-request",
            "user": "0x" + "a" * 40,
            "data": {
                "inTxs": [{"hash": "0x" + "9" * 64, "chainId": 56, "timestamp": 100}],
                "metadata": {"currencyIn": {"currency": {"chainId": 56, "address": "0x" + "c" * 40, "symbol": "USDT"}, "amountFormatted": "72.9"}},
            },
            "protocol": {"deposit": {"origin": {"chainId": 56, "depositor": "0x" + "a" * 40, "depository": "0x" + "d" * 40, "transactionId": "0x" + "9" * 64}}},
        }}
        details = Analyzer(FakeProvider())._relay_details(matched)
        self.assertEqual(details["chain_id"], 56)
        self.assertEqual(details["symbol"], "USDT")
        self.assertEqual(details["amount"], "72.9")

    def test_generic_source_chain_candidate_keeps_public_label(self):
        analyzer = Analyzer(FakeProvider())
        target = "0x" + "a" * 40
        events = [{
            "token": {"address": "0x" + "c" * 40, "symbol": "USDT", "decimals": "6"},
            "from": {"hash": "0x" + "b" * 40, "name": "Binance Hot Wallet"},
            "to": {"hash": target},
            "total": {"value": "72900000"},
            "timestamp": "2026-09-22T00:00:00Z",
            "transaction_hash": "0x" + "8" * 64,
        }]
        items = analyzer._generic_inbound_candidates(events, target, 1893456000, "0x" + "c" * 40, "USDT")
        self.assertEqual(items[0]["label"], "Binance Hot Wallet")
        self.assertEqual(analyzer.classify(items[0]["from"], items[0]["label"])[0], "交易所")

    def test_same_timestamp_relay_credit_is_not_dropped(self):
        analyzer = Analyzer(FakeProvider())
        target = "0x" + "a" * 40
        event = {
            "token": {"address": "0x" + "c" * 40, "symbol": "USDC.e", "decimals": "6"},
            "from": {"hash": "0x" + "b" * 40, "name": "RelayRouterV3"},
            "to": {"hash": target},
            "total": {"value": "320000000"},
            "timestamp": "2026-09-24T00:10:05Z",
            "transaction_hash": "0x" + "6" * 64,
        }
        items = analyzer._generic_inbound_candidates(
            [event], target, 1790208605, token_symbol="USDC.e"
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["amount"], "320.000000")

    def test_same_transaction_relay_path_uses_receipt_when_history_is_truncated(self):
        from chain_fund_tracer.models import AnalysisResult

        provider = FakeProvider()
        vault = "0x" + "a" * 40
        router = "0x" + "b" * 40
        source_tx = "0x" + "7" * 64
        destination_tx = "0x" + "6" * 64
        token = "0x2791bca1f2de4661ed88a30c99a7a9449aa84174"
        provider.receipt = lambda _tx: {"logs": [{
            "address": token,
            "topics": [
                "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
                "0x" + "0" * 24 + router[2:],
                "0x" + "0" * 24 + vault[2:],
            ],
            "data": hex(320_000_000),
            "logIndex": "0x1",
        }]}
        provider.address_token_transfers = lambda _address: []
        provider.relay_request_by_hash = lambda tx_hash: ({
            "version": 2,
            "request": {
                "id": "relay-request",
                "status": "success",
                "data": {
                    "inTxs": [{"hash": source_tx, "chainId": 137, "timestamp": 1790208604}],
                    "outTxs": [{"hash": destination_tx, "chainId": 137, "timestamp": 1790208605}],
                    "metadata": {"currencyIn": {"currency": {
                        "chainId": 137, "address": token, "symbol": "USDC.e", "decimals": 6,
                    }, "amountFormatted": "320.0"}},
                },
                "protocol": {"deposit": {"origin": {
                    "chainId": 137, "depositor": "0x" + "c" * 40,
                    "depository": "0x" + "d" * 40, "transactionId": source_tx,
                    "currency": token, "amount": "320000000",
                }}},
            },
        } if tx_hash == destination_tx else None)
        result = AnalysisResult(query=vault)
        matched = Analyzer(provider)._append_relay_path(result, {
            "hash": destination_tx, "time": "2026-09-24T00:10:05Z",
            "from": vault, "to": "0x" + "e" * 40,
            "token": "USDC.e", "amount": "320.000000",
        }, 3)
        self.assertTrue(matched)
        self.assertEqual([step.direction for step in result.steps], ["Relay 目的鏈補款", "Relay 來源鏈"])
        self.assertTrue(all(step.pair_verified for step in result.steps))

    def test_receipt_formats_usdc_e_with_six_decimals(self):
        receipt = {"logs": [{
            "address": "0x2791bca1f2de4661ed88a30c99a7a9449aa84174",
            "topics": [
                "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
                "0x" + "0" * 24 + "a" * 40,
                "0x" + "0" * 24 + "b" * 40,
            ],
            "data": hex(72_748_693),
        }]}
        transfers = Analyzer(FakeProvider())._parse_receipt("0x" + "1" * 64, receipt, "")
        self.assertEqual(transfers[0].token, "USDC.e")
        self.assertEqual(transfers[0].amount, "72.748693")

    def test_polymarket_mode_accepts_address_and_finds_pusd_underlying(self):
        provider = FakeProvider()
        target = "0x" + "a" * 40
        mint_tx = "0x" + "1" * 64
        source = "0x" + "b" * 40
        provider.address_token_transfers = lambda _address: [{
            "token": {"address": "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb", "decimals": "6"},
            "from": {"hash": "0x" + "0" * 40},
            "to": {"hash": target},
            "total": {"value": "72748693"},
            "timestamp": "2026-09-23T00:07:58Z",
            "transaction_hash": mint_tx,
        }]
        provider.receipt = lambda _tx: {"logs": [{
            "address": "0x2791bca1f2de4661ed88a30c99a7a9449aa84174",
            "topics": [
                "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
                "0x" + "0" * 24 + source[2:],
                "0x" + "0" * 24 + "c011a7e12a19f7b1f670d46f03b03f3342e82dfb",
            ],
            "data": hex(72_748_693),
        }]}
        with patch.object(Analyzer, "_append_relay_path", return_value=True):
            result = Analyzer(provider).analyze_polymarket_funding(target, 5)
        self.assertTrue(any(step.direction == "pUSD 底層入金" for step in result.steps))
        self.assertIn(target, result.summary[0])

    def test_batch_mint_only_attributes_matching_target_amount(self):
        provider = FakeProvider()
        analyzer = Analyzer(provider)
        target, other = "0x" + "a" * 40, "0x" + "d" * 40
        payer1, payer2 = "0x" + "b" * 40, "0x" + "c" * 40
        tx_hash = "0x" + "4" * 64

        def transfer(contract, sender, recipient, raw, index):
            return {"address": contract, "topics": [
                "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
                "0x" + "0" * 24 + sender[2:], "0x" + "0" * 24 + recipient[2:],
            ], "data": hex(raw), "logIndex": hex(index)}

        provider.receipt = lambda _tx: {"logs": [
            transfer("0x2791bca1f2de4661ed88a30c99a7a9449aa84174", payer1, "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb", 10_000_000, 0),
            transfer("0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb", "0x" + "0" * 40, target, 10_000_000, 1),
            transfer("0x2791bca1f2de4661ed88a30c99a7a9449aa84174", payer2, "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb", 90_000_000, 2),
            transfer("0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb", "0x" + "0" * 40, other, 90_000_000, 3),
        ]}
        candidates = [{"from": "0x" + "0" * 40, "to": target, "hash": tx_hash,
                       "time": "2026-09-23T00:00:00Z", "amount": "10.000000", "log_index": "1"}]
        found = analyzer._pusd_underlying_sources(candidates, 0)
        self.assertEqual([(item["from"], item["amount"]) for item in found], [(payer1, "10.000000")])
        self.assertEqual(found[0]["attribution_confirmed"], "true")

    def test_batch_mint_ambiguous_equal_amounts_are_not_confirmed(self):
        provider = FakeProvider()
        analyzer = Analyzer(provider)
        target = "0x" + "a" * 40
        payer1, payer2 = "0x" + "b" * 40, "0x" + "c" * 40
        tx_hash = "0x" + "5" * 64

        def transfer(contract, sender, recipient, index):
            return {"address": contract, "topics": [
                "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
                "0x" + "0" * 24 + sender[2:], "0x" + "0" * 24 + recipient[2:],
            ], "data": hex(10_000_000), "logIndex": hex(index)}

        provider.receipt = lambda _tx: {"logs": [
            transfer("0x2791bca1f2de4661ed88a30c99a7a9449aa84174", payer1, "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb", 0),
            transfer("0x2791bca1f2de4661ed88a30c99a7a9449aa84174", payer2, "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb", 1),
            transfer("0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb", "0x" + "0" * 40, target, 2),
        ]}
        candidates = [{"from": "0x" + "0" * 40, "to": target, "hash": tx_hash,
                       "time": "2026-09-23T00:00:00Z", "amount": "10.000000", "log_index": "2"}]
        found = analyzer._pusd_underlying_sources(candidates, 0)
        self.assertEqual(len(found), 2)
        self.assertTrue(all(item["attribution_confirmed"] == "false" for item in found))

    def test_address_mode_expands_multiple_funding_routes_and_reports_scope(self):
        provider = FakeProvider()
        target = "0x" + "a" * 40
        provider.token_history_truncated = True
        provider.address_token_transfers = lambda _address: []
        underlying = [
            {"hash": "0x" + str(index) * 64, "time": "2026-09-23T00:00:00Z",
             "from": "0x" + char * 40, "to": "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb",
             "token": "USDC.e", "amount": f"{index}.000000", "label": "",
             "block_number": "1", "log_index": str(index), "attribution_confirmed": "true"}
            for index, char in ((1, "b"), (2, "c"))
        ]
        analyzer = Analyzer(provider)
        with patch.object(analyzer, "_pusd_underlying_sources", return_value=underlying), \
             patch.object(analyzer, "_append_relay_path", return_value=True) as append:
            result = analyzer.analyze_polymarket_funding(target, 5)
        self.assertEqual(append.call_count, 2)
        self.assertIn("已展開 2 條 Relay 路徑", " ".join(result.summary))
        self.assertIn("一般索引查詢上限", " ".join(result.warnings))

    def test_targeted_queries_do_not_overwrite_general_history_scope(self):
        provider = FakeProvider()
        target = "0x" + "a" * 40
        provider.settings = Settings(max_history_pages=15)
        provider.address_token_transfers = lambda _address, **_kwargs: []
        provider.token_history_truncated = True
        provider.token_history_scanned_count = 750
        provider.token_history_min_block = 100
        provider.token_history_max_block = 999

        def targeted(*_args, **_kwargs):
            provider.token_history_truncated = False
            provider.token_history_scanned_count = 2
            provider.token_history_min_block = 900
            provider.token_history_max_block = 999
            return []

        provider.targeted_inbound_token_transfers = targeted
        result = Analyzer(provider).analyze_polymarket_funding(target, 3)
        warnings = " ".join(result.warnings)
        self.assertIn("最多約 750 筆", warnings)
        self.assertIn("實際讀取 750 筆", warnings)

    def test_bnbscan_token_transfers_are_normalized_without_api_key(self):
        provider = PolygonProvider(Settings())
        address = "0x" + "a" * 40
        response = {"data": [{
            "txHash": "0x" + "1" * 64,
            "tokenAddress": "0x55d398326f99059ff775485246999027b3197955",
            "fromAddress": "0x" + "b" * 40,
            "toAddress": address,
            "value": "72900000000000000000",
            "timestamp": "2026-09-23T00:05:26Z",
        }]}
        with patch("chain_fund_tracer.providers.fetch_json", return_value=response):
            events = provider.chain_token_transfers(address, 56)
        self.assertEqual(events[0]["token"]["symbol"], "USDT")
        self.assertEqual(events[0]["token"]["decimals"], "18")

    def test_tronscan_transfers_are_normalized_and_keep_bybit_label(self):
        provider = PolygonProvider(Settings())
        address = "TG646F2xG8mgoCCJERNLuid81dQbmnBhoQ"
        response = {"token_transfers": [{
            "transaction_id": "2" * 64,
            "contract_address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
            "symbol": "USDT",
            "decimals": 6,
            "from_address": "TU4vEruvZwLLkSfV9bNw12EJTPvNr7Pvaa",
            "to_address": address,
            "quant": "1000000000",
            "block_ts": 1789901583000,
            "from_address_tag": {"from_address_tag": "Bybit"},
        }]}
        with patch("chain_fund_tracer.providers.fetch_json", return_value=response):
            events = provider.chain_token_transfers(address, 728126428)
        self.assertEqual(events[0]["token"]["symbol"], "USDT")
        self.assertEqual(events[0]["timestamp"], 1789901583)
        self.assertEqual(events[0]["from"]["name"], "Bybit")
        self.assertEqual(
            Analyzer(provider).classify(events[0]["from"]["hash"], events[0]["from"]["name"])[0],
            "交易所",
        )

    def test_tron_source_address_preserves_base58_case(self):
        from chain_fund_tracer.models import AnalysisResult

        provider = FakeProvider()
        source = "TG646F2xG8mgoCCJERNLuid81dQbmnBhoQ"
        bybit = "TU4vEruvZwLLkSfV9bNw12EJTPvNr7Pvaa"
        seen = []

        def transfers(address, chain_id):
            seen.append((address, chain_id))
            return [{
                "token": {"address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t", "symbol": "USDT", "decimals": "6"},
                "from": {"hash": bybit, "name": "Bybit"},
                "to": {"hash": source},
                "total": {"value": "1000000000"},
                "timestamp": 1789901583,
                "transaction_hash": "3" * 64,
            }]

        provider.chain_token_transfers = transfers
        result = AnalysisResult(query=source)
        Analyzer(provider)._append_source_chain_upstream(result, {
            "chain_id": 728126428,
            "depositor": source,
            "timestamp": 1789901601,
            "contract": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
            "symbol": "USDT",
        }, 5)
        self.assertEqual(seen[0], (source, 728126428))
        self.assertEqual(result.steps[0].label, "Bybit")
        self.assertEqual(result.steps[0].classification, "交易所")
        self.assertEqual(result.steps[0].chain, "TRON")
        self.assertEqual(result.steps[0].chain_id, 728126428)
        self.assertTrue(result.steps[0].explorer_url.startswith("https://tronscan.org/"))

    def test_verified_binance_withdrawal_label(self):
        classified = Analyzer(FakeProvider()).classify("0xe2fc31f816a9b94326492132018c3aecc4a93ae1")
        self.assertEqual(classified[0], "交易所")
        self.assertEqual(classified[1], "Binance: Withdrawals 7")

    def test_bnb_rpc_fallback_continues_to_dex_and_exchange_when_index_fails(self):
        from chain_fund_tracer.models import AnalysisResult

        provider = FakeProvider()
        relay_wallet = "0x" + "1" * 40
        funding_wallet = "0x" + "2" * 40
        usdt = "0x55d398326f99059ff775485246999027b3197955"
        router = "0xb300000b72deaeb607a12d5f54773d1c19c7028d"
        binance = "0xe2fc31f816a9b94326492132018c3aecc4a93ae1"
        relay_input_tx = "0x" + "3" * 64
        swap_tx = "0x" + "4" * 64
        native_tx = "0x" + "5" * 64

        provider.chain_token_transfers = lambda *_args: (_ for _ in ()).throw(ProviderError("索引不可用"))
        provider.chain_inbound_token_transfers_before = lambda *_args: [{
            "token": {"address": usdt, "symbol": "USDT", "decimals": "18"},
            "from": {"hash": funding_wallet}, "to": {"hash": relay_wallet},
            "total": {"value": "72900000000000000000"}, "timestamp": 900,
            "transaction_hash": relay_input_tx,
        }]
        provider.chain_token_transfers_from_prior_activity = lambda *_args: [{
            "token": {"address": usdt, "symbol": "USDT", "decimals": "18"},
            "from": {"hash": router}, "to": {"hash": funding_wallet},
            "total": {"value": "72989429000000000000"}, "timestamp": 800,
            "transaction_hash": swap_tx,
        }]
        provider.chain_transactions = lambda *_args: (_ for _ in ()).throw(ProviderError("索引不可用"))
        provider.chain_activity_transactions_before = lambda *_args: [{
            "hash": native_tx, "from": binance, "to": funding_wallet,
            "fromAddress": binance, "toAddress": funding_wallet,
            "value": "0x149934936daa400", "timestamp": 700,
        }]

        result = AnalysisResult(query=relay_wallet)
        Analyzer(provider)._append_bnb_upstream(result, {
            "depositor": relay_wallet, "timestamp": 1000, "contract": usdt,
            "symbol": "USDT", "tx_hash": "0x" + "6" * 64,
        }, 5)

        self.assertEqual(
            [step.direction for step in result.steps],
            ["Relay 前穩定幣轉入", "來源鏈兌換入帳", "來源鏈原生幣入金"],
        )
        self.assertEqual(result.steps[-1].label, "Binance: Withdrawals 7")
        self.assertEqual(result.steps[-1].amount, "0.09276721")
        self.assertIn("上游命中交易所公開標籤", " ".join(result.summary))

    def test_redemption_transaction_is_not_treated_as_external_funding(self):
        provider = FakeProvider()
        target = "0x" + "a" * 40
        tx_hash = "0x" + "7" * 64
        relay = "0x4cd00e387622c35bddb9b4c962c136462338bc31"
        events = [
            {"token":{"address":"0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb","decimals":"6"},"from":{"hash":target},"to":{"hash":"0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb"},"total":{"value":"64062883"},"timestamp":"2026-09-23T04:47:38Z","transaction_hash":tx_hash,"log_index":786},
            {"token":{"address":"0x2791bca1f2de4661ed88a30c99a7a9449aa84174","decimals":"6"},"from":{"hash":"0xc417fd8e9661c0d2120b64a04bb3278c17e99db1"},"to":{"hash":target},"total":{"value":"64062883"},"timestamp":"2026-09-23T04:47:38Z","transaction_hash":tx_hash,"log_index":787},
            {"token":{"address":"0x2791bca1f2de4661ed88a30c99a7a9449aa84174","decimals":"6"},"from":{"hash":target},"to":{"hash":relay},"total":{"value":"64062883"},"timestamp":"2026-09-23T04:47:38Z","transaction_hash":tx_hash,"log_index":794},
        ]
        provider.address_token_transfers = lambda _address: events
        result = Analyzer(provider).analyze_polymarket_funding(target, 5)
        self.assertFalse(any(step.direction == "地址入金" for step in result.steps))
        self.assertEqual({step.direction for step in result.steps}, {"pUSD 贖回", "Relay 出金"})
        self.assertTrue(all(step.path_role == "出金" for step in result.steps))
        self.assertIn("贖回／出金", " ".join(result.summary))

    def test_polymarket_mode_direct_stable_inflow_triggers_relay_and_deduplicates(self):
        provider = FakeProvider()
        target = "0x" + "a" * 40
        solver = "0x" + "b" * 40
        destination_tx = "0x" + "8" * 64
        source_tx = "0x" + "9" * 64
        token = "0x2791bca1f2de4661ed88a30c99a7a9449aa84174"

        # 模擬目標地址直接收到外部 USDC.e 轉入（非平台內部轉帳）
        provider.address_token_transfers = lambda _address: [{
            "token": {"address": token, "decimals": "6"},
            "from": {"hash": solver},
            "to": {"hash": target},
            "total": {"value": "72748693"},
            "timestamp": "2026-09-23T00:07:47Z",
            "transaction_hash": destination_tx,
            "log_index": 459,
        }]
        provider.receipt = lambda _tx: {"logs": []}
        provider.relay_request_by_hash = lambda tx_hash: ({
            "version": 2,
            "request": {
                "id": "relay-request-direct",
                "status": "success",
                "data": {
                    "inTxs": [{"hash": source_tx, "chainId": 56, "timestamp": 1790122064}],
                    "outTxs": [{"hash": destination_tx, "chainId": 137, "timestamp": 1790122067}],
                    "metadata": {"currencyIn": {"currency": {
                        "chainId": 56, "address": "0x55d398326f99059ff775485246999027b3197955", "symbol": "USDT", "decimals": 18,
                    }, "amountFormatted": "72.9"}},
                },
                "protocol": {"deposit": {"origin": {
                    "chainId": 56, "depositor": target,
                    "depository": "0x" + "c" * 40, "transactionId": source_tx,
                    "currency": "0x55d398326f99059ff775485246999027b3197955", "amount": "72900000000000000000",
                }}},
            },
        } if tx_hash == destination_tx else None)

        with patch.object(Analyzer, "_append_source_chain_upstream") as mock_upstream:
            result = Analyzer(provider).analyze_polymarket_funding(target, 5)
            mock_upstream.assert_called_once()

        directions = [step.direction for step in result.steps]
        # 確認重複的「地址入金」已被移除，保留「Relay 目的鏈補款」與「Relay 來源鏈」
        self.assertNotIn("地址入金", directions)
        self.assertIn("Relay 目的鏈補款", directions)
        self.assertIn("Relay 來源鏈", directions)
        self.assertIn("已展開 1 條 Relay 路徑", " ".join(result.summary))
        self.assertNotIn("已找到 pUSD 入金", " ".join(result.warnings))

    def test_providers_defend_against_non_dict_and_none_rpc_responses(self):
        from unittest.mock import patch
        from chain_fund_tracer.config import Settings
        from chain_fund_tracer.providers import PolygonProvider, ProviderError

        provider = PolygonProvider(Settings())
        # 模擬 fetch_json 回傳 None 或純字串，驗證 rpc() 與 chain_receipt() 安全拋出 ProviderError，不發生 TypeError
        with patch("chain_fund_tracer.providers.fetch_json", return_value=None):
            with self.assertRaises(ProviderError):
                provider.rpc("eth_blockNumber", [])
            with self.assertRaises(ProviderError):
                provider.chain_receipt("0x" + "1" * 64, 56)
            # relay_request_by_hash 回傳 None
            self.assertIsNone(provider.relay_request_by_hash("0x" + "1" * 64))
            # chain_token_transfers 與 chain_transactions 回傳空列表
            self.assertEqual(provider.chain_token_transfers("0x" + "1" * 40, 56), [])
            self.assertEqual(provider.chain_transactions("0x" + "1" * 40, 56), [])

    def test_prioritize_candidates_places_exchange_and_native_usdc_first(self):
        analyzer = Analyzer(FakeProvider())
        candidates = [
            {"hash": "0x1111", "time": "2026-09-29T12:00:00Z", "from": "0xe111180000d2663c0091e4f400237545b87b996b", "token": "pUSD", "label": "CTFExchange"},
            {"hash": "0x2222", "time": "2024-11-18T15:00:00Z", "from": "0xe7804c37c13166ff0b37f5ae0bb07a3aebb6e245", "token": "USDC", "label": "Binance: Hot Wallet 48"},
            {"hash": "0x3333", "time": "2026-04-20T00:00:00Z", "from": "0x2222222222222222222222222222222222222222", "token": "USDC.e", "label": ""},
            {"hash": "0x4444", "time": "2026-09-28T00:00:00Z", "from": "0x3333333333333333333333333333333333333333", "token": "pUSD", "label": "GnosisSafeProxy"},
        ]
        sorted_cands = analyzer._prioritize_candidates(candidates)
        # 優先順序驗證：
        # 1. 交易所標籤 (Binance) 必須排在第一位（即使是 2024 年）
        # 2. 原生儲備代幣 (USDC.e) 外部轉入排第二位
        # 3. 外部 pUSD (GnosisSafe) 排第三位
        # 4. 內部平台撮合 (CTFExchange) 排最後（即使是 2026 年最新）
        self.assertEqual(sorted_cands[0]["hash"], "0x2222")
        self.assertIn("binance", sorted_cands[0]["label"].lower())
        self.assertEqual(sorted_cands[1]["hash"], "0x3333")
        self.assertEqual(sorted_cands[2]["hash"], "0x4444")
        self.assertEqual(sorted_cands[3]["hash"], "0x1111")

    def test_polygon_provider_targeted_inbound_token_transfers(self):
        provider = PolygonProvider(Settings())
        with patch.object(provider, "address_token_transfers", return_value=[{"transaction_hash": "0xabc", "log_index": 0}]) as mock_att:
            res = provider.targeted_inbound_token_transfers("0x" + "a" * 40)
            self.assertEqual(len(res), 1)
            # 應針對 4 軌核心儲備代幣分別呼叫
            self.assertEqual(mock_att.call_count, 4)

    def test_zero_address_classified_as_mint_and_excluded_from_subpoena(self):
        from chain_fund_tracer.analysis import ZERO_ADDRESS, classify_path_category, build_subpoena_candidates
        from chain_fund_tracer.models import AnalysisResult, TraceStep

        analyzer = Analyzer(FakeProvider())
        cls_name, lbl, basis, conf = analyzer.classify(ZERO_ADDRESS)
        self.assertEqual(cls_name, "代幣鑄造 (Mint)")
        self.assertIn("零地址", lbl)

        # 驗證路徑分類：零地址作為來源或目標時，一律歸類為內部平台回款／贖回（代幣鑄造）
        step_mint = TraceStep(
            direction="地址入金", hop=1, tx_hash="0x" + "1" * 64, timestamp="2026-01-01 00:00:00",
            token="pUSD", amount="100", from_address=ZERO_ADDRESS, to_address="0x" + "a" * 40,
            address="0x" + "a" * 40, classification="代幣鑄造 (Mint)", label="零地址（代幣鑄造發行）",
            label_source="EVM 規範", confidence="已確認", relation="直接交易", notes="代幣鑄造",
            path_role="內部", event_role="代幣鑄造",
        )
        self.assertEqual(classify_path_category(step_mint), "Polymarket 平台內部回款／贖回")

        # 驗證調證清單：絕不可出現零地址
        res = AnalysisResult(query="0x" + "a" * 40)
        res.steps = [step_mint]
        candidates = build_subpoena_candidates(res)
        self.assertEqual(len(candidates), 0, "零地址絕不可被加入函調候選清單或上游追查名單")

    def test_fetch_json_retries_on_transient_timeout(self):
        from chain_fund_tracer.providers import fetch_json
        import urllib.error

        # 第一次模擬逾時，第二次成功
        mock_response = unittest.mock.MagicMock()
        mock_response.read.return_value = b'{"success": true}'
        mock_response.__enter__.return_value = mock_response

        with patch("chain_fund_tracer.providers.urlopen", side_effect=[urllib.error.URLError("The read operation timed out"), mock_response]) as mock_url:
            with patch("time.sleep") as mock_sleep:
                data = fetch_json("http://example.com/test", timeout=5, max_retries=1)
                self.assertEqual(data, {"success": True})
                self.assertEqual(mock_url.call_count, 2)
                mock_sleep.assert_called_once()

if __name__ == "__main__": unittest.main()
