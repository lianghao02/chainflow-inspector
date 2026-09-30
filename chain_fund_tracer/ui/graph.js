/**
 * Chain Fund Tracer - 可互動 SVG 資金流程圖 (graph.js)
 * 核心升級：
 * 1. 節點唯一鍵值改為 `chain_id:address`，防止跨鏈地址與不同角色混淆。
 * 2. 建立紫色「Relay Request 跨鏈配對節點」，將來源鏈實體轉帳與目的鏈撥付用跨鏈配對雙線完整串接，杜絕斷線視覺假象。
 * 3. 協定內部事件（pUSD 鑄造、下注買賣等）附掛於 Proxy 下游，不平行割裂。
 * 4. 拓撲分層動態排版（Topological Layered Layout）＋文字錯位防疊＋視野自動自適應（fitToView）。
 */

class FlowGraph {
  constructor(svgElement, onSelectCallback) {
    this.svg = svgElement;
    this.onSelect = onSelectCallback || (() => {});
    this.steps = [];
    this.filter = 'verified'; // 'verified' | 'all' | 'principal' | 'relay' | 'pool' | 'internal' | 'outflow'

    // ViewBox 與平移縮放狀態
    this.viewBox = { x: 0, y: 0, w: 1100, h: 600 };
    this.isPanning = false;
    this.startPoint = { x: 0, y: 0 };

    this.selectedEdgeKey = null;
    this.initEvents();
  }

  initEvents() {
    this.svg.addEventListener('mousedown', (e) => {
      if (e.target === this.svg || e.target.tagName === 'svg' || e.target.id === 'graphRoot') {
        this.isPanning = true;
        this.startPoint = { x: e.clientX, y: e.clientY };
      }
    });

    window.addEventListener('mousemove', (e) => {
      if (!this.isPanning) return;
      const dx = (e.clientX - this.startPoint.x) * (this.viewBox.w / this.svg.clientWidth);
      const dy = (e.clientY - this.startPoint.y) * (this.viewBox.h / this.svg.clientHeight);
      this.viewBox.x -= dx;
      this.viewBox.y -= dy;
      this.startPoint = { x: e.clientX, y: e.clientY };
      this.updateViewBox();
    });

    window.addEventListener('mouseup', () => {
      this.isPanning = false;
    });

    this.svg.addEventListener('wheel', (e) => {
      e.preventDefault();
      const zoomFactor = e.deltaY > 0 ? 1.1 : 0.9;
      const mouseX = e.offsetX * (this.viewBox.w / this.svg.clientWidth) + this.viewBox.x;
      const mouseY = e.offsetY * (this.viewBox.h / this.svg.clientHeight) + this.viewBox.y;

      const newW = this.viewBox.w * zoomFactor;
      const newH = this.viewBox.h * zoomFactor;

      this.viewBox.x = mouseX - (mouseX - this.viewBox.x) * zoomFactor;
      this.viewBox.y = mouseY - (mouseY - this.viewBox.y) * zoomFactor;
      this.viewBox.w = newW;
      this.viewBox.h = newH;
      this.updateViewBox();
    }, { passive: false });
  }

  updateViewBox() {
    this.svg.setAttribute('viewBox', `${this.viewBox.x} ${this.viewBox.y} ${this.viewBox.w} ${this.viewBox.h}`);
  }

  fitToView(nodes) {
    if (!nodes || nodes.size === 0) {
      this.viewBox = { x: 0, y: 0, w: 1100, h: 600 };
      this.updateViewBox();
      return;
    }

    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;

    nodes.forEach((node) => {
      if (node.x < minX) minX = node.x;
      if (node.x > maxX) maxX = node.x;
      if (node.y < minY) minY = node.y;
      if (node.y > maxY) maxY = node.y;
    });

    const graphW = maxX - minX;
    const graphH = maxY - minY;

    const padX = 180;
    const padY = 140;
    const targetW = Math.max(graphW + padX * 2, 850);
    const targetH = Math.max(graphH + padY * 2, 540);

    this.viewBox.w = targetW;
    this.viewBox.h = targetH;
    this.viewBox.x = minX - (targetW - graphW) / 2;
    this.viewBox.y = minY - (targetH - graphH) / 2;
    this.updateViewBox();
  }

  setFilter(filterName) {
    this.filter = filterName;
    this.render();
  }

  setData(steps) {
    this.steps = steps || [];
    this.selectedEdgeKey = null;
    const nodes = this.render();
    this.fitToView(nodes);
  }

  selectStepByObject(stepObj) {
    if (!stepObj) return;
    this.selectedEdgeKey = `${stepObj.tx_hash}_${stepObj.from_address}`;
    this.render();
  }

  isStepVisible(step) {
    if (this.filter === 'all') return true;
    const cat = step.path_category || '';
    const style = step.line_style || 'solid';

    if (this.filter === 'verified') {
      const verifiedPrincipal = style === 'solid' && step.pair_verified === true && step.event_role !== '手續費供資';
      const verifiedRelay = cat === '跨鏈橋／Relay' && step.pair_verified === true;
      const exchangeCandidate = cat === '交易所直提' || step.classification === '交易所' || step.classification === 'VASP';
      return verifiedPrincipal || verifiedRelay || exchangeCandidate;
    }
    if (this.filter === 'principal') {
      return style === 'solid' && step.pair_verified === true && step.event_role !== '手續費供資';
    }
    if (this.filter === 'relay') {
      return cat === '跨鏈橋／Relay' || Boolean(step.relay_request_id);
    }
    if (this.filter === 'pool') {
      return style === 'dashed' || style === 'dotted';
    }
    if (this.filter === 'internal') {
      return cat === 'Polymarket 平台內部回款／贖回' || step.path_role === '內部';
    }
    if (this.filter === 'outflow') {
      return (step.direction || '').includes('出金') || step.path_role === '出金';
    }
    return true;
  }

  render() {
    this.svg.textContent = ''; // 清空畫布

    // 建立箭頭標記
    const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
    defs.innerHTML = `
      <marker id="arrow-solid" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 1 L 10 5 L 0 9 z" fill="#38bdf8"/>
      </marker>
      <marker id="arrow-dashed" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 1 L 10 5 L 0 9 z" fill="#94a3b8"/>
      </marker>
      <marker id="arrow-amber" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 1 L 10 5 L 0 9 z" fill="#fbbf24"/>
      </marker>
      <marker id="arrow-purple" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 1 L 10 5 L 0 9 z" fill="#c084fc"/>
      </marker>
      <marker id="arrow-relay-paired" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 L 3 5 z" fill="#c084fc"/>
      </marker>
      <marker id="arrow-selected" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M 0 1 L 10 5 L 0 9 z" fill="#ffffff"/>
      </marker>
    `;
    this.svg.appendChild(defs);

    const rootG = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    rootG.id = 'graphRoot';
    this.svg.appendChild(rootG);

    if (!this.steps || this.steps.length === 0) {
      const emptyText = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      emptyText.setAttribute('x', '500');
      emptyText.setAttribute('y', '300');
      emptyText.setAttribute('text-anchor', 'middle');
      emptyText.setAttribute('fill', '#64748b');
      emptyText.setAttribute('font-size', '14');
      emptyText.textContent = '尚無分析步驟資料，請由左側輸入地址或雜湊開始查詢。';
      rootG.appendChild(emptyText);
      return new Map();
    }

    const visibleSteps = this.steps.filter((s) => this.isStepVisible(s));
    if (visibleSteps.length === 0) {
      const emptyText = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      emptyText.setAttribute('x', '500');
      emptyText.setAttribute('y', '300');
      emptyText.setAttribute('text-anchor', 'middle');
      emptyText.setAttribute('fill', '#64748b');
      emptyText.setAttribute('font-size', '14');
      emptyText.textContent = '目前篩選條件下無符合之金流步驟。';
      rootG.appendChild(emptyText);
      return new Map();
    }

    // =========================================================================
    // 構建拓撲節點與邊（含 Relay Request 虛擬配對節點串接）
    // =========================================================================

    const nodes = new Map(); // nodeId -> NodeObject
    const edges = [];        // EdgeObject: { fromNode, toNode, label, style, color, marker, step, isBridgeLeg }

    // 建立 Relay 請求分組
    const relayGroups = new Map();
    visibleSteps.forEach((s) => {
      if (s.relay_request_id && s.pair_verified) {
        if (!relayGroups.has(s.relay_request_id)) {
          relayGroups.set(s.relay_request_id, { sources: [], destinations: [] });
        }
        const grp = relayGroups.get(s.relay_request_id);
        if (s.relay_leg === 'source') grp.sources.push(s);
        else grp.destinations.push(s);
      }
    });

    function getChainName(chainId) {
      const cid = parseInt(chainId, 10);
      if (cid === 56) return 'BNB Chain';
      if (cid === 137) return 'Polygon';
      if (cid === 1) return 'Ethereum';
      if (cid === 42161) return 'Arbitrum';
      if (cid === 10) return 'Optimism';
      if (cid === 8453) return 'Base';
      if (cid === 728126428) return 'TRON';
      return cid ? `Chain ${cid}` : 'Polygon';
    }

    // 1. 登記 Relay Request 配對節點
    relayGroups.forEach((grp, reqId) => {
      const relayNodeId = `relay:${reqId}`;
      nodes.set(relayNodeId, {
        id: relayNodeId,
        label: 'Relay 跨鏈配對',
        subLabel: `${reqId.slice(0, 8)}... (已唯一配對)`,
        chain: 'Relay Protocol',
        chainId: 0,
        classification: 'RelayPair',
        category: '跨鏈橋／Relay',
        isRelayNode: true,
        rank: 2, // 拓撲中間 rank
        step: grp.destinations[0] || grp.sources[0],
      });
    });

    // 2. 處理每個 Step 並生成 Node 與 Edge
    visibleSteps.forEach((step) => {
      const fromAddr = (step.from_address || 'unknown_from').toLowerCase();
      const toAddr = (step.to_address || 'unknown_to').toLowerCase();
      const fromChainId = step.chain_id || 137;
      const toChainId = (step.direction.includes('Relay 來源鏈') && step.chain_id) ? step.chain_id : 137;

      const fromNodeId = `${fromChainId}:${fromAddr}`;
      const toNodeId = `${toChainId}:${toAddr}`;

      // 註冊來源節點
      if (!nodes.has(fromNodeId)) {
        nodes.set(fromNodeId, {
          id: fromNodeId,
          address: fromAddr,
          label: step.label || fromAddr.slice(0, 8) + '...',
          subLabel: `${fromAddr.slice(0, 6)}...${fromAddr.slice(-4)}`,
          chain: getChainName(fromChainId),
          chainId: fromChainId,
          classification: step.classification,
          category: step.path_category,
          hop: step.hop,
          eventRole: step.event_role,
        });
      }

      // 註冊目標節點
      if (!nodes.has(toNodeId)) {
        const isTargetProxy = (step.hop === 1 && step.path_role === '入金') || step.classification === '目標錢包';
        nodes.set(toNodeId, {
          id: toNodeId,
          address: toAddr,
          label: isTargetProxy ? 'Polymarket 目標錢包' : toAddr.slice(0, 8) + '...',
          subLabel: `${toAddr.slice(0, 6)}...${toAddr.slice(-4)}`,
          chain: getChainName(toChainId),
          chainId: toChainId,
          classification: isTargetProxy ? '目標錢包' : '一般地址',
          category: isTargetProxy ? '目標' : '內部',
          hop: Math.max(0, (step.hop || 1) - 1),
          eventRole: step.event_role,
        });
      }

      // 判斷是否屬於已配對的 Relay 跨鏈路徑
      if (step.relay_request_id && step.pair_verified) {
        const relayNodeId = `relay:${step.relay_request_id}`;

        if (step.relay_leg === 'source') {
          // 來源鏈：來源錢包 ──[實線]──> Relay Request 節點
          edges.push({
            from: fromNodeId,
            to: relayNodeId,
            amount: step.amount,
            token: `${step.token} (${getChainName(fromChainId)})`,
            style: 'solid',
            color: '#38bdf8',
            marker: 'arrow-solid',
            step: step,
            key: `${step.tx_hash}_${step.from_address}`,
          });
        } else {
          // 目的鏈：Relay Request 節點 ══[紫色雙線]══> Relay Solver ──[實線]──> Target Proxy
          // 建立 Request -> Solver 的跨鏈配對邊
          const bridgeEdgeKey = `paired_${step.relay_request_id}`;
          if (!edges.some((e) => e.key === bridgeEdgeKey)) {
            edges.push({
              from: relayNodeId,
              to: fromNodeId, // fromNodeId 是 Relay Solver
              amount: '已唯一配對',
              token: '跨鏈完成',
              style: 'solid',
              color: '#c084fc',
              marker: 'arrow-relay-paired',
              isBridgeLeg: true,
              step: step,
              key: bridgeEdgeKey,
            });
          }

          // 建立 Solver -> Proxy 的撥付邊
          edges.push({
            from: fromNodeId,
            to: toNodeId,
            amount: step.amount,
            token: step.token,
            style: 'solid',
            color: '#38bdf8',
            marker: 'arrow-solid',
            step: step,
            key: `${step.tx_hash}_${step.from_address}`,
          });
        }
      } else {
        // 一般實體轉帳或內部交易
        let strokeColor = '#38bdf8';
        let marker = 'arrow-solid';

        if (step.line_style === 'dashed') {
          strokeColor = '#94a3b8';
          marker = 'arrow-dashed';
        } else if (step.line_style === 'dotted') {
          strokeColor = '#64748b';
          marker = 'arrow-dashed';
        }

        if (step.path_category === '交易所直提') {
          strokeColor = '#fbbf24';
          marker = 'arrow-amber';
        } else if (step.path_category === '跨鏈橋／Relay') {
          strokeColor = '#c084fc';
          marker = 'arrow-purple';
        }

        edges.push({
          from: fromNodeId,
          to: toNodeId,
          amount: step.amount,
          token: step.token,
          style: step.line_style || 'solid',
          color: strokeColor,
          marker: marker,
          step: step,
          key: `${step.tx_hash}_${step.from_address}`,
        });
      }
    });

    // =========================================================================
    // 拓撲分層算法（Topological Layered Layout）
    // =========================================================================

    // 為節點分配 rank（X 軸 column）：
    // 0: 出資交易所 (Binance)
    // 1: 來源個人錢包 (EOA)
    // 2: Relay Request 配對節點
    // 3: Relay Solver / 目的入金通道
    // 4: 目標錢包 (Polymarket Proxy)
    // 5: 平台內部下注市場／CTF 合約
    nodes.forEach((node) => {
      if (node.isRelayNode) {
        node.rank = 2;
      } else if (node.classification === '交易所' && (node.category === '交易所直提' || node.hop >= 3)) {
        node.rank = 0;
      } else if (node.chainId !== 137 && node.classification !== '交易所') {
        node.rank = 1;
      } else if (node.label.includes('Solver') || node.category === '跨鏈橋／Relay') {
        node.rank = 3;
      } else if (node.classification === '目標錢包' || node.category === '目標') {
        node.rank = 4;
      } else if (node.classification === 'Polymarket' || node.category === '內部' || node.eventRole === '投注買賣') {
        node.rank = 5;
      } else if (node.eventRole === '手續費供資') {
        node.rank = 1; // 燃料供資排在個人錢包附近
      } else {
        // 一般依據 hop 分配
        const h = node.hop || 1;
        node.rank = Math.max(0, 4 - h);
      }
    });

    // 分組並計算坐標
    const rankGroups = new Map();
    nodes.forEach((node) => {
      const r = node.rank;
      if (!rankGroups.has(r)) rankGroups.set(r, []);
      rankGroups.get(r).push(node);
    });

    const sortedRanks = Array.from(rankGroups.keys()).sort((a, b) => a - b);
    const minRank = sortedRanks[0] || 0;
    const maxRank = sortedRanks[sortedRanks.length - 1] || 4;

    // 動態開闊佈局：保證每欄間距 290px，避免節點與連線氣泡卡片擁擠重疊
    const colSpacingX = 290;
    const nodeSpacingY = 88;
    const startX = 150;

    // 計算各欄所需的最大高度以置中對齊
    let maxColNodes = 1;
    sortedRanks.forEach((r) => {
      const cnt = rankGroups.get(r).length;
      if (cnt > maxColNodes) maxColNodes = cnt;
    });
    const totalGraphHeight = Math.max(480, maxColNodes * nodeSpacingY + 80);

    sortedRanks.forEach((r) => {
      const groupNodes = rankGroups.get(r);
      const x = startX + (r - minRank) * colSpacingX;
      const count = groupNodes.length;
      const spacingY = totalGraphHeight / (count + 1);

      groupNodes.forEach((node, i) => {
        node.x = x;
        node.y = 50 + (i + 1) * spacingY;
      });
    });

    // =========================================================================
    // 繪製連線（Edges）：平行邊曲率展開與深色氣泡卡片
    // =========================================================================

    // 預先統計每對節點之間的所有邊，以動態分離平行邊（Parallel Edges）
    const pairGroups = new Map();
    edges.forEach((edge) => {
      const pairKey = `${edge.from}->${edge.to}`;
      if (!pairGroups.has(pairKey)) {
        pairGroups.set(pairKey, []);
      }
      pairGroups.get(pairKey).push(edge);
    });

    edges.forEach((edge) => {
      const u = nodes.get(edge.from);
      const v = nodes.get(edge.to);
      if (!u || !v) return;

      const edgeG = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      edgeG.style.cursor = 'pointer';

      // 平行邊曲率展開計算
      const pairKey = `${edge.from}->${edge.to}`;
      const pairList = pairGroups.get(pairKey) || [edge];
      const pairIndex = pairList.indexOf(edge);
      const pairTotal = pairList.length;

      const dx = v.x - u.x;
      const dy = v.y - u.y;
      const dist = Math.hypot(dx, dy) || 1;

      // 垂直單位法向量 (nx, ny)
      const nx = -dy / dist;
      const ny = dx / dist;

      // 若同方向只有 1 條邊，偏移量為 0；若有多條，依序展開
      const spreadStep = 38;
      const pairOffset = pairTotal > 1 ? (pairIndex - (pairTotal - 1) / 2) * spreadStep : 0;

      // 控制點與中點
      const cx1 = u.x + dx * 0.35 + nx * pairOffset;
      const cy1 = u.y + dy * 0.35 + ny * pairOffset;
      const cx2 = u.x + dx * 0.65 + nx * pairOffset;
      const cy2 = u.y + dy * 0.65 + ny * pairOffset;
      const midX = (u.x + v.x) / 2 + nx * (pairOffset * 0.85);
      const midY = (u.y + v.y) / 2 + ny * (pairOffset * 0.85);

      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      const d = `M ${u.x} ${u.y} C ${cx1} ${cy1}, ${cx2} ${cy2}, ${v.x} ${v.y}`;
      path.setAttribute('d', d);
      path.setAttribute('fill', 'none');

      let strokeColor = edge.color;
      let marker = edge.marker;
      const isSelected = this.selectedEdgeKey === edge.key;

      if (isSelected) {
        strokeColor = '#ffffff';
        marker = 'arrow-selected';
      }

      path.setAttribute('stroke', strokeColor);

      if (edge.isBridgeLeg) {
        // 跨鏈配對紫色雙線樣式
        path.setAttribute('stroke-width', isSelected ? '4.5' : '3.2');
        path.setAttribute('stroke-dasharray', '8,4');
      } else if (edge.style === 'dashed') {
        path.setAttribute('stroke-width', isSelected ? '3.5' : '1.8');
        path.setAttribute('stroke-dasharray', '5,4');
      } else if (edge.style === 'dotted') {
        path.setAttribute('stroke-width', isSelected ? '3.5' : '1.6');
        path.setAttribute('stroke-dasharray', '2,3');
      } else {
        path.setAttribute('stroke-width', isSelected ? '3.8' : '2.4');
      }

      path.setAttribute('marker-end', `url(#${marker})`);

      // 箭頭文字氣泡卡片（含獨立深色背景氣泡，杜絕與背後線條黏連重疊）
      const labelText = edge.isBridgeLeg ? '🌉 已唯一配對（跨鏈）' : `${edge.amount} ${edge.token}`;
      const badgeG = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      badgeG.setAttribute('transform', `translate(${midX}, ${midY})`);

      // 估算文字寬度以繪製氣泡圓角矩形
      const textLen = labelText.length;
      const boxW = Math.max(textLen * 7.5 + 16, 70);
      const boxH = 22;

      const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      rect.setAttribute('x', -boxW / 2);
      rect.setAttribute('y', -boxH / 2);
      rect.setAttribute('width', boxW);
      rect.setAttribute('height', boxH);
      rect.setAttribute('rx', '4');
      rect.setAttribute('fill', isSelected ? '#1e293b' : '#0a0f1d');
      rect.setAttribute('stroke', isSelected ? '#ffffff' : strokeColor);
      rect.setAttribute('stroke-width', isSelected ? '1.5' : '1');
      rect.setAttribute('opacity', '0.94');

      const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      text.setAttribute('x', '0');
      text.setAttribute('y', '0');
      text.setAttribute('fill', isSelected ? '#ffffff' : strokeColor);
      text.setAttribute('font-size', '11');
      text.setAttribute('font-weight', '700');
      text.setAttribute('text-anchor', 'middle');
      text.setAttribute('dominant-baseline', 'central');
      text.textContent = labelText;

      badgeG.appendChild(rect);
      badgeG.appendChild(text);

      edgeG.appendChild(path);
      edgeG.appendChild(badgeG);

      edgeG.addEventListener('click', (e) => {
        e.stopPropagation();
        this.selectedEdgeKey = edge.key;
        this.render();
        if (edge.step) {
          this.onSelect(edge.step);
        }
      });

      rootG.appendChild(edgeG);
    });

    // =========================================================================
    // 繪製節點（Nodes）
    // =========================================================================

    nodes.forEach((node) => {
      const nodeG = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      nodeG.setAttribute('transform', `translate(${node.x}, ${node.y})`);
      nodeG.style.cursor = 'pointer';

      let fill = '#18202c';
      let stroke = '#3b82f6';
      let icon = '👛';
      let badgeBg = '#273444';
      let badgeText = node.chain || 'Polygon';

      if (node.isRelayNode) {
        stroke = '#c084fc';
        fill = '#2a163d';
        icon = '🌉';
        badgeBg = '#581c87';
        badgeText = 'Relay Request';
      } else if (node.classification === '交易所' || node.category === '交易所直提') {
        stroke = '#fbbf24';
        fill = '#261c0c';
        icon = '🏛️';
        badgeBg = '#78350f';
      } else if (node.classification === 'Bridge' || node.category === '跨鏈橋／Relay') {
        stroke = '#c084fc';
        fill = '#231535';
        icon = '🌉';
        badgeBg = '#581c87';
      } else if (node.classification === 'Polymarket') {
        stroke = '#38bdf8';
        fill = '#0f2438';
        icon = '🎯';
        badgeBg = '#0369a1';
      } else if (node.classification === '目標錢包') {
        stroke = '#34d399';
        fill = '#0a2618';
        icon = '⭐';
        badgeBg = '#065f46';
      }

      // 卡片外框
      const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      rect.setAttribute('x', '-75');
      rect.setAttribute('y', '-26');
      rect.setAttribute('width', '150');
      rect.setAttribute('height', '52');
      rect.setAttribute('rx', '6');
      rect.setAttribute('fill', fill);
      rect.setAttribute('stroke', stroke);
      rect.setAttribute('stroke-width', node.isRelayNode ? '2.5' : '1.5');
      if (node.isRelayNode) {
        rect.setAttribute('stroke-dasharray', '6,3');
      }
      nodeG.appendChild(rect);

      // 鏈別徽章 (右上角)
      const badgeRect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      badgeRect.setAttribute('x', '10');
      badgeRect.setAttribute('y', '-22');
      badgeRect.setAttribute('width', '60');
      badgeRect.setAttribute('height', '13');
      badgeRect.setAttribute('rx', '3');
      badgeRect.setAttribute('fill', badgeBg);
      nodeG.appendChild(badgeRect);

      const badgeLabel = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      badgeLabel.setAttribute('x', '40');
      badgeLabel.setAttribute('y', '-13');
      badgeLabel.setAttribute('fill', '#f0f6fc');
      badgeLabel.setAttribute('font-size', '8');
      badgeLabel.setAttribute('font-weight', '600');
      badgeLabel.setAttribute('text-anchor', 'middle');
      badgeLabel.textContent = badgeText.slice(0, 10);
      nodeG.appendChild(badgeLabel);

      // 節點標題文字
      const textTitle = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      textTitle.setAttribute('x', '-65');
      textTitle.setAttribute('y', '-6');
      textTitle.setAttribute('fill', '#f0f6fc');
      textTitle.setAttribute('font-size', '11');
      textTitle.setAttribute('font-weight', '700');
      textTitle.textContent = `${icon} ${node.label.slice(0, 12)}`;
      nodeG.appendChild(textTitle);

      // 節點副標 (地址或狀態)
      const textSub = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      textSub.setAttribute('x', '-65');
      textSub.setAttribute('y', '14');
      textSub.setAttribute('fill', '#94a3b8');
      textSub.setAttribute('font-size', '9');
      textSub.setAttribute('font-family', 'var(--font-mono)');
      textSub.textContent = node.subLabel || '';
      nodeG.appendChild(textSub);

      nodeG.addEventListener('click', (e) => {
        e.stopPropagation();
        if (node.step) {
          this.selectedEdgeKey = `${node.step.tx_hash}_${node.step.from_address}`;
          this.render();
          this.onSelect(node.step);
        }
      });

      rootG.appendChild(nodeG);
    });

    return nodes;
  }
}
