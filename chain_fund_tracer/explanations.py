"""離線、可重現的證據解釋模板；不由標籤猜測自然人或實際發起者。"""
from dataclasses import dataclass
from .flow_graph import is_vasp, ZERO_ADDRESS, PUSD
from .models import TraceStep


@dataclass(frozen=True)
class Explanation:
    initiator: str
    executor: str
    control: str
    action: str
    badge: str
    paragraphs: tuple[str, ...]
    levels: tuple[str, ...]

    def text(self) -> str:
        return "\n".join([
            "【這一步代表什麼？】", *self.paragraphs,
            f"發起角色：{self.initiator}", f"執行角色：{self.executor}",
            f"節點控制性：{self.control}", f"行為性質：{self.action}",
            f"證據層級：{'、'.join(self.levels)}",
        ])


def explain_step(step: TraceStep) -> Explanation:
    levels = []
    if "RPC Receipt" in step.evidence_source and step.log_index:
        levels.append("鏈上直接證據")
    elif "Explorer" in step.evidence_source:
        levels.append("鏈上轉帳索引（待原始 Log 核對）")
    if step.label and step.label_source and step.label_source not in {"無", "無公開標籤", "使用者設定"}:
        levels.append("公開標籤證據")
    if step.relay_request_id and step.pair_verified:
        levels.append("協定解析結果")
    levels.extend(["資金關聯推論", "身分待查"])
    initiator = "待查：Token From／To 不能單獨確定操作人或交易發起者。"
    executor, control, action, badge = "待解析", "未知", "資產移轉紀錄", "角色待查"
    paragraphs = [
        f"資料記錄 {step.token} {step.amount or '數量未取得'} 由 {step.from_address} 移至 {step.to_address}。",
        "地址之間的移轉不等於同一人控制；本步與前後款項是否同源仍須核對。",
    ]
    if step.from_address.lower() == ZERO_ADDRESS:
        executor, control, action, badge = "代幣合約", "智能合約自動執行", "鑄造事件", "協定鑄造"
        paragraphs = [
            f"紀錄以零地址為來源，表示新增 {step.amount or '待解析'} {step.token} 給收款地址，不是零地址匯款。",
            "外部資金來源須另查同筆交易的底層資產流入；這個事件不能辨識刷卡、交易所或付款人。",
        ]
    elif step.to_address.lower() == ZERO_ADDRESS:
        executor, control, action, badge = "代幣合約", "智能合約自動執行", "燒毀事件", "協定燒毀"
        paragraphs = ["代幣移至零地址是燒毀事件，不代表匯入某人的錢包。", "是否另有贖回入帳，須查看同筆及相關交易。"]
    elif step.relay_request_id and step.pair_verified:
        executor, control, action, badge = "Relay 跨鏈協定（依索引）", "平台／服務商控制（協定節點）", "跨鏈來源／目的配對", "跨鏈索引配對"
        paragraphs = [
            f"來源與目的交易由相同 Relay Request ID 配對：{step.relay_request_id}。",
            "兩條鏈是分別入帳與撥付，不表示同一枚代幣直接跨鏈；Solver 與 Depository 不是原始付款人的身分。",
            "若資料來源為 stateChanges，箭頭僅表達淨額變化，仍須核對目的鏈原始 Transfer Log。",
        ]
    elif getattr(step, "line_style", "") == "dashed" or "較早資金池入金" in step.direction:
        executor, control, action, badge = "入金服務商／資金池", "第三方服務商資金池", "較早資金池入金（非逐筆歸屬）", "資金池關聯"
        paragraphs = [
            f"公開鏈上資料顯示，{step.from_address}（{step.label or '服務商標籤'}）曾向中間資金池轉入 {step.amount} {step.token}。",
            "此款項進入較大之混合資金池，非逐筆唯一對應；不能確認其中哪筆資金後續用於本案。",
            "構成服務商關聯線索，但不能單憑鏈上紀錄認定特定客戶身分或證明與本案具有必然歸屬。",
        ]
    elif getattr(step, "line_style", "") == "dotted" or "原生 POL 供資" in step.direction:
        executor, control, action, badge = "交易所熱錢包／出金節點", "交易所內部調度或提幣", "原生 POL 燃料供資（非本金）", "原生幣供資"
        paragraphs = [
            f"公開標籤顯示，{step.label or 'OKX'} 曾向中間節點轉入 {step.amount} {step.token} 作為鏈上手續費燃料。",
            "原生代幣（POL）為帳戶制餘額混合（非 UTXO），無法證明本案轉帳手續費必定消耗該筆代幣。",
            "此項為燃料手續費供資關聯，非本案投注本金；不可斷定提幣人即本案涉案人。",
        ]
    elif is_vasp(step):
        executor, control, action, badge = "標籤指向之服務商；實際發起者待查", "平台／服務商控制（依公開標籤，非身分認定）", "交易所標籤地址資金往來", "服務商標籤"
        paragraphs = [
            f"本步的 {step.address} 被公開資料標記為「{step.label}」。",
            "可作為交易所資金往來線索；是否客戶提幣、入金或平台調度，須由交易所紀錄確認。",
            "不能據此認定收付款地址與交易所帳戶由同一自然人控制。",
        ]
    elif step.classification == "DEX" or any(word in step.label.lower() for word in ("dex", "router", "swap")):
        executor, control, action, badge = "DEX／Router（依標籤）", "智能合約自動執行（須核對合約）", "DEX 資產互動", "DEX 合約互動"
        paragraphs = ["這一步與 DEX／Router 標籤地址有資產往來，不等同中心化交易所帳戶提幣。", "只有轉入紀錄不足以證明完整兌換，仍需同筆交易的投入資產、輸出資產及合約事件。"]
    elif step.trade_info:
        ti = step.trade_info
        t_action = ti.get("action_label") or ti.get("action", "買進 (BUY)")
        t_outcome = ti.get("outcome", "")
        t_shares = ti.get("shares", "0")
        t_amt = ti.get("collateral_amount", "0")
        t_token = ti.get("collateral_token", "pUSD")
        t_price = ti.get("price_per_share", "0")
        t_prob = ti.get("implied_probability", "")
        t_id = ti.get("token_id", "")
        market = ti.get("market_title")
        role = ti.get("trader_role", "")
        fee = ti.get("fee", "")
        val = ti.get("value", "")
        source = ti.get("enrichment_source") or "RPC Receipt"

        prob_text = f"（隱含勝率約 {t_prob}）" if t_prob and t_prob != "0.00%" else ""
        action_name = f"Polymarket 交易：{t_action}" + (f" {t_outcome}" if t_outcome else "")
        executor, control, action, badge = "Polymarket 條件代幣撮合", "智能合約自動撮合", action_name, "投注買賣"

        paragraphs = [
            f"本步為 Polymarket 投注交易：{t_action} {t_shares} 股，金額 {t_amt} {t_token}。",
            f"成交單價約 {t_price} USDC/股{prob_text}；下注標的 Token ID: #{t_id}。",
        ]
        if market:
            paragraphs.insert(0, f"【預測市場標的】{market}")
        if t_outcome or role or fee or val:
            detail_items = []
            if t_outcome:
                detail_items.append(f"立場：{t_outcome}")
            if role:
                detail_items.append(f"角色：{role}")
            val_clean = str(val).lstrip("$")
            if val_clean and val_clean != "0.00":
                detail_items.append(f"總值：${val_clean}")
            if fee and fee != "0.00":
                detail_items.append(f"手續費：{fee}")
            paragraphs.append(f"【交易語意解譯（{source}）】" + "｜".join(detail_items))
        paragraphs.append("註：鏈上底層扣款已由 Polygon RPC 核實；市場標的與交易細節由 Polymarket/Orbscan 補充解譯。")

        if "鏈上直接證據" not in levels:
            levels.insert(0, "鏈上直接證據")
        if source and "語意解譯" not in "".join(levels):
            levels.append(f"語意解譯（{source}）")
    elif step.classification == "Polymarket" or PUSD in {step.from_address.lower(), step.to_address.lower()}:
        executor, control, action, badge = "Polymarket 協定（依合約清冊）", "智能合約自動執行", "平台資產互動", "協定事件"
        paragraphs = ["這一步是與 Polymarket 協定的資產互動，不直接代表外部入金或交易所出金。", "買入／賣出、YES／NO、Shares 與費用須另核對成交事件及 Token ID；未解析者一律待解析。"]
    elif step.classification == "Bridge":
        executor, control, action, badge = "Bridge（依標籤）", "平台／服務商控制（依標籤）", "跨鏈服務互動候選", "跨鏈待配對"
        paragraphs = ["此轉帳與跨鏈服務標籤地址有關。", "尚無精確 Request 配對時，不以相近時間或金額連接另一條鏈。"]
    if "後續轉出候選" in step.direction:
        paragraphs.append("這是入帳後的轉出候選，可能混有原有餘額，不表示已證明同一筆資金轉入交易所。")
    return Explanation(initiator, executor, control, action, badge, tuple(paragraphs), tuple(dict.fromkeys(levels)))


def plain_summary(steps: list[TraceStep]) -> str:
    incoming = sorted({s.label for s in steps if s.path_role != "出金" and is_vasp(s)})
    outgoing = sorted({s.label for s in steps if s.path_role == "出金" and is_vasp(s)})
    requests = {s.relay_request_id for s in steps if s.pair_verified and s.relay_request_id}
    return (f"入金資料中的交易所標籤：{'、'.join(incoming) or '尚未命中'}。"
            f"出金資料中的交易所標籤：{'、'.join(outgoing) or '尚未命中'}。"
            f"已保留 {len(requests)} 個精確配對的 Relay Request；上述標籤與配對仍不足以單獨證明完整同源閉環或自然人身分。")
