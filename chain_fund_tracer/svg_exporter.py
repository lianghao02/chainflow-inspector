from __future__ import annotations

import html
from pathlib import Path
from typing import Iterable

from .branding import PRODUCT_NAME_ZH

from .flow_graph import (
    FlowEdge,
    FlowGraph,
    FlowNode,
    ROLE_BRIDGE,
    ROLE_DEPOSIT_WALLET,
    ROLE_DEX,
    ROLE_EXCHANGE,
    ROLE_INTERMEDIATE,
    ROLE_POLYMARKET_INTERNAL,
    ROLE_RELAY_SOLVER,
    ROLE_RELAY_SOURCE,
    ROLE_ZERO_MINT,
    bridge_elapsed,
    build_case_summary,
    build_flow_graph,
    ordered_edges,
    short_address,
)
from .models import AnalysisResult
from .explanations import explain_step, plain_summary


def xml_escape(text: str | None) -> str:
    if not text:
        return ""
    return html.escape(str(text), quote=True)


def _short_tx(value: str) -> str:
    return f"{value[:10]}…{value[-8:]}" if len(value) > 22 else value


def _node_colors(node: FlowNode) -> tuple[str, str, str, str]:
    """回傳 (fill, stroke, text_color, badge_text)。"""
    if node.is_target:
        return ("#eff6ff", "#3b82f6", "#1e40af", "TARGET")
    if node.lane == "內部":
        return ("#f8fafc", "#cbd5e1", "#475569", "INTERNAL")
    if node.role == ROLE_EXCHANGE:
        return ("#fffbeb", "#f59e0b", "#92400e", "VASP")
    if node.role in (ROLE_BRIDGE, ROLE_RELAY_SOLVER, ROLE_RELAY_SOURCE):
        return ("#eef2ff", "#6366f1", "#3730a3", "BRIDGE")
    if node.role == ROLE_DEX:
        return ("#ecfdf5", "#10b981", "#065f46", "DEX")
    return ("#ffffff", "#e2e8f0", "#1e293b", "NODE")


def generate_svg_markup(
    graph: FlowGraph,
    query: str = "",
    lanes: Iterable[str] = ("入金", "內部", "出金"),
    title: str = f"{PRODUCT_NAME_ZH}資金流程圖",
    time_condition: str = "",
) -> str:
    """根據 FlowGraph 生成現代化、向量無損之 SVG 標記文字。"""
    edges = ordered_edges(graph, lanes)

    width = 820
    node_w, node_h = 340, 68
    node_x = 44
    timeline_x = node_x + node_w / 2
    ev_x, ev_w = 416, 350
    banner_x, banner_w = 28, 764

    # 第一階段：計算座標與總高度
    y = 28
    elements: list[str] = []

    # 頂部標題
    elements.append(f'<text x="{banner_x}" y="{y + 14}" class="title">{xml_escape(title)}</text>')
    if query:
        elements.append(f'<text x="{banner_x}" y="{y + 34}" class="subtitle">查詢標的：{xml_escape(query)}</text>')
    if time_condition:
        elements.append(f'<text x="{banner_x}" y="{y + 52}" class="subtitle" fill="#d97706" font-weight="bold">【歷史條件】{xml_escape(time_condition)}</text>')
        y += 70
    else:
        y += 50

    # 頂部案件摘要卡片
    summary = build_case_summary(graph, query)
    main_tx_disp = _short_tx(summary.main_tx) if summary.main_tx != "無" else "無"

    summary_lines = [
        "【資金關聯摘要（段內由舊到新）】",
    ]
    if time_condition:
        summary_lines.append(f"時間錨定：{time_condition}")
    summary_lines.extend([
        f"路徑特徵：{' → '.join(summary.path_steps)}",
        f"入金標籤關聯 Tx：{main_tx_disp}",
        f"{summary.disclaimer}",
    ])
    sum_box_h = 24 + len(summary_lines) * 20
    elements.append(f'<rect x="{banner_x}" y="{y}" width="{banner_w}" height="{sum_box_h}" rx="8" class="summary-card"/>')
    for idx, s_line in enumerate(summary_lines):
        cls = "sum-title" if idx == 0 else ("sum-disclaimer" if idx == len(summary_lines) - 1 else "sum-text")
        elements.append(f'<text x="{banner_x + 16}" y="{y + 20 + idx * 20}" class="{cls}">{xml_escape(s_line)}</text>')
    y += sum_box_h + 24

    current_lane = None
    current_chain = None
    drawn_addrs: set[tuple[str, str]] = set()
    last_target_id: tuple[str, str] | None = None
    last_target_bottom: float = 0.0

    for edge in edges:
        # 泳道切換
        if edge.lane != current_lane:
            if current_lane is not None:
                y += 24
            current_lane = edge.lane
            current_chain = None
            last_target_id = None

            lane_title = "外部入金主路徑"
            lane_cls = "lane-inbound"
            if edge.lane == "內部":
                lane_title = "Polymarket 協定內部（非外部來源）"
                lane_cls = "lane-internal"
            elif edge.lane == "出金":
                lane_title = "資金出金路徑"
                lane_cls = "lane-outbound"

            elements.append(f'<text x="{banner_x}" y="{y + 14}" class="lane-title {lane_cls}">{lane_title}</text>')
            elements.append(f'<line x1="{banner_x}" y1="{y + 22}" x2="{banner_x + banner_w}" y2="{y + 22}" class="lane-line"/>')
            y += 40

        # 鏈別切換
        if edge.chain != current_chain:
            current_chain = edge.chain
            last_target_id = None
            elements.append(f'<rect x="{node_x}" y="{y}" width="180" height="26" rx="4" class="chain-badge-bg"/>')
            elements.append(f'<text x="{node_x + 10}" y="{y + 17}" class="chain-badge-text">鏈別：{xml_escape(current_chain)}</text>')
            y += 38

        source = graph.nodes[edge.source]
        target = graph.nodes[edge.target]
        src_id = (edge.chain, source.address.lower())
        tgt_id = (edge.chain, target.address.lower())

        reuse_source = (last_target_id is not None and last_target_id == src_id)
        if reuse_source:
            arrow_top = last_target_bottom + 4
        else:
            is_src_revisit = src_id in drawn_addrs
            s_fill, s_stroke, s_text, s_badge = _node_colors(source)
            s_title = source.role + ("（同一地址再次出現）" if is_src_revisit else "")
            elements.append(
                f'<rect x="{node_x}" y="{y}" width="{node_w}" height="{node_h}" rx="6" '
                f'fill="{s_fill}" stroke="{s_stroke}" stroke-width="1.5" class="node-card"/>'
            )
            # 角色徽章 Pill
            elements.append(
                f'<rect x="{node_x + node_w - 74}" y="{y + 10}" width="64" height="18" rx="3" '
                f'fill="{s_stroke}" fill-opacity="0.15"/>'
            )
            elements.append(
                f'<text x="{node_x + node_w - 42}" y="{y + 23}" text-anchor="middle" '
                f'fill="{s_stroke}" class="role-pill">{s_badge}</text>'
            )
            elements.append(f'<text x="{node_x + 12}" y="{y + 24}" fill="{s_text}" class="node-title">{xml_escape(s_title)}</text>')
            elements.append(f'<text x="{node_x + 12}" y="{y + 50}" class="node-addr">{xml_escape(short_address(source.address))}</text>')
            drawn_addrs.add(src_id)
            arrow_top = y + node_h + 6

        # 交易事件卡片
        exp = explain_step(edge.step)
        ev_lines = [
            f"{edge.token}  {edge.amount or '金額未取得'}",
            edge.timestamp or "時間未取得",
            f"Tx：{_short_tx(edge.tx_hash)}" if edge.tx_hash else "Tx：未取得",
            f"[{exp.badge}]",
        ]
        if edge.step.trade_info:
            ti = edge.step.trade_info
            side = ti.get("action_label") or ti.get("action") or "買入"
            outcome = ti.get("outcome") or ""
            shares = ti.get("shares") or ""
            price = ti.get("price_per_share") or ""
            market = ti.get("market_title") or ""

            line_parts = [side]
            if outcome:
                line_parts.append(outcome)
            if shares and shares != "0":
                line_parts.append(f"{shares} 股")
            if price and price != "0":
                line_parts.append(f"@{price}¢")
            ev_lines.append(" ".join(line_parts))
            if market:
                short_mkt = market if len(market) <= 24 else market[:22] + "..."
                ev_lines.append(f"標的：{short_mkt}")

        elapsed = bridge_elapsed(edge, edges) if edge.step.relay_leg == "destination" else ""
        if elapsed:
            ev_lines.append(f"跨鏈時間戳差：{elapsed}")

        ev_h = 16 + len(ev_lines) * 19
        ev_fill = "#f8fafc" if edge.lane == "內部" else "#ffffff"
        elements.append(
            f'<rect x="{ev_x}" y="{arrow_top}" width="{ev_w}" height="{ev_h}" rx="6" '
            f'fill="{ev_fill}" stroke="#e2e8f0" stroke-width="1" class="ev-card"/>'
        )
        for idx, line in enumerate(ev_lines):
            cls = "ev-amount" if idx == 0 else ("ev-badge" if idx == 3 else "ev-detail")
            elements.append(f'<text x="{ev_x + 12}" y="{arrow_top + 18 + idx * 19}" class="{cls}">{xml_escape(line)}</text>')

        arrow_bottom = max(arrow_top + 90, arrow_top + ev_h + 12)
        arrow_color = "#3b82f6" if edge.style == "bridge" else ("#d97706" if edge.style == "dashed" else ("#7c3aed" if edge.style == "dotted" else ("#94a3b8" if edge.style == "internal" else "#10b981")))
        dash_attr = ' stroke-dasharray="2,3"' if edge.style == "dotted" else (' stroke-dasharray="6,4"' if edge.style in ("bridge", "internal", "unknown", "dashed") else "")
        marker_id = "arrow-bridge" if edge.style == "bridge" else ("arrow-internal" if edge.style == "internal" else "arrow-normal")

        # 時序箭頭
        elements.append(
            f'<line x1="{timeline_x}" y1="{arrow_top}" x2="{timeline_x}" y2="{arrow_bottom}" '
            f'stroke="{arrow_color}" stroke-width="2.5"{dash_attr} marker-end="url(#{marker_id})"/>'
        )

        # Target 節點
        target_y = arrow_bottom + 6
        is_tgt_revisit = tgt_id in drawn_addrs
        t_fill, t_stroke, t_text, t_badge = _node_colors(target)
        t_title = target.role + ("（同一地址再次出現）" if is_tgt_revisit else "")
        elements.append(
            f'<rect x="{node_x}" y="{target_y}" width="{node_w}" height="{node_h}" rx="6" '
            f'fill="{t_fill}" stroke="{t_stroke}" stroke-width="1.5" class="node-card"/>'
        )
        elements.append(
            f'<rect x="{node_x + node_w - 74}" y="{target_y + 10}" width="64" height="18" rx="3" '
            f'fill="{t_stroke}" fill-opacity="0.15"/>'
        )
        elements.append(
            f'<text x="{node_x + node_w - 42}" y="{target_y + 23}" text-anchor="middle" '
            f'fill="{t_stroke}" class="role-pill">{t_badge}</text>'
        )
        elements.append(f'<text x="{node_x + 12}" y="{target_y + 24}" fill="{t_text}" class="node-title">{xml_escape(t_title)}</text>')
        elements.append(f'<text x="{node_x + 12}" y="{target_y + 50}" class="node-addr">{xml_escape(short_address(target.address))}</text>')
        drawn_addrs.add(tgt_id)

        last_target_id = tgt_id
        last_target_bottom = target_y + node_h
        y = last_target_bottom + 26

    # 底部水印與界限說明
    elements.append(f'<line x1="{banner_x}" y1="{y}" x2="{banner_x + banner_w}" y2="{y}" stroke="#e2e8f0" stroke-width="1"/>')
    elements.append(
        f'<text x="{banner_x}" y="{y + 22}" class="footer-note">'
        f'本流程圖由 Chain Fund Tracer 自動生成，依據鏈上原始資料與公開標籤。資金關聯不等於自然人帳戶身分認定。'
        f'</text>'
    )
    total_height = int(y + 44)

    # 組合完整 SVG
    svg_header = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {total_height}" width="{width}" height="{total_height}">
<defs>
  <style>
    .title {{ font-family: 'Microsoft JhengHei UI', 'Segoe UI', sans-serif; font-size: 18px; font-weight: bold; fill: #0f172a; }}
    .subtitle {{ font-family: 'Microsoft JhengHei UI', 'Segoe UI', sans-serif; font-size: 11px; fill: #64748b; }}
    .summary-card {{ fill: #f8fafc; stroke: #cbd5e1; stroke-width: 1; }}
    .sum-title {{ font-family: 'Microsoft JhengHei UI', 'Segoe UI', sans-serif; font-size: 12px; font-weight: bold; fill: #1e293b; }}
    .sum-text {{ font-family: 'Microsoft JhengHei UI', 'Segoe UI', sans-serif; font-size: 11px; fill: #334155; }}
    .sum-disclaimer {{ font-family: 'Microsoft JhengHei UI', 'Segoe UI', sans-serif; font-size: 10px; fill: #64748b; }}
    .lane-title {{ font-family: 'Microsoft JhengHei UI', 'Segoe UI', sans-serif; font-size: 13px; font-weight: bold; }}
    .lane-inbound {{ fill: #0f172a; }}
    .lane-internal {{ fill: #64748b; }}
    .lane-outbound {{ fill: #0f172a; }}
    .lane-line {{ stroke: #e2e8f0; stroke-width: 1; }}
    .chain-badge-bg {{ fill: #eef2ff; stroke: #c7d2fe; stroke-width: 1; }}
    .chain-badge-text {{ font-family: 'Microsoft JhengHei UI', 'Segoe UI', sans-serif; font-size: 11px; font-weight: bold; fill: #4338ca; }}
    .node-title {{ font-family: 'Microsoft JhengHei UI', 'Segoe UI', sans-serif; font-size: 11px; font-weight: bold; }}
    .node-addr {{ font-family: 'Cascadia Mono', Consolas, monospace; font-size: 10px; fill: #64748b; }}
    .role-pill {{ font-family: 'Segoe UI', sans-serif; font-size: 9px; font-weight: bold; }}
    .ev-amount {{ font-family: 'Microsoft JhengHei UI', 'Segoe UI', sans-serif; font-size: 12px; font-weight: bold; fill: #0f172a; }}
    .ev-detail {{ font-family: 'Microsoft JhengHei UI', 'Segoe UI', sans-serif; font-size: 10px; fill: #475569; }}
    .ev-badge {{ font-family: 'Microsoft JhengHei UI', 'Segoe UI', sans-serif; font-size: 10px; font-weight: bold; fill: #2563eb; }}
    .footer-note {{ font-family: 'Microsoft JhengHei UI', 'Segoe UI', sans-serif; font-size: 10px; fill: #94a3b8; }}
  </style>
  <marker id="arrow-normal" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
    <path d="M 0 1 L 10 5 L 0 9 z" fill="#10b981" />
  </marker>
  <marker id="arrow-bridge" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
    <path d="M 0 1 L 10 5 L 0 9 z" fill="#3b82f6" />
  </marker>
  <marker id="arrow-internal" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
    <path d="M 0 1 L 10 5 L 0 9 z" fill="#94a3b8" />
  </marker>
</defs>
<rect width="{width}" height="{total_height}" fill="#f8fafc" />
"""
    return svg_header + "\n".join(elements) + "\n</svg>\n"


def export_svg(result_or_graph: AnalysisResult | FlowGraph, path: str, query: str = "") -> None:
    """將分析結果或 FlowGraph 匯出為標準向量 SVG 圖檔。"""
    time_condition = ""
    if isinstance(result_or_graph, AnalysisResult):
        graph = build_flow_graph(result_or_graph)
        query = query or result_or_graph.query
        tf = getattr(result_or_graph, "time_filter", {}) or {}
        if tf.get("cutoff_text"):
            end_blk = f"（區塊 <= {tf.get('end_block')}）" if tf.get("end_block") else ""
            time_condition = f"{tf.get('cutoff_text')} 之前 {end_blk}".strip()
    else:
        graph = result_or_graph
    svg_code = generate_svg_markup(graph, query=query, time_condition=time_condition)
    Path(path).write_text(svg_code, encoding="utf-8")
