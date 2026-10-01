# 鏈流查核｜ChainFlow Inspector (Blockchain Evidence Collector)

> **目前版本**：`v1.6.0`（2026-09-30）
> **核心定位**：**Blockchain Evidence Collector + Diagnostic Tool + Agent Analysis Bundle Exporter**

本工具定位為法證等級的**鏈上證據蒐集器與診斷工具**，供執法人員與分析師取得可靠、客觀、可重現的公開鏈上原始資料與標準化金流事件（FlowEvents）。

本工具堅持「程式與 Agent 職責分離」原則：
- **程式負責（固化、可重現、零偏誤）**：公開 RPC / Explorer 資料可靠取得、分頁防漏、異常狀態精準分類（拒絕將錯誤偽裝成 0 筆）、資料標準化（去重、Decimal 轉換、時區正規化）、診斷管線審計與原始證據打包。
- **Agent 負責（語境理解、複雜推理）**：深度跨鏈跳轉分析、意圖協議與 Bridge 解碼、交易所出入金實名破口研判。可一鍵匯出標準 **Agent Analysis Bundle (ZIP)** 直接交由 Antigravity、Codex 或 ChatGPT 進行深度研判。

> **法律與證據界線：** 地址分類、資金關聯與交易所標籤，不是自然人身分、實際控制權或違法事實的認定。交易所 KYC、IP 與帳戶控制資料，仍須依正式法定程序調取並由承辦人員核實。

## 核心能力

1. **多維鏈上資料採集（Evidence Collection）**：
   - 完整支援主鏈交易（Normal Transactions）、代幣轉帳（ERC-20 Token Transfers）、內部交易（Internal Transactions）與合約事件日誌。
   - 嚴格分離「成功查詢（0 筆結果）」與「查詢失敗（HTTP 429 RateLimited、Timeout、RPC 異常、分頁未完）」，拒絕將端點限制偽裝為無金流。

2. **統一金流模型（FlowEvents）**：
   - 多來源標準化匯流為統一事件模型（Chain ID、區塊高度、時間戳、交易雜湊、發送/接收地址、事件類型、代幣合約、標準金額、原始參照）。

3. **採集診斷管線（Diagnostic Pipeline）**：
   - 結構化記錄 `Raw API Records` → `Parsed` → `Normalized` → `Rejected (附拒絕原因：wrong token, outside time window 等)` → `Candidates`。
   - 支援指定 Tx Hash 診斷，快速定位特定交易在採集與過濾哪一層被排除。

4. **Agent Analysis Bundle 匯出**：
   - 一鍵匯出包含 `PROMPT.txt`、`summary.json`（含完整 Data Availability 清冊）、`transactions.json`、`token_transfers.json`、`internal_transactions.json`、`traces_and_logs.json`、`labels.json`、`contracts.json` 與 `diagnostic.log` 的標準壓縮包。

5. **歷史 CSV 索引離線穿透**：
   - 支援匯入 PolygonScan 匯出的完整 CSV 索引，搭配本機 RPC 即時核實，突破公共 API 單次翻頁限制。

6. **可互動現代化法證工作台（PyWebView）**：
   - 提供直觀 SVG 資金圖譜、調證候選清單、狀態看板與匯出選單，並支援離線與無 WebView 環境下的備援。
- pUSD 批次鑄造會以目標收款地址、金額與 Log 順序配對底層 USDC；若同筆交易仍有多筆同額來源，顯示「歸屬待確認／關聯不足」並停止向上串接，避免把其他錢包補款列為目標來源。
- 若目的鏈補款命中 Relay 公開索引，自動還原來源鏈、來源資產、原始入金者、Relay 收款合約及來源鏈 Tx Hash；追蹤深度 4～5 跳時再續查來源鏈上游與交易所公開標籤。來源為 TRON 時，會以 Tronscan 公開 TRC-20 紀錄續追並保留公開標籤。
- 解析交易基本資料與 Receipt 內 ERC-20 Transfer；提示 Polymarket Conditional Tokens 的 ERC-1155 相關事件。
- 上游／下游追蹤 1 至 5 跳（預設 4 跳），逐跳保存 Tx Hash、時間、Token／金額、From／To、標籤來源、信心與判定。
- 地址類別支援交易所、Bridge、DEX、Polymarket、未知地址等；內建少量已實際查核的公開合約／交易所標籤，並記錄標籤來源與查核日期。其餘由使用者提供有證據的自訂標籤。
- 判定固定使用：`已確認`、`高度可能`、`僅資金關聯`、`未知`。
- 匯出 UTF-8 案件紀錄文字或 Excel 可讀取的 CSV。
- 資金流程圖以入金、平台內部與出金分段，段內按照臺灣時間由舊到新呈現垂直證據鏈；交易箭頭顯示 Token／金額、時間及縮短 Tx。相同 Relay Request 的唯一來源／目的交易才顯示時間戳差，**不是服務處理耗時**；負值保留而不取絕對值。
- 流程圖支援路徑篩選、縮放、捲動、複製 Tx Hash、開啟 Explorer，以及長時間查詢的進度與安全停止；文字明細仍完整保留。
- 工作台分為「採集與匯出」、「金流檢視」、「資料與診斷」三個工作區；進階設定與啟發式調證參考預設收合，圖譜詳情於點選節點或箭頭後開啟。
- CSV 模式顯示檔案筆數、臺灣標準時間範圍、查詢階段與候選完成筆數；四種匯出格式集中於單一「匯出」選單。

## Windows 執行

1. 安裝 [Python 3.11 以上](https://www.python.org/downloads/windows/)，安裝時勾選 **Add Python to PATH**。
2. 安裝核心依賴套件（HTML 現代化工作台所需）：
   ```powershell
   py -3 -m pip install -r requirements.txt
   ```
3. 執行程式：雙擊 `run.bat` 或在命令列執行 `python app.py`。
4. 系統以 PyWebView 原生視窗開啟工作台。
5. 在「採集與匯出」輸入地址或交易雜湊（支援 PolygonScan 網址），按「開始採集」。時間、歷史 CSV 與追蹤深度位於進階設定。
6. 查詢後依需求切換工作區：
   - **採集與匯出**：查看主鏈交易、代幣轉帳、內部交易與合約日誌的筆數及狀態，再按「匯出 Agent 分析包 ZIP」。ZIP 交由 Agent 進行跨鏈與金流研判；程式仍保留基本追蹤、圖譜與診斷功能。
   - **金流檢視**：查看 SVG 圖譜、切換金流篩選、縮放與重設視野；點選節點或箭頭開啟證據詳情。
   - **資料與診斷**：核對資料可用性、來源、分頁限制與診斷日誌；切換調證候選、上游節點、入金路徑、投注解碼及文字報告。啟發式調證參考可自行展開。
7. 頂端「其他匯出」保留 CSV、TXT、SVG、證據包等格式。匯出失敗會顯示原因，可選擇其他資料夾重試；原查詢結果保留。

成功零筆會顯示 `0`；未採集、查詢失敗或歷史快照缺少狀態時不宣稱沒有交易。摘要的「範圍內採集完成」僅代表本次查詢範圍，不代表完整鏈上歷史。

如要反查下注本金，可貼入**下注交易雜湊**或 **Polymarket 錢包地址**後按「Polymarket 資金鏈穿透」。結果中的「下注前補款／地址入金」是候選資金池；「pUSD 底層入金」是鑄造 pUSD 時真正投入 USDC 的地址；「Relay 來源鏈」才是跨鏈前的原始交易。工具會將 Polymarket Exchange、Onramp、Reward Distributor、pUSD 合約、Relay Solver 與零地址鑄造分開標示，不會把它們誤當交易所來源。

預設使用 `https://polygon.drpc.org` 與 `https://polygon.blockscout.com/api/v2`，Polygon RPC 失敗時會依序嘗試公開備援端點。可在「設定」改用機關核准的 RPC 或 Explorer。Relay API Key 為選填，填入後優先使用 v3；未填時暫以免金鑰 v2 相容介面查詢。BNB Chain 來源鏈會優先使用 BNBScan 公開 REST API 查詢 Token 與原生 BNB 入帳；若該索引回傳 0 筆或連線失敗，會改以 Relay 來源 Tx 為錨點，向前查核 BNB Chain 原始區塊 Receipt 與地址交易，再續追穩定幣、DEX 兌換與原生 BNB 入金。TRON 來源鏈則使用 Tronscan 公開 TRC-20 API，兩者都不必填 API Key。其他缺少免金鑰 Explorer 的來源鏈才需要選填 Etherscan V2 API Key。金鑰只存放在程式同目錄的 `settings.json`，不得硬編碼、交付或上傳。摘要將「Relay 來源鏈／地址／資產」與「上游命中交易所公開標籤」分開顯示，避免把 BNB Chain 網路誤解為 Binance 交易所。

## 自訂地址標籤

在 `settings.json` 的 `custom_labels` 加入已核實的公開地址。地址鍵值請使用小寫：

```json
{
  "custom_labels": {
    "0x0000000000000000000000000000000000000000": {
      "classification": "交易所",
      "label": "範例交易所 Hot Wallet",
      "confidence": "已確認"
    }
  }
}
```

可使用的 `classification` 包含「交易所」、「Bridge」、「DEX」、「Polymarket」與「未知地址」。標籤來源會顯示為「使用者設定」，因此案件紀錄仍應另行保存查核依據。

## 限制

- 公開 API 有限流、索引延遲與歷史深度限制；工具會保留資料來源與錯誤，不會把缺失資料補成結論。
- 一般分析模式的地址圖仍以原生幣交易為主；Polymarket／Relay 模式則會另查 ERC-20 Token Transfers 與交易 Receipt。
- 公開 Explorer 的 Token Transfers 通常只提供近期已索引資料；若候選補款未出現，應匯入對應地址的完整 USDC／USDC.e CSV 或改用機關核准資料服務。
- 資金鏈模式會依 Blockscout 分頁游標讀取一般 ERC-20 歷史，預設最多 15 頁（約 750 筆），並另對 Native USDC、USDC.e、pUSD、USDT 各執行最多 5 頁的定向入金查詢。所有範圍皆屬可調整上限；達上限時會提示資料不完整。查不到補款不代表沒有補款，必要時才啟用較慢的 RPC Logs 備援。
- 僅內建本版已查核、且在測試金流中必要的少量公開標籤；不構成完整交易所熱錢包清冊。正式案件仍應保存標籤頁截圖與查核日期，並串接機關核准的鏈上標籤資料庫。
- Relay 將來源與目的交易依 Request ID 配對；若 Explorer 無公開標籤，結果仍會是未知地址，不能因此推定交易所或自然人。

## 證據解釋與出金續追（2026-09-24）

- 點選箭頭，右側「這一步代表什麼？」使用固定規則離線說明發起者是否已知、執行角色、節點控制性及證據層級。From／To 不直接當成操作人，DEX 不當成中心化交易所。
- 地址模式在既有贖回紀錄上，可將 Relay 出金接到目的鏈入帳與後續同合約轉出候選。目前支援 Ethereum、Optimism、BNB Chain、Polygon、Base、Arbitrum One；不宣稱完整交易所閉環。
- 目的鏈入帳先以 Relay `stateChanges` 淨額索引配對，再以目的鏈 RPC Receipt 核對 Token、From、To、原始金額與唯一 Transfer Log；核對失敗時保留為索引線索並明確警告，不提升為逐筆轉帳證據。
- 地址模式會顯示本次取得的 Token Transfer 數、入金候選數、唯一配對數及已展開的 Relay 路徑數；最多展開 10 筆可唯一配對的底層入金。一般索引或定向查詢達設定上限時會標示資料不完整。
- 出金最多查 5 個 Request、每條目的路徑 8 個地址、每地址 5 個轉出分支，受使用者選定跳數限制。查詢 BNB Chain 近期最多 100 筆、Blockscout 單頁最多 50 筆事件。後續轉出可能混有原有餘額，**不是同一筆款項的逐筆歸屬證明**。
- 選取 Polygon 步驟後可按「讀取選取地址合約結構」；以固定最新區塊唯讀探測 `owner()`、`factory()`、`id()`、ERC-1167／ERC-1967 implementation 特徵。可停止；未知介面、ABI 未驗證、其他代理型式保持未知，不自動定性為 Polymarket DepositWallet。這不是交易當時的歷史控制權解析。
- 文字與 CSV 匯出保留 Request ID、鏈別、Token 合約、原有證據欄位與白話解釋。CSV 對可能被 Excel 當成公式的外部文字加前置單引號，原值仍在文字報告保留。
- 「匯出證據包」會產生 ZIP，包含文字報告、CSV、SVG 流程圖、本次查詢資料快照及 SHA-256 完整性清冊。SHA-256 不是數位簽章；司法檢視、完整 YES／NO／Shares 解析與主路徑釘選仍未完成，現有輸出仍是初步分析資料包，不代表法定證據保全程序已完成。

技術依據：[Relay v3 欄位與遷移文件](https://docs.relay.link/references/api/api_guides/migrating-to-requests-v3)、[ERC-1967](https://eips.ethereum.org/EIPS/eip-1967)、[ERC-1167](https://eips.ethereum.org/EIPS/eip-1167)。

## 測試

```powershell
py -3 -m unittest discover -s tests -v
```

全案目前包含 **114 項單元測試**（涵蓋分析邏輯、時間錨定、跨鏈穿透、CSV 投注候選、投注語意精確配對、歷史查詢範圍、SVG 匯出、GUI 佈局、Provider 健全性防禦、法證入金路徑分類、函調候選清單提煉、個人錢包遞迴向上追查、歷史最早 POL 燃料開戶來源排序檢驗、EOA 逐筆本金嚴格分級與金額不符降級防護、模型序列化與 PyWebView Controller 初始化），無桌面環境下自動略過 Tkinter 視窗測試，執行結果應為全數 `OK` 通過。
