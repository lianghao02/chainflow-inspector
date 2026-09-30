import tempfile
import unittest
import zipfile
from pathlib import Path

from chain_fund_tracer.flow_graph import build_flow_graph
from chain_fund_tracer.models import AnalysisResult, TraceStep
from chain_fund_tracer.svg_exporter import export_svg, generate_svg_markup, xml_escape
from chain_fund_tracer.exporters import export_evidence_package


class SvgExporterTests(unittest.TestCase):
    def setUp(self):
        self.step1 = TraceStep(
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
            notes="上游提幣",
            chain="BNB Chain",
            chain_id=56,
            path_role="入金",
            event_role="轉帳",
            evidence_source="Explorer Token Transfers",
        )
        self.step2 = TraceStep(
            direction="Polymarket 投注",
            hop=1,
            tx_hash="0x" + "b" * 64,
            timestamp="2026-09-23 11:00:00 +0800",
            token="pUSD",
            amount="50.000000",
            from_address="0x" + "2" * 40,
            to_address="0x4d97dcd97ec945f40cf65f87097ace5ea0476045",
            address="0x" + "2" * 40,
            classification="Polymarket",
            label="Polymarket 買進 (BUY)",
            label_source="內建公開合約清冊",
            confidence="已確認",
            relation="直接交易",
            notes="買進 100 股",
            chain="Polygon",
            chain_id=137,
            path_role="內部",
            event_role="投注買賣",
            evidence_source="RPC Receipt 條件代幣解碼",
            trade_info={
                "action": "買進 (BUY)",
                "collateral_token": "pUSD",
                "collateral_amount": "50.000000",
                "shares": "100.000000",
                "price_per_share": "0.500000",
                "implied_probability": "50.00%",
                "token_id": "123456",
            },
        )
        self.result = AnalysisResult(
            query="0x" + "2" * 40,
            steps=[self.step1, self.step2],
            summary=["測試分析摘要"],
        )

    def test_xml_escape(self):
        self.assertEqual(xml_escape("A & B < C > 'D' \"E\""), "A &amp; B &lt; C &gt; &#x27;D&#x27; &quot;E&quot;")
        self.assertEqual(xml_escape(None), "")

    def test_generate_svg_structure(self):
        graph = build_flow_graph(self.result)
        svg = generate_svg_markup(graph, query=self.result.query)
        self.assertTrue(svg.startswith("<svg"))
        self.assertTrue(svg.strip().endswith("</svg>"))
        self.assertIn("viewBox=", svg)
        self.assertIn("<style>", svg)
        self.assertIn("Binance", svg)
        self.assertIn("USDT", svg)
        self.assertIn("pUSD", svg)
        self.assertIn("VASP", svg)
        self.assertIn("Polymarket", svg)
        self.assertIn("資金關聯摘要", svg)

    def test_export_svg_file(self):
        with tempfile.TemporaryDirectory() as folder:
            svg_path = Path(folder) / "test.svg"
            export_svg(self.result, str(svg_path))
            self.assertTrue(svg_path.exists())
            content = svg_path.read_text(encoding="utf-8")
            self.assertIn("<svg", content)
            self.assertIn("</svg>", content)
            self.assertGreater(len(content), 500)

    def test_svg_in_evidence_package(self):
        with tempfile.TemporaryDirectory() as folder:
            pkg_path = Path(folder) / "evidence.zip"
            export_evidence_package(self.result, str(pkg_path))
            self.assertTrue(pkg_path.exists())
            with zipfile.ZipFile(pkg_path) as archive:
                namelist = archive.namelist()
                self.assertIn("flow_graph.svg", namelist)
                self.assertIn("manifest.json", namelist)
                svg_data = archive.read("flow_graph.svg").decode("utf-8")
                self.assertIn("<svg", svg_data)


if __name__ == "__main__":
    unittest.main()
