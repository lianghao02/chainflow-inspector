/**
 * Chain Fund Tracer - 主工作台前端邏輯 (app.js)
 * 遵循安全法證標準：全面杜絕 XSS 外部腳本注入、DOM 安全構建、支援 6 大分層頁籤與摘要橫幅。
 */

let flowGraph = null;
let currentResult = null;
let currentSettings = {};

document.addEventListener('DOMContentLoaded', () => {
  const svgEl = document.getElementById('flowSvg');
  flowGraph = new FlowGraph(svgEl, renderStepDetail);

  initEventListeners();

  // 若在 pywebview 環境中，等待 API 準備完畢
  if (window.pywebview) {
    onPyWebViewReady();
  } else {
    window.addEventListener('pywebviewready', onPyWebViewReady);
  }
});

// 進度回報全域回呼
window.__onProgress = function(message) {
  updateStatus(message, true);
};

async function onPyWebViewReady() {
  updateStatus('系統已就緒', false);
  try {
    const initData = await window.pywebview.api.get_init_data();
    currentSettings = initData.settings || {};
    renderHistoryList(initData.history || []);
  } catch (err) {
    console.error('初始化失敗:', err);
  }
}

function updateStatus(text, isBusy) {
  const statusText = document.getElementById('statusText');
  const statusDot = document.getElementById('statusDot');
  if (statusText) statusText.textContent = text;
  if (statusDot) {
    if (isBusy) statusDot.classList.add('busy');
    else statusDot.classList.remove('busy');
  }
}

// ==========================
// 安全輔助工具（防禦 XSS）
// ==========================

function escapeHtml(text) {
  if (text === null || text === undefined) return '';
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function createTextElement(tag, text, className) {
  const el = document.createElement(tag);
  if (text !== undefined && text !== null) {
    el.textContent = String(text);
  }
  if (className) {
    el.className = className;
  }
  return el;
}

function createTxLink(txHash, chainId = 137, displayText = null) {
  const a = document.createElement('a');
  a.href = '#';
  a.className = 'mono safe-explorer-link';
  a.style.color = '#38bdf8';
  a.style.textDecoration = 'underline';
  a.textContent = displayText || (txHash ? `${txHash.slice(0, 10)}...` : '檢視');
  a.addEventListener('click', (e) => {
    e.preventDefault();
    if (window.pywebview && window.pywebview.api && txHash) {
      window.pywebview.api.open_explorer(chainId, 'tx', txHash);
    }
  });
  return a;
}

function createAddressLink(address, chainId = 137, label = '') {
  const span = document.createElement('span');
  span.className = 'mono';
  if (!address) {
    span.textContent = '—';
    return span;
  }
  const a = document.createElement('a');
  a.href = '#';
  a.style.color = '#38bdf8';
  a.textContent = `${address.slice(0, 8)}...${address.slice(-6)}`;
  a.title = address;
  a.addEventListener('click', (e) => {
    e.preventDefault();
    if (window.pywebview && window.pywebview.api && address) {
      window.pywebview.api.open_explorer(chainId, 'address', address);
    }
  });
  span.appendChild(a);
  if (label) {
    const lblSpan = document.createElement('span');
    lblSpan.style.color = '#fbbf24';
    lblSpan.style.marginLeft = '4px';
    lblSpan.textContent = `[${label}]`;
    span.appendChild(lblSpan);
  }
  return span;
}

// ==========================
// 事件監聽與控制器互動
// ==========================

function initEventListeners() {
  // 開始追查
  const startBtn = document.getElementById('startBtn');
  const stopBtn = document.getElementById('stopBtn');

  startBtn.addEventListener('click', handleStartTrace);
  stopBtn.addEventListener('click', handleStopTrace);

  // 選取 CSV
  const selectCsvBtn = document.getElementById('selectCsvBtn');
  if (selectCsvBtn) {
    selectCsvBtn.addEventListener('click', handleSelectCsv);
  }

  // 流程圖篩選按鈕
  document.querySelectorAll('.pill-btn').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      document.querySelectorAll('.pill-btn').forEach((b) => b.classList.remove('active'));
      e.target.classList.add('active');
      const filter = e.target.getAttribute('data-filter');
      flowGraph.setFilter(filter);
    });
  });

  // 重設視角
  document.getElementById('resetViewBtn').addEventListener('click', () => {
    flowGraph.fitToView();
  });

  // 匯出下拉選單
  const exportBtn = document.getElementById('exportDropdownBtn');
  const exportMenu = document.getElementById('exportDropdownMenu');
  if (exportBtn && exportMenu) {
    exportBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      exportMenu.classList.toggle('show');
    });
    document.addEventListener('click', () => {
      exportMenu.classList.remove('show');
    });
  }

  // 匯出項目點擊
  document.querySelectorAll('[data-export]').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      const exportType = btn.getAttribute('data-export');
      if (exportMenu) exportMenu.classList.remove('show');
      try {
        updateStatus(`正在匯出 ${exportType}…`, true);
        const res = await window.pywebview.api.export_report(exportType);
        if (res.success) {
          alert(`匯出成功！\n儲存路徑：${res.file_path}`);
          updateStatus('匯出完成', false);
        } else if (!res.cancelled) {
          alert(`匯出失敗：${res.error}`);
          updateStatus('匯出失敗', false);
        } else {
          updateStatus('已取消匯出', false);
        }
      } catch (err) {
        alert(`匯出異常：${err}`);
        updateStatus('匯出異常', false);
      }
    });
  });

  // 底欄抽屜頁籤切換
  document.querySelectorAll('.drawer-tab').forEach((tab) => {
    tab.addEventListener('click', (e) => {
      const tabTarget = tab.getAttribute('data-tab');
      document.querySelectorAll('.drawer-tab').forEach((t) => t.classList.remove('active'));
      document.querySelectorAll('.drawer-content').forEach((c) => c.classList.remove('active'));

      tab.classList.add('active');
      const targetContent = document.getElementById(`tab-${tabTarget}`);
      if (targetContent) targetContent.classList.add('active');

      const drawer = document.getElementById('bottomDrawer');
      if (drawer.classList.contains('collapsed')) {
        drawer.classList.remove('collapsed');
      }
    });
  });

  // 底欄收合/展開
  document.getElementById('toggleDrawerBtn').addEventListener('click', () => {
    const drawer = document.getElementById('bottomDrawer');
    drawer.classList.toggle('collapsed');
  });
}

// ==========================
// 核心業務流程
// ==========================

async function handleSelectCsv() {
  try {
    const path = await window.pywebview.api.select_csv_file();
    if (path) {
      document.getElementById('csvInput').value = path;
      const targetAddr = cleanInputQuery(document.getElementById('queryInput').value);
      const res = await window.pywebview.api.inspect_csv(path, targetAddr);
      const badge = document.getElementById('csvBadge');
      if (res.success && res.data) {
        badge.style.display = 'block';
        badge.textContent = `已載入 CSV：共 ${res.data.total_rows} 筆（${res.data.time_range}）`;
      }
    }
  } catch (err) {
    alert(`選取 CSV 失敗：${err}`);
  }
}

function cleanInputQuery(val) {
  let q = (val || '').trim();
  if (q.includes('polygonscan.com/address/')) {
    q = q.split('polygonscan.com/address/')[1].split('/')[0].split('?')[0];
  } else if (q.includes('polygonscan.com/tx/')) {
    q = q.split('polygonscan.com/tx/')[1].split('/')[0].split('?')[0];
  }
  return q.trim();
}

async function handleStartTrace() {
  const queryRaw = document.getElementById('queryInput').value;
  const query = cleanInputQuery(queryRaw);
  if (!query) {
    alert('請輸入 Polygon 錢包地址或交易雜湊！');
    return;
  }

  const mode = document.getElementById('modeSelect').value;
  const hops = parseInt(document.getElementById('hopsSelect').value, 10) || 2;
  const timeFilter = document.getElementById('timeInput').value.trim();
  const csvPath = document.getElementById('csvInput').value.trim();

  document.getElementById('startBtn').style.display = 'none';
  document.getElementById('stopBtn').style.display = 'inline-flex';
  updateStatus('正在進行鏈上法證追蹤…', true);

  try {
    const res = await window.pywebview.api.run_analysis({
      query: query,
      mode: mode,
      hops: hops,
      time_filter_raw: timeFilter,
      csv_path: csvPath,
    });

    if (res.success && res.data) {
      currentResult = res.data;
      renderAllResults(res.data);
      updateStatus('分析完成', false);
    } else {
      alert(`分析失敗：${res.error || '未知錯誤'}`);
      updateStatus('分析中斷或失敗', false);
    }
  } catch (err) {
    alert(`執行異常：${err}`);
    updateStatus('系統異常', false);
  } finally {
    document.getElementById('startBtn').style.display = 'inline-flex';
    document.getElementById('stopBtn').style.display = 'none';
  }
}

async function handleStopTrace() {
  try {
    await window.pywebview.api.cancel_analysis();
    updateStatus('正在請求停止…', true);
  } catch (err) {
    console.error(err);
  }
}

// ==========================
// 結果渲染器（完全防禦 XSS）
// ==========================

function renderAllResults(data) {
  const steps = data.steps || [];
  const subpoenas = data.subpoena_candidates || [];
  const tracks = data.query_tracks || {};

  // 1. 流程圖
  flowGraph.setData(steps);

  // 2. 調證候選分流：可函調 KYC 服務商 vs 上游追查節點
  const kycCandidates = subpoenas.filter((c) => c.inquiry_value === '可函調 KYC');
  const upstreamCandidates = subpoenas.filter((c) => c.inquiry_value !== '可函調 KYC');

  const bettingSteps = steps.filter((s) => s.direction === 'Polymarket 投注' || s.event_role === '投注買賣');
  const inboundSteps = steps.filter((s) => s.path_role === '入金');

  // 3. 更新頁籤計數器徽章
  document.getElementById('countSubpoena').textContent = kycCandidates.length;
  document.getElementById('countUpstream').textContent = upstreamCandidates.length;
  document.getElementById('countInbound').textContent = inboundSteps.length;
  document.getElementById('countBetting').textContent = bettingSteps.length;
  document.getElementById('countAudit').textContent = Object.keys(tracks).length;

  // 4. 渲染頂部「本案初步結論」摘要橫幅
  renderSummaryBanner(data, kycCandidates, upstreamCandidates, steps);

  // 5. 渲染 4 軌狀態徽章
  renderTrackBadges(tracks);

  // 6. 渲染各頁籤表格（DOM 安全構建）
  renderKycTable(kycCandidates);
  renderUpstreamTable(upstreamCandidates);
  renderInboundTable(inboundSteps);
  renderBettingTable(bettingSteps);
  renderAuditTable(tracks);
  renderReportText(data);

  // 7. 預設選取最高優先級之步驟（首選交易所直提/逐筆本金，非內部底層事件）
  selectDefaultPriorityStep(steps);
}

function renderSummaryBanner(data, kycCandidates, upstreamCandidates, steps) {
  const kycEl = document.getElementById('sumKycCount');
  const principalEl = document.getElementById('sumPrincipalCount');
  const relayEl = document.getElementById('sumRelayCount');
  const upstreamEl = document.getElementById('sumUpstreamCount');
  const trackEl = document.getElementById('sumTrackStatus');

  if (kycCandidates.length > 0) {
    const providers = Array.from(new Set(kycCandidates.map((c) => c.service_provider))).join('、');
    kycEl.textContent = `${providers} (${kycCandidates.length})`;
    kycEl.classList.add('highlight');
  } else {
    kycEl.textContent = '尚未命中交易所';
    kycEl.classList.remove('highlight');
  }

  const principalCount = steps.filter((s) => s.line_style === 'solid' && s.event_role !== '手續費供資' && s.path_role === '入金').length;
  principalEl.textContent = `${principalCount} 條`;

  const relayCount = steps.filter((s) => s.path_category === '跨鏈橋／Relay' || Boolean(s.relay_request_id)).length;
  relayEl.textContent = `${relayCount} 段`;

  upstreamEl.textContent = `${upstreamCandidates.length} 個`;

  const tracks = data.query_tracks || {};
  const hasTruncated = Object.values(tracks).some((t) => t.is_truncated);
  const hasError = Object.values(tracks).some((t) => t.status === 'error');
  if (hasError) {
    trackEl.textContent = '部分查詢異常';
    trackEl.style.color = '#f87171';
  } else if (hasTruncated) {
    trackEl.textContent = '4 軌已查（部分歷史達上限）';
    trackEl.style.color = '#fbbf24';
  } else {
    trackEl.textContent = 'USDC/USDC.e/pUSD/USDT 完整';
    trackEl.style.color = '#34d399';
  }
}

function renderTrackBadges(tracks) {
  const mapping = [
    { key: '0x3c499c542cef5e3811e1192ce70d8cc03d5c3359', statusId: 'status-usdc', subId: 'sub-usdc', name: 'USDC' },
    { key: '0x2791bca1f2de4661ed88a30c99a7a9449aa84174', statusId: 'status-usdce', subId: 'sub-usdce', name: 'USDC.e' },
    { key: '0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb', statusId: 'status-pusd', subId: 'sub-pusd', name: 'pUSD' },
    { key: '0xc2132d05d31c914a87c6611c10748aeb04b58e8f', statusId: 'status-usdt', subId: 'sub-usdt', name: 'USDT' },
  ];

  mapping.forEach((item) => {
    const statusEl = document.getElementById(item.statusId);
    const subEl = document.getElementById(item.subId);
    if (!statusEl) return;

    const t = tracks[item.key] || tracks[item.key.toLowerCase()];
    if (!t) {
      statusEl.textContent = '未啟用';
      statusEl.className = 'track-badge-status';
      return;
    }

    if (t.status === 'error') {
      statusEl.textContent = '查詢失敗';
      statusEl.className = 'track-badge-status err';
    } else if (t.is_truncated) {
      statusEl.textContent = `達上限 (${t.items_count}筆)`;
      statusEl.className = 'track-badge-status warn';
    } else {
      statusEl.textContent = `完成 (${t.items_count}筆)`;
      statusEl.className = 'track-badge-status ok';
    }

    if (subEl && t.min_block) {
      subEl.textContent = `區塊 ${t.min_block}～${t.max_block}`;
    }
  });
}

function selectDefaultPriorityStep(steps) {
  if (!steps || steps.length === 0) return;

  // 優先級：
  // 1. 交易所直提且為 solid 本金線
  // 2. 任何可函調 KYC 步驟
  // 3. Relay 來源鏈入金
  // 4. solid 入金線
  // 5. 第一筆
  const priorityStep =
    steps.find((s) => s.path_category === '交易所直提' && s.line_style === 'solid') ||
    steps.find((s) => s.classification === '交易所' && s.line_style === 'solid') ||
    steps.find((s) => s.event_role === '手續費供資') ||
    steps.find((s) => s.path_category === '跨鏈橋／Relay') ||
    steps.find((s) => s.line_style === 'solid' && s.path_role === '入金') ||
    steps[0];

  if (priorityStep) {
    renderStepDetail(priorityStep);
    flowGraph.selectStepByObject(priorityStep);
  }
}

// 渲染右欄法證詳情卡片（DOM 安全構建，防禦 XSS）
function renderStepDetail(step) {
  const container = document.getElementById('detailBody');
  if (!container) return;
  container.textContent = ''; // 清空

  let badgeCls = 'badge-dashed';
  if (step.line_style === 'solid') badgeCls = 'badge-solid';
  if (step.classification === '交易所' || step.path_category === '交易所直提') badgeCls = 'badge-vasp';
  if (step.classification === 'Bridge' || step.path_category === '跨鏈橋／Relay') badgeCls = 'badge-bridge';

  // 1. 路徑分類與性質
  const kv1 = createKvRow('路徑分類與性質');
  const spanBadge = createTextElement('span', step.path_category || '未能分類', `badge ${badgeCls}`);
  kv1.val.appendChild(spanBadge);
  const spanHop = createTextElement('span', ` ${step.direction || ''} 第 ${step.hop || 0} 跳`);
  spanHop.style.marginLeft = '6px';
  spanHop.style.fontWeight = '600';
  kv1.val.appendChild(spanHop);
  container.appendChild(kv1.row);

  // 2. 資產與金額
  const kv2 = createKvRow('資產與轉帳金額');
  kv2.val.style.fontSize = '14px';
  kv2.val.style.fontWeight = '700';
  kv2.val.style.color = '#38bdf8';
  kv2.val.textContent = `${step.amount || '0'} ${step.token || ''}`;
  container.appendChild(kv2.row);

  // 3. 交易時間
  const kv3 = createKvRow('交易時間 (UTC+8)');
  kv3.val.className = 'evidence-kv-val mono';
  kv3.val.textContent = step.timestamp || '未收錄';
  container.appendChild(kv3.row);

  // 4. 來源地址 (From)
  const kv4 = createKvRow('來源地址 (From)');
  kv4.val.className = 'evidence-kv-val mono';
  kv4.val.appendChild(createAddressLink(step.from_address, step.chain_id || 137, step.label));
  container.appendChild(kv4.row);

  // 5. 目標地址 (To)
  const kv5 = createKvRow('目標地址 (To)');
  kv5.val.className = 'evidence-kv-val mono';
  kv5.val.appendChild(createAddressLink(step.to_address, step.chain_id || 137));
  container.appendChild(kv5.row);

  // 6. 交易雜湊 (Tx Hash)
  const kv6 = createKvRow('交易雜湊 (Tx Hash)');
  kv6.val.className = 'evidence-kv-val mono';
  kv6.val.appendChild(createTxLink(step.tx_hash, step.chain_id || 137, step.tx_hash));
  container.appendChild(kv6.row);

  // 7. 證據依據與配對
  const kv7 = createKvRow('證據依據與配對狀態');
  kv7.val.style.fontSize = '11px';
  const d1 = createTextElement('div', `鏈別／區塊：${step.chain || 'Polygon'} ｜ 區塊 ${step.block_number || 'N/A'}`);
  const d2 = createTextElement('div', `資料來源：${step.evidence_source || 'Explorer 索引'}`);
  const d3 = createTextElement('div', step.pair_verified ? '✅ 已唯一配對（逐筆本金）' : '⚠️ 資金池關聯或較早關聯（非逐筆）');
  kv7.val.appendChild(d1);
  kv7.val.appendChild(d2);
  kv7.val.appendChild(d3);
  container.appendChild(kv7.row);

  // 8. 法證查核備註
  const kv8 = createKvRow('法證查核備註');
  kv8.val.style.fontSize = '12px';
  kv8.val.style.color = '#cbd5e1';
  kv8.val.style.background = 'rgba(0,0,0,0.2)';
  kv8.val.style.padding = '8px';
  kv8.val.style.borderRadius = '4px';
  kv8.val.textContent = step.notes || '無特殊備註';
  container.appendChild(kv8.row);
}

function createKvRow(keyTitle) {
  const row = document.createElement('div');
  row.className = 'evidence-kv';
  const keyEl = createTextElement('div', keyTitle, 'evidence-kv-key');
  const valEl = document.createElement('div');
  valEl.className = 'evidence-kv-val';
  row.appendChild(keyEl);
  row.appendChild(valEl);
  return { row, key: keyEl, val: valEl };
}

// 渲染 🏛️ 可函調 KYC 服務商表格
function renderKycTable(candidates) {
  const tbody = document.querySelector('#subpoenaTable tbody');
  if (!tbody) return;
  tbody.textContent = '';

  if (candidates.length === 0) {
    const tr = document.createElement('tr');
    const td = createTextElement('td', '本案尚未命中具直接函調價值之中心化交易所或法幣入金商。');
    td.colSpan = 8;
    td.style.textAlign = 'center';
    td.style.color = '#64748b';
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  candidates.forEach((c) => {
    const tr = document.createElement('tr');

    const tdProv = createTextElement('td', c.service_provider || '未標註交易所');
    tdProv.style.fontWeight = '700';
    tdProv.style.color = '#f0f6fc';

    const tdType = createTextElement('td', c.service_type || '中心化交易所');

    const tdVal = document.createElement('td');
    const badge = createTextElement('span', c.inquiry_value || '可函調 KYC', 'badge badge-vasp');
    tdVal.appendChild(badge);

    const tdAmt = createTextElement('td', `${c.amount || '0'} ${c.asset || ''}`, 'mono');
    tdAmt.style.color = '#38bdf8';
    tdAmt.style.fontWeight = '600';

    const tdTime = createTextElement('td', c.datetime_tw || '未收錄', 'mono');

    const tdAddr = document.createElement('td');
    tdAddr.appendChild(createAddressLink(c.from_address, 137));

    const tdTx = document.createElement('td');
    tdTx.appendChild(createTxLink(c.tx_hash, 137));

    const tdNotes = createTextElement('td', c.limitations || '—');
    tdNotes.style.color = '#94a3b8';
    tdNotes.style.fontSize = '11px';

    tr.appendChild(tdProv);
    tr.appendChild(tdType);
    tr.appendChild(tdVal);
    tr.appendChild(tdAmt);
    tr.appendChild(tdTime);
    tr.appendChild(tdAddr);
    tr.appendChild(tdTx);
    tr.appendChild(tdNotes);
    tbody.appendChild(tr);
  });
}

// 渲染 🔍 上游追查節點表格
function renderUpstreamTable(candidates) {
  const tbody = document.querySelector('#upstreamTable tbody');
  if (!tbody) return;
  tbody.textContent = '';

  if (candidates.length === 0) {
    const tr = document.createElement('tr');
    const td = createTextElement('td', '本案無其他待追查之上游節點。');
    td.colSpan = 8;
    td.style.textAlign = 'center';
    td.style.color = '#64748b';
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  candidates.forEach((c) => {
    const tr = document.createElement('tr');

    const tdProv = createTextElement('td', c.service_provider || '上游地址');
    tdProv.style.fontWeight = '600';

    const tdType = createTextElement('td', c.service_type || '個人錢包');

    const tdVal = document.createElement('td');
    const badge = createTextElement('span', c.inquiry_value || '僅供上游追蹤', 'badge badge-dashed');
    tdVal.appendChild(badge);

    const tdAmt = createTextElement('td', `${c.amount || '0'} ${c.asset || ''}`, 'mono');
    const tdTime = createTextElement('td', c.datetime_tw || '未收錄', 'mono');

    const tdAddr = document.createElement('td');
    tdAddr.appendChild(createAddressLink(c.from_address, 137));

    const tdTx = document.createElement('td');
    tdTx.appendChild(createTxLink(c.tx_hash, 137));

    const tdNotes = createTextElement('td', c.limitations || '—');
    tdNotes.style.color = '#94a3b8';
    tdNotes.style.fontSize = '11px';

    tr.appendChild(tdProv);
    tr.appendChild(tdType);
    tr.appendChild(tdVal);
    tr.appendChild(tdAmt);
    tr.appendChild(tdTime);
    tr.appendChild(tdAddr);
    tr.appendChild(tdTx);
    tr.appendChild(tdNotes);
    tbody.appendChild(tr);
  });
}

// 渲染 🛣️ 入金路徑表格
function renderInboundTable(steps) {
  const tbody = document.querySelector('#inboundTable tbody');
  if (!tbody) return;
  tbody.textContent = '';

  if (steps.length === 0) {
    const tr = document.createElement('tr');
    const td = createTextElement('td', '未辨識到入金步驟。');
    td.colSpan = 6;
    td.style.textAlign = 'center';
    td.style.color = '#64748b';
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  steps.forEach((s) => {
    const tr = document.createElement('tr');

    const tdCat = document.createElement('td');
    const badgeCls = s.line_style === 'solid' ? 'badge-solid' : 'badge-dashed';
    tdCat.appendChild(createTextElement('span', s.path_category || '未能分類', `badge ${badgeCls}`));

    const tdAmt = createTextElement('td', `${s.amount} ${s.token}`, 'mono');
    tdAmt.style.fontWeight = '600';
    tdAmt.style.color = '#38bdf8';

    const tdTime = createTextElement('td', s.timestamp || '—', 'mono');

    const tdFrom = document.createElement('td');
    tdFrom.appendChild(createAddressLink(s.from_address, s.chain_id || 137, s.label));

    const tdTx = document.createElement('td');
    tdTx.appendChild(createTxLink(s.tx_hash, s.chain_id || 137));

    const tdEvid = createTextElement('td', s.evidence_source || '鏈上紀錄');

    tr.appendChild(tdCat);
    tr.appendChild(tdAmt);
    tr.appendChild(tdTime);
    tr.appendChild(tdFrom);
    tr.appendChild(tdTx);
    tr.appendChild(tdEvid);
    tbody.appendChild(tr);
  });
}

// 渲染 🎯 Polymarket 投注解碼表格
function renderBettingTable(steps) {
  const tbody = document.querySelector('#bettingTable tbody');
  if (!tbody) return;
  tbody.textContent = '';

  if (steps.length === 0) {
    const tr = document.createElement('tr');
    const td = createTextElement('td', '本次未辨識到 Polymarket 下注交易。');
    td.colSpan = 7;
    td.style.textAlign = 'center';
    td.style.color = '#64748b';
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  // 依 tx_hash 去重，優先保留解析出市場題目與選項的紀錄
  const dedupedSteps = [];
  const seenTx = new Map();
  steps.forEach((s) => {
    const tx = (s.tx_hash || '').toLowerCase();
    const info = s.trade_info || {};
    const hasRichInfo = Boolean(info.market_title && info.market_title !== '市場題目待解析');
    if (!seenTx.has(tx)) {
      seenTx.set(tx, s);
      dedupedSteps.push(s);
    } else if (hasRichInfo) {
      const prev = seenTx.get(tx);
      const prevInfo = prev.trade_info || {};
      if (!prevInfo.market_title || prevInfo.market_title === '市場題目待解析') {
        seenTx.set(tx, s);
        const idx = dedupedSteps.indexOf(prev);
        if (idx !== -1) dedupedSteps[idx] = s;
      }
    }
  });

  dedupedSteps.forEach((s) => {
    const info = s.trade_info || {};
    const tr = document.createElement('tr');

    const tdTime = createTextElement('td', s.timestamp || '—', 'mono');
    const tdTitle = createTextElement('td', info.market_title || '市場題目待解析');
    tdTitle.style.fontWeight = '600';
    tdTitle.style.color = '#f0f6fc';

    const tdOutcome = document.createElement('td');
    const outBadge = createTextElement('span', info.outcome || '選項待解', 'badge');
    outBadge.style.background = '#0f2438';
    outBadge.style.color = '#38bdf8';
    tdOutcome.appendChild(outBadge);

    const tdAmt = createTextElement('td', `${info.collateral_amount || s.amount} ${info.collateral_token || s.token}`, 'mono');
    tdAmt.style.color = '#34d399';

    const tdShares = createTextElement('td', info.shares || 'N/A', 'mono');

    const tdTx = document.createElement('td');
    tdTx.appendChild(createTxLink(s.tx_hash, s.chain_id || 137));

    const tdSrc = createTextElement('td', info.enrichment_source || s.evidence_source || 'Receipt 解碼');

    tr.appendChild(tdTime);
    tr.appendChild(tdTitle);
    tr.appendChild(tdOutcome);
    tr.appendChild(tdAmt);
    tr.appendChild(tdShares);
    tr.appendChild(tdTx);
    tr.appendChild(tdSrc);
    tbody.appendChild(tr);
  });
}

// 渲染 📜 查詢狀態與稽核軌道
function renderAuditTable(tracks) {
  const tbody = document.querySelector('#auditTable tbody');
  if (!tbody) return;
  tbody.textContent = '';

  const keys = Object.keys(tracks);
  if (keys.length === 0) {
    const tr = document.createElement('tr');
    const td = createTextElement('td', '本次查詢未記錄定向代幣軌道。');
    td.colSpan = 6;
    td.style.textAlign = 'center';
    td.style.color = '#64748b';
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  keys.forEach((k) => {
    const t = tracks[k];
    const tr = document.createElement('tr');

    const tdSymbol = createTextElement('td', t.symbol || 'ERC-20');
    tdSymbol.style.fontWeight = '600';
    tdSymbol.style.color = '#f0f6fc';

    const tdContract = createTextElement('td', t.token || '', 'mono');

    const tdStatus = document.createElement('td');
    let stBadge;
    if (t.status === 'error') {
      stBadge = createTextElement('span', '查詢失敗', 'badge');
      stBadge.style.background = '#7f1d1d';
      stBadge.style.color = '#f87171';
    } else if (t.is_truncated) {
      stBadge = createTextElement('span', '已達上限 (歷史未完整)', 'badge badge-vasp');
    } else {
      stBadge = createTextElement('span', '正常完成', 'badge');
      stBadge.style.background = '#064e3b';
      stBadge.style.color = '#34d399';
    }
    tdStatus.appendChild(stBadge);

    const tdPages = createTextElement('td', `${t.pages_scanned || 0} 頁 / ${t.items_count || 0} 筆`);
    const tdBlocks = createTextElement('td', t.min_block ? `區塊 ${t.min_block} ～ ${t.max_block}` : '無資料');

    const tdErr = createTextElement('td', t.error_message || '—');
    tdErr.style.color = '#ef4444';

    tr.appendChild(tdSymbol);
    tr.appendChild(tdContract);
    tr.appendChild(tdStatus);
    tr.appendChild(tdPages);
    tr.appendChild(tdBlocks);
    tr.appendChild(tdErr);
    tbody.appendChild(tr);
  });
}

// 渲染 📄 純文字報告
function renderReportText(data) {
  const el = document.getElementById('reportTextContent');
  if (!el) return;

  const lines = [
    `【Chain Fund Tracer 鏈上資金追蹤報告】`,
    `目標查詢：${data.query}`,
    `網路：${data.network || 'Polygon'}`,
    `--------------------------------------------------`,
    `【摘要結論】`,
    ...(data.summary || []).map((s) => `• ${s}`),
    ``,
    `【注意事項與法證邊界】`,
    ...(data.warnings || []).map((w) => `! ${w}`),
    ``,
    `【可函調服務商清單】`,
    ...(data.subpoena_candidates || [])
      .filter((c) => c.inquiry_value === '可函調 KYC')
      .map((c) => `[可函調 KYC] 服務商：${c.service_provider} ｜ 金額：${c.amount} ${c.asset} ｜ Tx：${c.tx_hash}`),
    ``,
    `【上游追蹤線索清單】`,
    ...(data.subpoena_candidates || [])
      .filter((c) => c.inquiry_value !== '可函調 KYC')
      .map((c) => `[${c.inquiry_value}] 節點：${c.service_provider} (${c.service_type}) ｜ 地址：${c.from_address} ｜ Tx：${c.tx_hash}`),
  ];

  el.textContent = lines.join('\n');
}

function renderHistoryList(history) {
  const sel = document.getElementById('historySelect');
  if (!sel) return;
  sel.innerHTML = '<option value="">-- 載入歷史紀錄快照 --</option>';

  history.forEach((h) => {
    const opt = document.createElement('option');
    opt.value = h.id;
    opt.textContent = h.display_title || `${h.query} (${h.timestamp})`;
    sel.appendChild(opt);
  });

  sel.addEventListener('change', async (e) => {
    const id = e.target.value;
    if (!id) return;
    updateStatus('正在載入歷史快照…', true);
    try {
      const res = await window.pywebview.api.load_history(id);
      if (res.success && res.data) {
        currentResult = res.data;
        document.getElementById('queryInput').value = res.data.query || '';
        renderAllResults(res.data);
        updateStatus('歷史快照載入完成', false);
      } else {
        alert('載入失敗：' + (res.error || ''));
      }
    } catch (err) {
      alert('載入異常：' + err);
    }
  });
}
