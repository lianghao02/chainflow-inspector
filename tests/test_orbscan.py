import unittest
from unittest.mock import patch
from chain_fund_tracer.orbscan import (
    OrbscanTradeInfo,
    parse_orbscan_response,
    parse_polygonscan_meta,
    fallback_from_receipt,
    fetch_orbscan_trade,
    fetch_gamma_market_by_token_id,
)
from chain_fund_tracer.betting import (
    BetTrade,
    PUSD,
    POLYMARKET_CONDITIONAL_TOKENS,
    TRANSFER_TOPIC,
    TRANSFER_SINGLE_TOPIC,
)
from chain_fund_tracer.models import AnalysisResult, TraceStep
from chain_fund_tracer.explanations import explain_step
from chain_fund_tracer.flow_graph import build_flow_graph
from chain_fund_tracer.svg_exporter import generate_svg_markup

TARGET = "0x5A2409487d0a03ecbE444c8784b0EFc371477d0D".lower()
EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E".lower()
TOKEN_ID = 1008075377317019671629813133649514785465922378931293817112093787123987123


def pad_address(addr: str) -> str:
    return "0x" + "0" * 24 + addr.lower().removeprefix("0x")


def uint256_hex(val: int) -> str:
    return f"{val:064x}"


class OrbscanIntegrationTests(unittest.TestCase):
    def test_parse_orbscan_response_standard(self):
        sample_api_data = [
            {
                "transactionHash": "0xabc123",
                "title": "Will Donald Trump win the 2024 Presidential Election?",
                "maker": "0x1111111111111111111111111111111111111111",
                "taker": TARGET,
                "side": "BUY",
                "outcome": "No",
                "size": "200.0",
                "price": "0.862",
                "fee": "0.952",
                "timestamp": 1727078400,
            }
        ]

        info = parse_orbscan_response(sample_api_data, TARGET, "0xabc123")
        self.assertIsNotNone(info)
        self.assertEqual(info.market_title, "Will Donald Trump win the 2024 Presidential Election?")
        self.assertEqual(info.trader, TARGET)
        self.assertIn("Taker", info.role)
        self.assertIn("BUY", info.side)
        self.assertEqual(info.outcome, "No")
        self.assertEqual(info.shares, "200.000000")
        self.assertEqual(info.price_cents, "86.2¢")
        self.assertEqual(info.price_usd, "$0.862000")
        self.assertEqual(info.fee, "$0.952")
        self.assertEqual(info.value, "$172.40")
        self.assertIn("Orbscan", info.source)

        summary = info.summary_line()
        self.assertIn("買入 No", summary)
        self.assertIn("200.000000 Shares", summary)
        self.assertIn("價格 86.2¢", summary)
        self.assertIn("交易價值 $172.40", summary)
        self.assertIn("手續費 $0.952", summary)
        self.assertIn("Will Donald Trump win", summary)

    def test_parse_orbscan_maker_role(self):
        sample_api_data = [
            {
                "transactionHash": "0xdef456",
                "title": "Fed interest rate decision November 2024",
                "maker": TARGET,
                "taker": "0x2222222222222222222222222222222222222222",
                "side": "SELL",
                "outcome": "Yes",
                "size": 500,
                "price": 0.35,
                "fee": 0,
            }
        ]

        info = parse_orbscan_response(sample_api_data, TARGET, "0xdef456")
        self.assertIsNotNone(info)
        self.assertIn("Maker", info.role)
        self.assertIn("SELL", info.side)
        self.assertEqual(info.outcome, "Yes")
        self.assertEqual(info.price_cents, "35.0¢")

    def test_parse_orbscan_does_not_take_unrelated_first_item(self):
        unrelated = [{
            "transactionHash": "0xother",
            "title": "其他人的市場",
            "taker": "0x3333333333333333333333333333333333333333",
            "side": "BUY",
            "outcome": "Yes",
            "size": "10",
            "price": "0.5",
        }]
        self.assertIsNone(parse_orbscan_response(unrelated, TARGET, "0xwanted"))

    def test_fallback_from_receipt(self):
        pusd_amount = 8_685_810
        shares_amount = 15_000_000

        receipt = {
            "status": "0x1",
            "logs": [
                {
                    "address": PUSD,
                    "topics": [TRANSFER_TOPIC, pad_address(TARGET), pad_address(EXCHANGE)],
                    "data": hex(pusd_amount),
                    "logIndex": "0xa",
                },
                {
                    "address": POLYMARKET_CONDITIONAL_TOKENS,
                    "topics": [TRANSFER_SINGLE_TOPIC, pad_address(EXCHANGE), pad_address(EXCHANGE), pad_address(TARGET)],
                    "data": "0x" + uint256_hex(TOKEN_ID) + uint256_hex(shares_amount),
                    "logIndex": "0xb",
                },
            ],
        }

        info = fallback_from_receipt(receipt, TARGET, "0x999")
        self.assertIsNotNone(info)
        self.assertEqual(info.trader, TARGET)
        self.assertIn("BUY", info.side)
        self.assertIn("待解析（Token ID", info.outcome)
        self.assertEqual(info.shares, "15.000000")
        self.assertIn("鏈上 Receipt", info.source)
        self.assertIn("¢", info.price_cents)

    def test_fetch_orbscan_trade_with_network_fallback(self):
        pusd_amount = 8_685_810
        shares_amount = 15_000_000
        receipt = {
            "status": "0x1",
            "logs": [
                {
                    "address": PUSD,
                    "topics": [TRANSFER_TOPIC, pad_address(TARGET), pad_address(EXCHANGE)],
                    "data": hex(pusd_amount),
                    "logIndex": "0xa",
                },
                {
                    "address": POLYMARKET_CONDITIONAL_TOKENS,
                    "topics": [TRANSFER_SINGLE_TOPIC, pad_address(EXCHANGE), pad_address(EXCHANGE), pad_address(TARGET)],
                    "data": "0x" + uint256_hex(TOKEN_ID) + uint256_hex(shares_amount),
                    "logIndex": "0xb",
                },
            ],
        }

        with patch("urllib.request.urlopen", side_effect=Exception("Network unreachable")):
            info = fetch_orbscan_trade(
                tx_hash="0xabc",
                target_address=TARGET,
                api_url="https://data-api.polymarket.com/trades",
                receipt=receipt,
                timestamp="2026-09-23 16:00:00",
            )
            self.assertIsNotNone(info)
            self.assertIn("鏈上 Receipt", info.source)
            self.assertIn("BUY", info.side)

    def test_bet_trade_summary_formatting(self):
        trade = BetTrade(
            action="買進 (BUY)",
            collateral_token="pUSD",
            collateral_amount="172.40",
            shares="200.00",
            price_per_share="0.8620",
            implied_probability="86.20%",
            token_id=str(TOKEN_ID),
            token_id_hex=hex(TOKEN_ID),
            outcome_index=1,
            log_index="10",
            market_title="US Election 2024",
            outcome="No",
            trader_role="Taker",
            fee="0.952",
            value="172.40",
            enrichment_source="Orbscan / Polymarket API",
        )
        summary = trade.summary_text()
        self.assertIn("買入 No", summary)
        self.assertIn("200.00 Shares", summary)
        self.assertIn("價格 86.2¢", summary)
        self.assertIn("交易價值 172.40", summary)
        self.assertIn("手續費 0.952", summary)
        self.assertIn("US Election 2024", summary)

    def test_explanation_and_svg_enrichment(self):
        step = TraceStep(
            "Polymarket 投注", 0, "0x123", "2026-09-23 16:00:00",
            "pUSD", "172.40",
            TARGET, POLYMARKET_CONDITIONAL_TOKENS, TARGET,
            "Polymarket", "Polymarket 買入", "內建公開合約清冊", "已確認", "直接交易",
            "買入 No、200.00 Shares、價格 86.2¢、交易價值 $172.40、手續費 $0.952（市場：US Election 2024）",
            chain="Polygon", block_number="12345", log_index="10",
            path_role="內部", event_role="投注買賣",
            explorer_url="https://polygonscan.com/tx/0x123", chain_id=137,
            evidence_source="Orbscan / Polymarket API",
            trade_info={
                "action": "BUY",
                "action_label": "買入",
                "outcome": "No",
                "shares": "200.00",
                "price_per_share": "0.8620",
                "market_title": "US Election 2024",
                "trader_role": "Taker",
                "fee": "0.952",
                "value": "172.40",
                "enrichment_source": "Orbscan / Polymarket API",
            },
        )

        exp = explain_step(step)
        self.assertIn("US Election 2024", exp.text())
        self.assertIn("立場：No", exp.text())
        self.assertIn("角色：Taker", exp.text())
        self.assertIn("Orbscan / Polymarket API", exp.text())

        result = AnalysisResult(query="0x123", steps=[step])
        graph = build_flow_graph(result)
        svg_content = generate_svg_markup(graph, query="0x123")
        self.assertIn("買入 No 200.00 股", svg_content)
        self.assertIn("US Election 2024", svg_content)

    def test_parse_polygonscan_meta(self):
        sample_html = '''
        <!doctype html>
        <html>
        <head>
          <meta name="Description" content="0x5A240948...371477d0D bought 200 No shares for $ 173.47 in Will Puma Shen win the next Taipei Mayor election? via Polymarket View on Orbscan | Success" />
        </head>
        </html>
        '''
        info = parse_polygonscan_meta(sample_html, TARGET, "0xb53c", "2026-09-24 00:08:14")
        self.assertIsNotNone(info)
        self.assertEqual(info.market_title, "Will Puma Shen win the next Taipei Mayor election?")
        self.assertEqual(info.outcome, "No")
        self.assertEqual(info.shares, "200.000000")
        self.assertEqual(info.value, "$173.47")
        self.assertIn("86.7", info.price_cents)
        self.assertEqual(info.source, "PolygonScan + Orbscan 語意解譯")

    def test_fetch_gamma_market_by_token_id_success(self):
        sample_gamma = [{
            "question": "Will Johnny Chiang win the next Taichung Mayor election?",
            "outcomes": '["Yes", "No"]',
            "clobTokenIds": f'["{TOKEN_ID}", "999999"]',
            "slug": "will-johnny-chiang-win",
            "conditionId": "0xcond123",
        }]
        import io
        import json
        mock_resp = io.BytesIO(json.dumps(sample_gamma).encode("utf-8"))
        with patch("chain_fund_tracer.orbscan.urlopen", return_value=mock_resp):
            res = fetch_gamma_market_by_token_id(str(TOKEN_ID))
            self.assertIsNotNone(res)
            self.assertEqual(res["question"], "Will Johnny Chiang win the next Taichung Mayor election?")
            self.assertEqual(res["outcome"], "Yes")

    def test_fetch_gamma_market_by_token_id_network_error(self):
        with patch("chain_fund_tracer.orbscan.urlopen", side_effect=ConnectionResetError("10054")):
            res = fetch_gamma_market_by_token_id(str(TOKEN_ID))
            self.assertIsNone(res)

    def test_fetch_orbscan_trade_with_gamma_tier(self):
        pusd_amount = 8_685_810
        shares_amount = 15_000_000
        receipt = {
            "status": "0x1",
            "logs": [
                {
                    "address": PUSD,
                    "topics": [TRANSFER_TOPIC, pad_address(TARGET), pad_address(EXCHANGE)],
                    "data": hex(pusd_amount),
                    "logIndex": "0xa",
                },
                {
                    "address": POLYMARKET_CONDITIONAL_TOKENS,
                    "topics": [TRANSFER_SINGLE_TOPIC, pad_address(EXCHANGE), pad_address(EXCHANGE), pad_address(TARGET)],
                    "data": "0x" + uint256_hex(TOKEN_ID) + uint256_hex(shares_amount),
                    "logIndex": "0xb",
                },
            ],
        }

        with patch("chain_fund_tracer.orbscan.parse_orbscan_response", return_value=None), \
             patch("chain_fund_tracer.orbscan.fetch_gamma_market_by_token_id", return_value={
                 "question": "Trump Putin and Xi seen together before 2027?",
                 "outcome": "Yes",
             }):
            info = fetch_orbscan_trade(
                tx_hash="0xabc",
                target_address=TARGET,
                api_url="https://data-api.polymarket.com/trades",
                receipt=receipt,
                timestamp="2026-09-23 16:00:00",
            )
            self.assertIsNotNone(info)
            self.assertEqual(info.market_title, "Trump Putin and Xi seen together before 2027?")
            self.assertEqual(info.outcome, "Yes")
            self.assertEqual(info.source, "Polymarket Gamma API")


if __name__ == "__main__":
    unittest.main()
