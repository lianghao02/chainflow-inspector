# 鏈流查核｜ChainFlow Inspector

> **目前版本**：`v1.4.0`（2026-09-30）

**公開鏈上資金關聯分析工具。**供臺灣警務案件的公開鏈上資料初步分析使用。工具透過公開 RPC、Blockscout API 與使用者自行維護的公開地址標籤查詢資料；支援匯入 PolygonScan Token Transfers CSV 作為歷史索引，不使用網頁爬蟲，也不內建 API 金鑰。採用 PyWebView 搭配本機 HTML/CSS/原生 JS 現代化法證工作台（支援可互動 SVG 圖譜與 5 大資料頁籤），並保留 Tkinter 作為無 WebView 環境下的自動備援。

> **法律與證據界線：** 地址分類、資金關聯與交易所標籤，不是自然人身分、實際控制權或違法事實的認定。交易所 KYC、IP 與帳戶控制資料，仍須依正式法定程序調取並由承辦人員核實。

## 功能

- 輸入 Polygon `Tx Hash` 或 EVM `Wallet Address`。
- 「Polymarket／Relay 資金鏈」模式：可輸入**下注 Tx Hash**或 **Polymarket 錢包地址**。Tx Hash 模式會列出同筆批次撮合內全部 pUSD 扣款候選；地址模式會從近期 pUSD／USDC 入金自動反查鑄造、Relay 與來源鏈。
- **支援歷史 CSV 索引離線穿透**：高頻交易或歷史久遠地址（超出公開 Explorer 一般索引查詢範圍者），可匯入 PolygonScan 匯出的 Token Transfers CSV 作為候選索引；工具依「使用者提供之歷史索引 ＋ Polygon RPC 鏈上即時核實」原則，由鏈上 Receipt 解碼底層 USDC.e 出資人與 Relay 跨鏈來源，突破公開 API 深度限制。
- **法證入金 7 大路徑分類**：自動將入金關聯劃分為「交易所直提」、「跨鏈橋／Relay」、「法幣／信用卡入金服務商」、「DEX 兌換」、「外部錢包轉入」、「Polymarket 平台內部回款／贖回」與「未能分類」。
- **函調候選清單（Subpoena Candidates）提煉**：逐筆提煉可向執法機關發函調取之具體對象，自動標註「可函調 KYC」、「僅供上游追蹤」或「不可作 KYC 終點」，並提供法定限制與資金池混合警示，支援一鍵匯出 `subpoena_candidates.csv`。
- **核心儲備代幣軌道透明稽核**：定向檢索 USDC、USDC.e、pUSD、USDT，公開記錄檢索狀態、頁數、筆數、起訖區塊；若觸及單次上限強制揭露「歷史未完整」警示，拒絕靜默略過。
- **可互動現代化 HTML 工作台**：整合 SVG 資金流程圖（支援 Pan/Zoom、視角重設、主線/跨鏈/出金多維度過濾）、三欄佈局、狀態燈號與底部五大資料抽屜（投注解碼、入金路徑、函調清單、查詢軌道、法證報告）。
- pUSD 批次鑄造會以目標收款地址、金額與 Log 順序配對底層 USDC；若同筆交易仍有多筆同額來源，顯示「歸屬待確認／關聯不足」並停止向上串接，避免把其他錢包補款列為目標來源。
- 若目的鏈補款命中 Relay 公開索引，自動還原來源鏈、來源資產、原始入金者、Relay 收款合約及來源鏈 Tx Hash；追蹤深度 4～5 跳時再續查來源鏈上游與交易所公開標籤。來源為 TRON 時，會以 Tronscan 公開 TRC-20 紀錄續追並保留公開標籤。
- 解析交易基本資料與 Receipt 內 ERC-20 Transfer；提示 Polymarket Conditional Tokens 的 ERC-1155 相關事件。
- 上游／下游追蹤 1 至 5 跳（預設 4 跳），逐跳保存 Tx Hash、時間、Token／金額、From／To、標籤來源、信心與判定。
- 地址類別支援交易所、Bridge、DEX、Polymarket、未知地址等；內建少量已實際查核的公開合約／交易所標籤，並記錄標籤來源與查核日期。其餘由使用者提供有證據的自訂標籤。
- 判定固定使用：`已確認`、`高度可能`、`僅資金關聯`、`未知`。
- 匯出 UTF-8 案件紀錄文字或 Excel 可讀取的 CSV。
- 資金流程圖以入金、平台內部與出金分段，段內按照臺灣時間由舊到新呈現垂直證據鏈；交易箭頭顯示 Token／金額、時間及縮短 Tx。相同 Relay Request 的唯一來源／目的交易才顯示時間戳差，**不是服務處理耗時**；負值保留而不取絕對值。
- 流程圖支援路徑篩選、縮放、捲動、複製 Tx Hash、開啟 Explorer，以及長時間查詢的進度與安全停止；文字明細仍完整保留。
- 經典三欄式工作台（Inspector 檢視模式）：左欄「查詢目標」與設定、中欄「資金流程圖」與「文字明細」、右欄全高「證據詳情」；雙向分隔線可自由拖曳調整寬度，日期、CSV 與本機紀錄預設收合於「資料範圍（選填）」，右欄內建獨立垂直捲軸。
- CSV 模式顯示檔案筆數、臺灣標準時間範圍、查詢階段與候選完成筆數；四種匯出格式集中於單一「匯出」選單。

## Windows 執行

1. 安裝 [Python 3.11 以上](https://www.python.org/downloads/windows/)，安裝時勾選 **Add Python to PATH**。
2. 直接雙擊 `run.bat`。
3. 在左欄輸入交易雜湊或錢包地址，選擇追蹤跳數，按「追蹤 Polymarket 資金鏈」或「一般資金追蹤」。
4. 在中欄「資金流程圖」由上到下沿箭頭查看資金時間序列；點選箭頭可於右欄「證據詳情」即時核對查核結論、發送地址（Transfer From）、收款地址（Transfer To）、Tx Hash、摘要、標籤、信心與限制；其他技術欄位（區塊、Log Index、Token 合約、Request ID）可按需展開。「文字明細」保留原始逐筆內容。

如要反查下注本金，可貼入**下注交易雜湊**或 **Polymarket 錢包地址**後按「Polymarket／Relay 資金鏈」。結果中的「下注前補款／地址入金」是候選資金池；「pUSD 底層入金」是鑄造 pUSD 時真正投入 USDC 的地址；「Relay 來源鏈」才是跨鏈前的原始交易。工具會將 Polymarket Exchange、Onramp、Reward Distributor、pUSD 合約、Relay Solver 與零地址鑄造分開標示，不會把它們誤當交易所來源。

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

全案目前包含 **110 項單元測試**（涵蓋分析邏輯、時間錨定、跨鏈穿透、CSV 投注候選、投注語意精確配對、歷史查詢範圍、SVG 匯出、GUI 佈局、Provider 健全性防禦、法證入金路徑分類、函調候選清單提煉、模型序列化與 PyWebView Controller 初始化），執行結果應為全部 `OK` 通過。
