/**
 * Chain Fund Tracer - 可互動 SVG 資金流程圖 (graph.js)
 * 支援縮放、拖曳、實線/虛線/點線語義渲染、過濾器與右側卡片點選連動。
 */

class FlowGraph {
  constructor(svgElement, onSelectCallback) {
    this.svg = svgElement;
    this.onSelect = onSelectCallback || (() => {});
    this.steps = [];
    this.filter = 'all'; // 'all' | 'principal' | 'relay' | 'pool' | 'internal' | 'outflow'

    // ViewBox 與平移縮放狀態
    this.viewBox = { x: 0, y: 0, w: 1000, h: 600 };
    this.isPanning = false;
    this.startPoint = { x: 0, y: 0 };
    this.scale = 1.0;

    this.selectedStepIndex = null;
    this.initEvents();
  }

  initEvents() {
    this.svg.addEventListener('mousedown', (e) => {
      // 點擊空白處平移
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

  resetView() {
    this.viewBox = { x: 0, y: 0, w: 1100, h: 650 };
    this.updateViewBox();
  }

  setFilter(filterName) {
    this.filter = filterName;
    this.render();
  }

  setData(steps) {
    this.steps = steps || [];
    this.selectedStepIndex = null;
    this.render();
    this.resetView();
  }

  isStepVisible(step) {
    if (this.filter === 'all') return true;
    const cat = step.path_category || '';
    const style = step.line_style || 'solid';

    if (this.filter === 'principal') {
      return style === 'solid' && step.event_role !== '手續費供資';
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
      return step.direction.includes('出金') || step.path_role === '出金';
    }
    return true;
  }

  render() {
    this.svg.innerHTML = '';

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
    `;
    this.svg.appendChild(defs);

    const rootG = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    rootG.id = 'graphRoot';
    this.svg.appendChild(rootG);

    if (!this.steps || this.steps.length === 0) {
      const emptyText = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      emptyText.setAttribute('x', '550');
      emptyText.setAttribute('y', '300');
      emptyText.setAttribute('text-anchor', 'middle');
      emptyText.setAttribute('fill', '#64748b');
      emptyText.setAttribute('font-size', '14');
      emptyText.textContent = '尚無分析步驟資料，請由左側輸入地址或雜湊開始查詢。';
      rootG.appendChild(emptyText);
      return;
    }

    // 收集所有節點與邊
    const visibleSteps = this.steps.filter((s) => this.isStepVisible(s));
    if (visibleSteps.length === 0) {
      const emptyText = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      emptyText.setAttribute('x', '550');
      emptyText.setAttribute('y', '300');
      emptyText.setAttribute('text-anchor', 'middle');
      emptyText.setAttribute('fill', '#64748b');
      emptyText.setAttribute('font-size', '14');
      emptyText.textContent = '目前篩選條件下無符合之金流步驟。';
      rootG.appendChild(emptyText);
      return;
    }

    // 動態排列層級 (Layered Layout)
    // 依跳數 hop (0: 目標, 1: 前一步, 2: 來源...)
    const nodes = new Map();
    visibleSteps.forEach((step, idx) => {
      const fromAddr = (step.from_address || 'unknown_from').toLowerCase();
      const toAddr = (step.to_address || 'unknown_to').toLowerCase();

      if (!nodes.has(fromAddr)) {
        nodes.set(fromAddr, {
          id: fromAddr,
          label: step.label || step.from_address.slice(0, 10) + '...',
          classification: step.classification,
          hop: step.hop,
          category: step.path_category,
        });
      }
      if (!nodes.has(toAddr)) {
        nodes.set(toAddr, {
          id: toAddr,
          label: toAddr.slice(0, 10) + '...',
          classification: '目標錢包',
          hop: Math.max(0, step.hop - 1),
          category: '目標',
        });
      }
    });

    // 依 hop 分組計算坐標
    const hopGroups = new Map();
    nodes.forEach((node) => {
      const h = node.hop || 0;
      if (!hopGroups.has(h)) hopGroups.set(h, []);
      hopGroups.get(h).push(node);
    });

    const maxHop = Math.max(...Array.from(hopGroups.keys()), 1);
    const startX = 100;
    const endX = 950;
    const stepX = (endX - startX) / Math.max(maxHop, 1);

    hopGroups.forEach((groupNodes, h) => {
      // 資金流入方向通常是左 (高 hop) -> 右 (目標 hop 0)
      const x = endX - (h * stepX);
      const totalY = 500;
      const count = groupNodes.length;
      const spacingY = totalY / (count + 1);

      groupNodes.forEach((node, i) => {
        node.x = x;
        node.y = 80 + (i + 1) * spacingY;
      });
    });

    // 1. 繪製邊 (Edges)
    visibleSteps.forEach((step, idx) => {
      const u = nodes.get((step.from_address || '').toLowerCase());
      const v = nodes.get((step.to_address || '').toLowerCase());
      if (!u || !v) return;

      const edgeG = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      edgeG.style.cursor = 'pointer';

      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      const dx = v.x - u.x;
      const dy = v.y - u.y;
      const cx1 = u.x + dx * 0.5;
      const cy1 = u.y;
      const cx2 = u.x + dx * 0.5;
      const cy2 = v.y;
      const d = `M ${u.x} ${u.y} C ${cx1} ${cy1}, ${cx2} ${cy2}, ${v.x} ${v.y}`;
      path.setAttribute('d', d);
      path.setAttribute('fill', 'none');

      let strokeColor = '#38bdf8';
      let marker = 'arrow-solid';

      if (step.line_style === 'dashed') {
        strokeColor = '#94a3b8';
        marker = 'arrow-dashed';
        path.setAttribute('stroke-dasharray', '5,4');
      } else if (step.line_style === 'dotted') {
        strokeColor = '#64748b';
        marker = 'arrow-dashed';
        path.setAttribute('stroke-dasharray', '2,3');
      }

      if (step.path_category === '交易所直提') {
        strokeColor = '#fbbf24';
        marker = 'arrow-amber';
      } else if (step.path_category === '跨鏈橋／Relay') {
        strokeColor = '#c084fc';
        marker = 'arrow-purple';
      }

      const isSelected = this.selectedStepIndex === idx;
      path.setAttribute('stroke', isSelected ? '#ffffff' : strokeColor);
      path.setAttribute('stroke-width', isSelected ? '3.5' : (step.line_style === 'solid' ? '2.2' : '1.5'));
      path.setAttribute('marker-end', `url(#${marker})`);

      // 箭頭文字 (金額與 Token)
      const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      const midX = (u.x + v.x) / 2;
      const midY = (u.y + v.y) / 2 - 8;
      text.setAttribute('x', midX);
      text.setAttribute('y', midY);
      text.setAttribute('fill', isSelected ? '#ffffff' : strokeColor);
      text.setAttribute('font-size', '10');
      text.setAttribute('font-weight', '600');
      text.setAttribute('text-anchor', 'middle');
      text.textContent = `${step.amount || ''} ${step.token || ''}`;

      edgeG.appendChild(path);
      edgeG.appendChild(text);

      edgeG.addEventListener('click', (e) => {
        e.stopPropagation();
        this.selectedStepIndex = idx;
        this.render();
        this.onSelect(step);
      });

      rootG.appendChild(edgeG);
    });

    // 2. 繪製節點 (Nodes)
    nodes.forEach((node) => {
      const nodeG = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      nodeG.setAttribute('transform', `translate(${node.x}, ${node.y})`);
      nodeG.style.cursor = 'pointer';

      let fill = '#18202c';
      let stroke = '#3b82f6';
      let icon = '👛';

      if (node.classification === '交易所' || node.category === '交易所直提') {
        stroke = '#fbbf24';
        fill = '#261c0c';
        icon = '🏛️';
      } else if (node.classification === 'Bridge' || node.category === '跨鏈橋／Relay') {
        stroke = '#c084fc';
        fill = '#231535';
        icon = '🌉';
      } else if (node.classification === 'Polymarket') {
        stroke = '#38bdf8';
        fill = '#0f2438';
        icon = '🎯';
      } else if (node.classification === '目標錢包') {
        stroke = '#34d399';
        fill = '#0a2618';
        icon = '⭐';
      }

      // 卡片外框
      const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      rect.setAttribute('x', '-70');
      rect.setAttribute('y', '-22');
      rect.setAttribute('width', '140');
      rect.setAttribute('height', '44');
      rect.setAttribute('rx', '6');
      rect.setAttribute('fill', fill);
      rect.setAttribute('stroke', stroke);
      rect.setAttribute('stroke-width', '1.5');
      nodeG.appendChild(rect);

      // 節點文字
      const textTitle = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      textTitle.setAttribute('x', '-60');
      textTitle.setAttribute('y', '-4');
      textTitle.setAttribute('fill', '#f0f6fc');
      textTitle.setAttribute('font-size', '11');
      textTitle.setAttribute('font-weight', '600');
      textTitle.textContent = `${icon} ${node.label.slice(0, 14)}`;
      nodeG.appendChild(textTitle);

      const textSub = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      textSub.setAttribute('x', '-60');
      textSub.setAttribute('y', '12');
      textSub.setAttribute('fill', '#94a3b8');
      textSub.setAttribute('font-size', '9');
      textSub.setAttribute('font-family', 'var(--font-mono)');
      textSub.textContent = `${node.id.slice(0, 6)}...${node.id.slice(-4)}`;
      nodeG.appendChild(textSub);

      nodeG.addEventListener('click', (e) => {
        e.stopPropagation();
        // 點選節點時，找到關聯的 step 並觸發
        const matched = this.steps.find((s) =>
          (s.from_address || '').toLowerCase() === node.id ||
          (s.to_address || '').toLowerCase() === node.id
        );
        if (matched) {
          this.onSelect(matched);
        }
      });

      rootG.appendChild(nodeG);
    });
  }
}
