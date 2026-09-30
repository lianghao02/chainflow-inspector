from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from .models import AnalysisResult, TraceStep

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
PUSD = "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb"
POLYMARKET_ADDRESSES = {
    PUSD,
    "0xe111180000d2663c0091e4f400237545b87b996b",
    "0xe2222d279d744050d28e00520010520000310f59",
    "0x93070a847efef7f70739046a929d47a521f5b8ee",
    "0x4d97dcd97ec945f40cf65f87097ace5ea0476045",
}

ROLE_EXCHANGE = "交易所 / VASP"
ROLE_INTERMEDIATE = "中間地址"
ROLE_RELAY_SOURCE = "Relay 來源地址"
ROLE_RELAY_SOLVER = "Relay Solver"
ROLE_BRIDGE = "Bridge"
ROLE_DEX = "DEX / Router"
ROLE_DEPOSIT_WALLET = "Polymarket DepositWallet"
ROLE_POLYMARKET_INTERNAL = "Polymarket 協定"
ROLE_ZERO_MINT = "零地址 / Mint"
ROLE_UNCLASSIFIED = "未分類地址"


def normalize(value: str) -> str:
    return value.lower() if value else ""


def short_address(value: str) -> str:
    return f"{value[:8]}…{value[-6:]}" if len(value) > 18 else value


def is_vasp(step: TraceStep | None) -> bool:
    """第 7 點：只有符合公開可驗證標籤之實體才判定為交易所/VASP，且排除 DEX Router。"""
    if not step:
        return False
    if step.classification in ("交易所", "VASP", "入金服務商"):
        text = step.label
        if any(kw in text for kw in ("Router", "DEX", "Swap")):
            return False
        if step.label and (
            "公開標籤" in step.label_source
            or "Explorer" in step.label_source
            or "BscScan" in step.label_source
            or "Blockscan" in step.label_source
            or "Etherscan" in step.label_source
        ):
            return True
    return False


def infer_node_role(address: str, step: TraceStep | None, query: str = "") -> tuple[str, str, str, str]:
    """統一節點角色為 10 種標準角色，並拆分角色信心與關聯信心。"""
    norm_addr = normalize(address)
    on_polygon = step is None or infer_chain(step) == "Polygon"
    if not norm_addr:
        return (ROLE_UNCLASSIFIED, "地址未取得", "未知", "未知")
    if norm_addr == ZERO_ADDRESS:
        return (ROLE_ZERO_MINT, "零地址（鑄造／燒毀）", "已確認公開標籤", "已確認移轉")

    # 分類與公開標籤只屬於 step.address，不可外溢到轉帳另一端。
    if step and norm_addr != normalize(step.address):
        step = None

    # Polymarket DepositWallet 判斷（第 9 點）
    if step and ("DepositWallet" in step.label or "DepositWallet" in step.notes or "Polymarket Deposit" in step.label):
        return (ROLE_DEPOSIT_WALLET, "Polymarket DepositWallet", "已確認合約", "高度相關")

    # Polymarket 內部協定
    if (on_polygon and norm_addr in POLYMARKET_ADDRESSES) or (step and step.classification == "Polymarket"):
        lbl = step.label if (step and step.label and step.label != "Polymarket") else "Polymarket 協定合約"
        return (ROLE_POLYMARKET_INTERNAL, lbl, "已確認合約", "已確認移轉")

    # DEX / Router 判斷（第 7 點：如 Binance DEX Router 歸為 DEX / Router，非 VASP）
    if step:
        text = f"{step.classification} {step.label}"
        if any(kw in text for kw in ("DEX", "Router", "Swap", "PancakeSwap", "Uniswap")):
            return (ROLE_DEX, step.label or "DEX / Router 合約", "已確認合約", "高度相關")

    # Relay Solver
    if step and "Solver" in step.label:
        return (ROLE_RELAY_SOLVER, step.label or "Relay: Solver", "已確認合約", "高度相關")

    # Bridge
    if step and (step.classification == "Bridge" or "Relay Depository" in step.label or "Relay Depository" in step.notes):
        return (ROLE_BRIDGE, step.label or "Relay Depository", "已確認合約", "高度相關")

    # 交易所 / VASP（第 7 點）
    if is_vasp(step):
        return (ROLE_EXCHANGE, step.label, "已確認公開標籤", "僅資金關聯")

    # Relay 來源地址
    if step and ("Relay 來源" in step.direction or "Relay來源鏈" in step.label or "Relay來源鏈" in step.notes):
        if norm_addr == normalize(step.from_address):
            return (ROLE_RELAY_SOURCE, "Relay 來源地址", "已確認移轉", "僅資金關聯")

    # 目標地址
    if on_polygon and norm_addr == normalize(query):
        return (ROLE_INTERMEDIATE, "目標 Polymarket 地址", "已確認地址", "高度相關")

    # 一般中繼地址（第 3 點：不再顯示未知地址|未知地址，統一為中間地址）
    if step and (step.classification in ("外部錢包", "未知地址", "") or not step.classification):
        return (ROLE_INTERMEDIATE, short_address(address), "待查證（鏈上無公開標籤）", "僅資金關聯")

    return (ROLE_UNCLASSIFIED, short_address(address), "待查證", "僅資金關聯")


@dataclass
class FlowNode:
    key: str
    address: str
    label: str
    classification: str
    confidence: str
    lane: str
    is_target: bool = False
    role: str = ROLE_INTERMEDIATE
    role_confidence: str = ""
    relation_confidence: str = ""
    public_tag: str = ""
    tag_source: str = ""
    deposit_info: dict[str, str] = field(default_factory=dict)


@dataclass
class FlowEdge:
    key: str
    source: str
    target: str
    token: str
    amount: str
    tx_hash: str
    timestamp: str
    direction: str
    lane: str
    style: str
    step: TraceStep
    chain: str = ""


@dataclass
class CaseSummary:
    vasp_name: str
    vasp_chain: str
    main_tx: str
    path_steps: list[str]
    judgment: str
    disclaimer: str


@dataclass
class FlowGraph:
    nodes: dict[str, FlowNode] = field(default_factory=dict)
    edges: list[FlowEdge] = field(default_factory=list)
    truncated: bool = False


def step_lane(step: TraceStep) -> str:
    text = f"{step.path_role} {step.direction} {step.event_role} {step.notes}"
    if any(word in text for word in ("出金", "贖回", "燒毀")):
        return "出金"
    if any(word in text for word in ("內部", "鑄造", "結算", "投注")):
        return "內部"
    return "入金"


def edge_style(step: TraceStep, lane: str) -> str:
    if getattr(step, "line_style", "") in ("dashed", "dotted"):
        return step.line_style
    addresses = {normalize(step.from_address), normalize(step.to_address)}
    if step.classification == "Bridge" or "Relay" in step.direction:
        return "bridge"
    if ZERO_ADDRESS in addresses or PUSD in addresses or lane == "內部":
        return "internal"
    if step.confidence == "未知" or step.relation == "未知":
        return "unknown"
    return "confirmed"



def node_identity(lane: str, address: str, chain: str = "") -> str:
    return f"{chain}:{lane}:{normalize(address)}"


def node_metadata(step: TraceStep, address: str, query: str, lane: str) -> FlowNode:
    role, role_label, role_conf, rel_conf = infer_node_role(address, step, query)
    is_source = normalize(address) == normalize(step.address)
    public_tag = step.label if (is_source and step.label and step.label != step.classification) else ""
    tag_source = step.label_source if is_source else ""
    is_target_addr = infer_chain(step) == "Polygon" and normalize(address) == normalize(query)

    deposit_info = {}
    if role == ROLE_DEPOSIT_WALLET or (step.deposit_info and is_target_addr):
        deposit_info = getattr(step, "deposit_info", {}) or {
            "Contract": address,
            "owner()": "未取得",
            "factory()": "未取得",
            "id()": "未取得",
            "是否 Proxy": "未取得",
            "Implementation": "未取得",
        }

    return FlowNode(
        key=node_identity(lane, address, infer_chain(step)),
        address=address,
        label=role_label or short_address(address),
        classification=step.classification if is_source else role,
        confidence=step.confidence if is_source else role_conf,
        lane=lane,
        is_target=is_target_addr,
        role=role,
        role_confidence=role_conf,
        relation_confidence=rel_conf,
        public_tag=public_tag,
        tag_source=tag_source,
        deposit_info=deposit_info,
    )


def infer_chain(step: TraceStep) -> str:
    if step.chain:
        return step.chain
    text = f"{step.token} {step.notes} {step.direction}"
    if "BNB Chain" in text or "BNB（" in text:
        return "BNB Chain"
    if "Base" in text:
        return "Base"
    if "Tron" in text or "TRON" in text or "TRC-20" in text:
        return "Tron"
    return "Polygon"


def timestamp_value(value: str) -> float:
    if not value:
        return float("inf")
    cleaned = value.strip().replace("Z", "+00:00")
    for parser in (
        lambda: datetime.fromisoformat(cleaned).timestamp(),
        lambda: datetime.strptime(cleaned, "%Y-%m-%d %H:%M:%S %z").timestamp(),
    ):
        try:
            return parser()
        except ValueError:
            continue
    return float("inf")


def elapsed_label(first: FlowEdge, second: FlowEdge) -> str:
    first_time, second_time = timestamp_value(first.timestamp), timestamp_value(second.timestamp)
    if first_time == float("inf") or second_time == float("inf"):
        return ""
    seconds = int(abs(second_time - first_time))
    if seconds < 60:
        return f"約 {seconds} 秒"
    minutes, remainder = divmod(seconds, 60)
    if minutes < 60:
        return f"約 {minutes} 分 {remainder} 秒"
    hours, minutes = divmod(minutes, 60)
    return f"約 {hours} 小時 {minutes} 分"


def build_flow_graph(result: AnalysisResult, max_edges: int = 80) -> FlowGraph:
    graph = FlowGraph()
    for index, step in enumerate(result.steps[:max_edges]):
        if not step.from_address or not step.to_address:
            continue
        lane = step_lane(step)
        source_key = node_identity(lane, step.from_address, infer_chain(step))
        target_key = node_identity(lane, step.to_address, infer_chain(step))
        for key, address in ((source_key, step.from_address), (target_key, step.to_address)):
            meta = node_metadata(step, address, result.query, lane)
            previous = graph.nodes.get(key)
            if previous is None or (previous.role in {ROLE_INTERMEDIATE, ROLE_UNCLASSIFIED} and meta.role not in {ROLE_INTERMEDIATE, ROLE_UNCLASSIFIED}):
                graph.nodes[key] = meta
        graph.edges.append(FlowEdge(
            key=f"edge-{index}",
            source=source_key,
            target=target_key,
            token=step.token,
            amount=step.amount,
            tx_hash=step.tx_hash,
            timestamp=step.timestamp,
            direction=step.direction,
            lane=lane,
            style=edge_style(step, lane),
            step=step,
            chain=infer_chain(step),
        ))
    graph.truncated = len(result.steps) > max_edges
    return graph


def visible_edges(graph: FlowGraph, lanes: Iterable[str]) -> list[FlowEdge]:
    allowed = set(lanes)
    return [edge for edge in graph.edges if edge.lane in allowed]


def ordered_edges(graph: FlowGraph, lanes: Iterable[str]) -> list[FlowEdge]:
    """依入金、內部、出金分段，段內再以交易時間由舊到新排列。"""
    lane_order = {"入金": 0, "內部": 1, "出金": 2}
    indexed = list(enumerate(visible_edges(graph, lanes)))
    indexed.sort(key=lambda item: (
        lane_order.get(item[1].lane, 9),
        timestamp_value(item[1].timestamp),
        item[0],
    ))
    return [edge for _index, edge in indexed]


def bridge_elapsed(edge: FlowEdge, edges: Iterable[FlowEdge]) -> str:
    """只計算同一 Request 的唯一來源／目的時間戳差，不宣稱實際處理耗時。"""
    if not edge.step.pair_verified or not edge.step.relay_request_id or edge.step.relay_leg not in {"source", "destination"}:
        return ""
    candidates = [
        candidate for candidate in edges
        if candidate.key != edge.key
        and candidate.step.pair_verified
        and candidate.step.relay_request_id == edge.step.relay_request_id
        and {candidate.step.relay_leg, edge.step.relay_leg} == {"source", "destination"}
        and candidate.step.path_role == edge.step.path_role
        and candidate.chain != edge.chain
        and timestamp_value(candidate.timestamp) != float("inf")
    ]
    if len(candidates) != 1 or timestamp_value(edge.timestamp) == float("inf"):
        return ""
    other = candidates[0]
    source, destination = (edge, other) if edge.step.relay_leg == "source" else (other, edge)
    delta = timestamp_value(destination.timestamp) - timestamp_value(source.timestamp)
    if delta < 0:
        return f"目的鏈早 {elapsed_label(source, destination)}（非處理耗時）"
    return elapsed_label(source, destination)


def build_case_summary(graph: FlowGraph, query: str) -> CaseSummary:
    """第 2 點與第 10 點：辦案導向摘要。"""
    vasp_edge = None
    for edge in graph.edges:
        if edge.step.path_role != "出金" and is_vasp(edge.step):
            vasp_edge = edge
            break

    if vasp_edge:
        vasp_name = vasp_edge.step.label or "已命中 VASP"
        vasp_chain = vasp_edge.chain or "BNB Chain"
        main_tx = vasp_edge.tx_hash
    else:
        vasp_name = "尚未命中已知公開 VASP 標籤"
        vasp_chain = "無"
        main_tx = graph.edges[0].tx_hash if graph.edges else "無"

    has_vasp = vasp_edge is not None
    first_token = "Binance" if (has_vasp and "Binance" in vasp_name) else (vasp_name.split(":")[0].strip() if has_vasp else "未知來源")

    roles_in_graph = {node.role for node in graph.nodes.values()}
    has_dex = any(ROLE_DEX in r for r in roles_in_graph)
    has_relay = any(ROLE_RELAY_SOURCE in r or ROLE_RELAY_SOLVER in r or ROLE_BRIDGE in r for r in roles_in_graph)
    has_intermediate = any(ROLE_INTERMEDIATE in r for r in roles_in_graph)
    has_polymarket = (
        any(ROLE_POLYMARKET_INTERNAL in r or ROLE_DEPOSIT_WALLET in r for r in roles_in_graph)
        or any("Polymarket" in s.direction or "pUSD" in s.token for s in [e.step for e in graph.edges])
        or "polymarket" in query.lower()
    )

    macro_steps: list[str] = [first_token]
    if has_intermediate:
        macro_steps.append("中間地址")
    if has_dex:
        macro_steps.append("DEX")
    if has_relay:
        macro_steps.append("Relay")
        macro_steps.append("Polygon")
    if has_polymarket:
        macro_steps.append("Polymarket")
    else:
        macro_steps.append("目標地址")

    judgment = "僅呈現可查得的資金關聯；節點種類不等於已證明完整同源路徑。"
    disclaimer = "本結果僅表示鏈上資金關聯，不代表已確認目標地址與該交易所帳戶屬同一自然人。"

    return CaseSummary(
        vasp_name=vasp_name,
        vasp_chain=vasp_chain,
        main_tx=main_tx,
        path_steps=list(dict.fromkeys(macro_steps)),
        judgment=judgment,
        disclaimer=disclaimer,
    )
