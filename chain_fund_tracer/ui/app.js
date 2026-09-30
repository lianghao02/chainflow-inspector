/**
 * Chain Fund Tracer - 主工作台前端邏輯 (app.js)
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
    flowGraph.resetView();
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

  // 匯出功能選單
  document.querySelectorAll('[data-export]').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      const exportType = btn.getAttribute('data-export');
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
// 結果渲染器
// ==========================

function renderAllResults(data) {
  // 1. 流程圖
  flowGraph.setData(data.steps || []);

  // 2. 更新計數器徽章
  const bettingSteps = (data.steps || []).filter((s) => s.path_category === 'Polymarket 平台內部回款／贖回' || s.event_role === '投注買賣');
  const inboundSteps = (data.steps || []).filter((s) => s.path_role === '入金');
  const subpoenas = data.subpoena_candidates || [];
  const tracks = Object.keys(data.query_tracks || {}).length;

  document.getElementById('countBetting').textContent = bettingSteps.length;
  document.getElementById('countInbound').textContent = inboundSteps.length;
  document.getElementById('countSubpoena').textContent = subpoenas.length;
  document.getElementById('countAudit').textContent = tracks;

  // 3. 渲染各頁籤表格
  renderBettingTable(bettingSteps);
  renderInboundTable(inboundSteps);
  renderSubpoenaTable(subpoenas);
  renderAuditTable(data.query_tracks || {});
  renderReportText(data);
}

function renderStepDetail(step) {
  const container = document.getElementById('detailBody');
  if (!container) return;

  let badgeCls = 'badge-dashed';
  if (step.line_style === 'solid') badgeCls = 'badge-solid';
  if (step.classification === '交易所' || step.path_category === '交易所直提') badgeCls = 'badge-vasp';
  if (step.classification === 'Bridge' || step.path_category === '跨鏈橋／Relay') badgeCls = 'badge-bridge';

  container.innerHTML = `
    <div class="evidence-kv">
      <div class="evidence-kv-key">路徑分類與性質</div>
      <div class="evidence-kv-val">
        <span class="badge ${badgeCls}">${step.path_category || '未能分類'}</span>
        <span style="margin-left: 6px; font-weight:600;">${step.direction || ''} 第 ${step.hop || 0} 跳</span>
      </div>
    </div>

    <div class="evidence-kv">
      <div class="evidence-kv-key">資產與轉帳金額</div>
      <div class="evidence-kv-val" style="font-size: 14px; font-weight: 700; color: #38bdf8;">
        ${step.amount || '0'} ${step.token || ''}
      </div>
    </div>

    <div class="evidence-kv">
      <div class="evidence-kv-key">交易時間 (UTC+8)</div>
      <div class="evidence-kv-val mono">${step.timestamp || '未收錄'}</div>
    </div>

    <div class="evidence-kv">
      <div class="evidence-kv-key">來源地址 (From)</div>
      <div class="evidence-kv-val mono">
        ${step.from_address || ''}
        ${step.label ? `<div style="color:#fbbf24; margin-top:2px;">標籤：${step.label} (${step.label_source || ''})</div>` : ''}
      </div>
    </div>

    <div class="evidence-kv">
      <div class="evidence-kv-key">目標地址 (To)</div>
      <div class="evidence-kv-val mono">${step.to_address || ''}</div>
    </div>

    <div class="evidence-kv">
      <div class="evidence-kv-key">交易雜湊 (Tx Hash)</div>
      <div class="evidence-kv-val mono">
        <a href="#" onclick="openTxUrl('${step.tx_hash}'); return false;" style="color:#38bdf8; text-decoration: underline;">
          ${step.tx_hash}
        </a>
      </div>
    </div>

    <div class="evidence-kv">
      <div class="evidence-kv-key">證據依據與配對狀態</div>
      <div class="evidence-kv-val" style="font-size: 11px;">
        <div>鏈別／區塊：${step.chain || 'Polygon'} ｜ 區塊 ${step.block_number || 'N/A'}</div>
        <div>資料來源：${step.evidence_source || 'Explorer Token Transfers'}</div>
        <div>精確配對：${step.pair_verified ? '✅ 已唯一配對' : '⚠️ 資金池關聯或未單獨閉環'}</div>
      </div>
    </div>

    <div class="evidence-kv">
      <div class="evidence-kv-key">法證查核備註</div>
      <div class="evidence-kv-val" style="color: #cbd5e1; font-size: 11px; background: rgba(0,0,0,0.2); padding: 6px; border-radius: 4px;">
        ${step.notes || '無特殊備註'}
      </div>
    </div>
  `;
}

function openTxUrl(txHash) {
  if (window.pywebview && txHash) {
    window.pywebview.api.open_external(`https://polygonscan.com/tx/${txHash}`);
  }
}

// 渲染 🎯 Polymarket 投注解碼表格
function renderBettingTable(steps) {
  const tbody = document.querySelector('#bettingTable tbody');
  if (!tbody) return;
  tbody.innerHTML = '';

  if (steps.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; color:#64748b;">本次未辨識到 Polymarket 下注交易。</td></tr>';
    return;
  }

  steps.forEach((s) => {
    const info = s.trade_info || {};
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${s.timestamp || ''}</td>
      <td style="font-weight: 600; color:#f0f6fc;">${info.market_title || '市場題目待解析'}</td>
      <td><span class="badge" style="background:#0f2438; color:#38bdf8;">${info.outcome || '選項待解'}</span></td>
      <td class="mono" style="color:#34d399;">${info.collateral_amount || s.amount} ${info.collateral_token || s.token}</td>
      <td class="mono">${info.shares || 'N/A'}</td>
      <td class="mono"><a href="#" onclick="openTxUrl('${s.tx_hash}'); return false;" style="color:#38bdf8;">${s.tx_hash.slice(0, 10)}...</a></td>
      <td>${info.enrichment_source || s.evidence_source || 'Receipt 解碼'}</td>
    `;
    tbody.appendChild(tr);
  });
}

// 渲染 💰 入金路徑表格
function renderInboundTable(steps) {
  const tbody = document.querySelector('#inboundTable tbody');
  if (!tbody) return;
  tbody.innerHTML = '';

  if (steps.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:#64748b;">未辨識到入金步驟。</td></tr>';
    return;
  }

  steps.forEach((s) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><span class="badge ${s.line_style === 'solid' ? 'badge-solid' : 'badge-dashed'}">${s.path_category || '未能分類'}</span></td>
      <td class="mono" style="font-weight:600; color:#38bdf8;">${s.amount} ${s.token}</td>
      <td class="mono">${s.timestamp || ''}</td>
      <td class="mono">${s.from_address.slice(0, 12)}... ${s.label ? `<span style="color:#fbbf24;">[${s.label}]</span>` : ''}</td>
      <td class="mono"><a href="#" onclick="openTxUrl('${s.tx_hash}'); return false;" style="color:#38bdf8;">${s.tx_hash.slice(0, 10)}...</a></td>
      <td>${s.evidence_source || '鏈上紀錄'}</td>
    `;
    tbody.appendChild(tr);
  });
}

// 渲染 ⚖️ 函調候選清單
function renderSubpoenaTable(candidates) {
  const tbody = document.querySelector('#subpoenaTable tbody');
  if (!tbody) return;
  tbody.innerHTML = '';

  if (candidates.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; color:#64748b;">本案尚未命中具直接函調價值之交易所或入金商節點。</td></tr>';
    return;
  }

  candidates.forEach((c) => {
    const tr = document.createElement('tr');
    const isKyc = c.inquiry_value === '可函調 KYC';
    const tagCls = isKyc ? 'badge-vasp' : 'badge-dashed';

    tr.innerHTML = `
      <td style="font-weight:700; color:#f0f6fc;">${c.service_provider || '未標註實體'}</td>
      <td>${c.service_type || ''}</td>
      <td><span class="badge ${tagCls}">${c.inquiry_value || ''}</span></td>
      <td class="mono">${c.asset} ${c.amount}</td>
      <td class="mono">${c.datetime_tw || ''}</td>
      <td class="mono">${c.from_address}</td>
      <td class="mono"><a href="#" onclick="openTxUrl('${c.tx_hash}'); return false;" style="color:#38bdf8;">${c.tx_hash.slice(0, 10)}...</a></td>
      <td style="color:#94a3b8; font-size:10px;">${c.limitations || ''}</td>
    `;
    tbody.appendChild(tr);
  });
}

// 渲染 📜 查詢狀態與稽核軌道
function renderAuditTable(tracks) {
  const tbody = document.querySelector('#auditTable tbody');
  if (!tbody) return;
  tbody.innerHTML = '';

  const keys = Object.keys(tracks);
  if (keys.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:#64748b;">本次查詢未啟用或未記錄定向代幣軌道。</td></tr>';
    return;
  }

  keys.forEach((k) => {
    const t = tracks[k];
    const tr = document.createElement('tr');
    let statusBadge = '<span class="badge" style="background:#064e3b; color:#34d399;">正常完成</span>';
    if (t.status === 'error') {
      statusBadge = '<span class="badge" style="background:#7f1d1d; color:#f87171;">查詢失敗</span>';
    } else if (t.is_truncated) {
      statusBadge = '<span class="badge badge-vasp">已達上限 (歷史未完整)</span>';
    }

    tr.innerHTML = `
      <td style="font-weight:600; color:#f0f6fc;">${t.symbol || 'ERC-20'}</td>
      <td class="mono">${t.token}</td>
      <td>${statusBadge}</td>
      <td>${t.pages_scanned || 0} 頁 / ${t.items_count || 0} 筆</td>
      <td>${t.min_block ? `區塊 ${t.min_block} ～ ${t.max_block}` : '無資料'}</td>
      <td style="color:#ef4444;">${t.error_message || '—'}</td>
    `;
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
    `【函調候選清單摘要】`,
    ...(data.subpoena_candidates || []).map((c) =>
      `[${c.inquiry_value}] 服務商：${c.service_provider} (${c.service_type}) ｜ 金額：${c.amount} ${c.asset} ｜ Tx：${c.tx_hash}`
    ),
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
