import unittest

from chain_fund_tracer.flow_graph import bridge_elapsed, build_case_summary, build_flow_graph, ordered_edges, visible_edges
from chain_fund_tracer.models import AnalysisResult, TraceStep


class FlowGraphTests(unittest.TestCase):
    def test_graph_separates_inbound_and_outbound_lanes(self):
        target = "0x" + "a" * 40
        source = "0x" + "b" * 40
        relay = "0x" + "c" * 40
        result = AnalysisResult(query=target, steps=[
            TraceStep("地址入金", 1, "0x" + "1" * 64, "", "pUSD", "72.9", source, target, source, "未知地址", "", "無公開標籤", "未知", "僅資金關聯"),
            TraceStep("Relay 出金", 1, "0x" + "2" * 64, "", "USDC.e", "64.0", target, relay, relay, "Bridge", "Relay Depository", "Relay 公開索引", "已確認", "僅資金關聯", path_role="出金", event_role="跨鏈轉出"),
        ])
        graph = build_flow_graph(result)
        self.assertEqual({edge.lane for edge in graph.edges}, {"入金", "出金"})
        self.assertEqual(len(visible_edges(graph, ["出金"])), 1)
        self.assertTrue(any(node.is_target for node in graph.nodes.values()))

    def test_internal_transfer_uses_internal_style(self):
        zero = "0x" + "0" * 40
        target = "0x" + "a" * 40
        step = TraceStep("pUSD 鑄造", 1, "0x" + "3" * 64, "", "pUSD", "1", zero, target, zero, "協定事件", "零地址", "內建", "已確認", "僅資金關聯", path_role="內部", event_role="鑄造")
        graph = build_flow_graph(AnalysisResult(query=target, steps=[step]))
        self.assertEqual(graph.edges[0].style, "internal")

    def test_edges_are_ordered_by_lane_then_time(self):
        target = "0x" + "a" * 40
        source = "0x" + "b" * 40
        result = AnalysisResult(query=target, steps=[
            TraceStep("較晚入金", 1, "0x" + "1" * 64, "2026-09-23 08:07:32 +0800", "USDT（BNB Chain）", "72.9", source, target, source, "未知地址", "", "無", "未知", "僅資金關聯"),
            TraceStep("較早入金", 1, "0x" + "2" * 64, "2026-09-23 08:03:46 +0800", "BNB（BNB Chain）", "0.09", source, target, source, "交易所", "Binance", "公開標籤", "高度可能", "僅資金關聯"),
        ])
        graph = build_flow_graph(result)
        ordered = ordered_edges(graph, ["入金"])
        self.assertEqual([edge.direction for edge in ordered], ["較早入金", "較晚入金"])

    def test_bridge_elapsed_uses_source_and_destination_timestamps(self):
        target = "0x" + "a" * 40
        source = "0x" + "b" * 40
        result = AnalysisResult(query=target, steps=[
            TraceStep("Relay 來源鏈", 3, "0x" + "1" * 64, "2026-09-23 08:07:44 +0800", "USDT（BNB Chain）", "72.9", source, target, source, "外部錢包", "Relay來源", "Relay", "已確認", "僅資金關聯"),
            TraceStep("Relay 目的鏈補款", 3, "0x" + "2" * 64, "2026-09-23 08:07:47 +0800", "USDC.e", "72.7", source, target, source, "Bridge", "Relay Solver", "Explorer", "高度可能", "僅資金關聯"),
        ])
        for step, leg in zip(result.steps, ("source", "destination")):
            step.relay_request_id, step.relay_leg, step.pair_verified = "request-1", leg, True
        graph = build_flow_graph(result)
        self.assertEqual(bridge_elapsed(graph.edges[1], graph.edges), "約 3 秒")
        result.steps[0].relay_request_id = "another-request"
        self.assertEqual(bridge_elapsed(graph.edges[1], graph.edges), "")

    def test_case_summary_ends_with_target_address_when_no_polymarket_internal(self):
        target = "0x" + "a" * 40
        source = "0x" + "b" * 40
        result = AnalysisResult(query=target, steps=[
            TraceStep("Relay 來源鏈", 3, "0x" + "1" * 64, "2026-09-23 08:07:44 +0800", "USDT（BNB Chain）", "72.9", source, target, source, "外部錢包", "Relay來源", "Relay", "已確認", "僅資金關聯"),
            TraceStep("Relay 目的鏈補款", 3, "0x" + "2" * 64, "2026-09-23 08:07:47 +0800", "USDC.e", "72.7", source, target, source, "Bridge", "Relay Solver", "Explorer", "高度可能", "僅資金關聯"),
        ])
        graph = build_flow_graph(result)
        summary = build_case_summary(graph, target)
        self.assertIn("目標地址", summary.path_steps)
        self.assertEqual(summary.path_steps[-1], "目標地址")


if __name__ == "__main__":
    unittest.main()
