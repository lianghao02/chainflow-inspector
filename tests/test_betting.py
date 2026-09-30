import unittest
from chain_fund_tracer.betting import (
    BetTrade,
    decode_polymarket_trade,
    TRANSFER_TOPIC,
    TRANSFER_SINGLE_TOPIC,
    TRANSFER_BATCH_TOPIC,
    POLYMARKET_CONDITIONAL_TOKENS,
    PUSD,
    ZERO_ADDRESS,
)

TARGET = "0x5A2409487d0a03ecbE444c8784b0EFc371477d0D".lower()
EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E".lower()
TOKEN_ID = 1008075377317019671629813133649514785465922378931293817112093787123987123


def pad_address(addr: str) -> str:
    return "0x" + "0" * 24 + addr.lower().removeprefix("0x")


def uint256_hex(val: int) -> str:
    return f"{val:064x}"


class BettingDecoderTests(unittest.TestCase):
    def test_buy_trade_decoding(self):
        # 目標地址轉出 8.685810 pUSD，收到 15.000000 股條件代幣
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

        trade = decode_polymarket_trade(receipt, TARGET, tx_hash="0x" + "1" * 64, timestamp="2026-09-23 16:00:00 +0800")
        self.assertIsNotNone(trade)
        self.assertEqual(trade.action, "買進 (BUY)")
        self.assertEqual(trade.collateral_token, "pUSD")
        self.assertEqual(trade.collateral_amount, "8.685810")
        self.assertEqual(trade.shares, "15.000000")
        self.assertEqual(trade.price_per_share, "0.579054")
        self.assertEqual(trade.implied_probability, "57.91%")
        self.assertEqual(trade.token_id, str(TOKEN_ID))
        self.assertIn("買進 (BUY)", trade.summary_text())
        self.assertIn("15.000000 股", trade.summary_text())

    def test_sell_trade_decoding(self):
        # 目標地址交出 10.000000 股條件代幣，收回 6.500000 pUSD
        pusd_amount = 6_500_000
        shares_amount = 10_000_000

        receipt = {
            "status": "0x1",
            "logs": [
                {
                    "address": POLYMARKET_CONDITIONAL_TOKENS,
                    "topics": [TRANSFER_SINGLE_TOPIC, pad_address(EXCHANGE), pad_address(TARGET), pad_address(EXCHANGE)],
                    "data": "0x" + uint256_hex(TOKEN_ID) + uint256_hex(shares_amount),
                    "logIndex": "0x1",
                },
                {
                    "address": PUSD,
                    "topics": [TRANSFER_TOPIC, pad_address(EXCHANGE), pad_address(TARGET)],
                    "data": hex(pusd_amount),
                    "logIndex": "0x2",
                },
            ],
        }

        trade = decode_polymarket_trade(receipt, TARGET)
        self.assertIsNotNone(trade)
        self.assertEqual(trade.action, "賣出 (SELL)")
        self.assertEqual(trade.collateral_amount, "6.500000")
        self.assertEqual(trade.shares, "10.000000")
        self.assertEqual(trade.price_per_share, "0.650000")
        self.assertEqual(trade.implied_probability, "65.00%")

    def test_redemption_trade_decoding(self):
        # 勝選兌現：目標地址將 64.062883 股代幣銷毀至 0x0，收回 64.062883 pUSD
        amount = 64_062_883

        receipt = {
            "status": "0x1",
            "logs": [
                {
                    "address": POLYMARKET_CONDITIONAL_TOKENS,
                    "topics": [TRANSFER_SINGLE_TOPIC, pad_address(TARGET), pad_address(TARGET), pad_address(ZERO_ADDRESS)],
                    "data": "0x" + uint256_hex(TOKEN_ID) + uint256_hex(amount),
                    "logIndex": "0x5",
                },
                {
                    "address": PUSD,
                    "topics": [TRANSFER_TOPIC, pad_address(EXCHANGE), pad_address(TARGET)],
                    "data": hex(amount),
                    "logIndex": "0x6",
                },
            ],
        }

        trade = decode_polymarket_trade(receipt, TARGET)
        self.assertIsNotNone(trade)
        self.assertEqual(trade.action, "勝選兌現 (REDEEM)")
        self.assertEqual(trade.collateral_amount, "64.062883")
        self.assertEqual(trade.shares, "64.062883")
        self.assertEqual(trade.price_per_share, "1.000000")
        self.assertIn("勝選兌現", trade.summary_text())

    def test_non_target_address_is_ignored(self):
        # 與目標地址無關的交易不應被解析
        other_user = "0x" + "9" * 40
        receipt = {
            "status": "0x1",
            "logs": [
                {
                    "address": PUSD,
                    "topics": [TRANSFER_TOPIC, pad_address(other_user), pad_address(EXCHANGE)],
                    "data": hex(10_000_000),
                },
            ],
        }
        self.assertIsNone(decode_polymarket_trade(receipt, TARGET))


    def test_trade_info_explanation_and_step(self):
        from chain_fund_tracer.models import TraceStep
        from chain_fund_tracer.explanations import explain_step

        trade_dict = {
            "action": "買進 (BUY)",
            "collateral_token": "pUSD",
            "collateral_amount": "8.685810",
            "shares": "15.000000",
            "price_per_share": "0.579054",
            "implied_probability": "57.91%",
            "token_id": str(TOKEN_ID),
            "exchange_contract": EXCHANGE,
        }
        step = TraceStep(
            "Polymarket 投注", 0, "0x" + "1" * 64, "2026-09-23 16:00:00 +0800",
            "pUSD", "8.685810", TARGET, POLYMARKET_CONDITIONAL_TOKENS, TARGET,
            "Polymarket", "Polymarket 投注", "內建公開合約清冊", "已確認", "直接交易",
            "買進 15 股", chain="Polygon", log_index="10", path_role="內部", event_role="投注買賣",
            evidence_source="RPC Receipt 條件代幣解碼", trade_info=trade_dict,
        )

        explanation = explain_step(step)
        self.assertIn("鏈上直接證據", explanation.levels)
        self.assertEqual(explanation.badge, "投注買賣")
        self.assertIn("買進 (BUY) 15.000000 股", explanation.text())
        self.assertIn("0.579054 USDC/股", explanation.text())
        self.assertIn("57.91%", explanation.text())
        self.assertIn(str(TOKEN_ID), explanation.text())


if __name__ == "__main__":
    unittest.main()
