# 15_chainflow-inspector 專案規則

本檔只寫本專案專屬限制；全域開發憲法維護於 `00_Dev-Control-Center\configs\AGENTS.md`，不在此複製。

- **性質**：鏈上證據蒐集器與診斷工具（Python 3.13）。程式負責可重現的資料蒐集與診斷，Agent 或分析人員負責研判；地址分類與資金關聯不是自然人身分或違法事實的認定。
- **執行環境**：使用專案 `.venv`（完整 Python 3.13），一律以 `.venv\Scripts\python.exe -B -s` 執行與安裝套件，不依賴全域 `python` 或 `py`。
- **啟動與測試**：雙擊 `run.bat`；測試使用 `.venv\Scripts\python.exe -B -s -m unittest discover -s tests -v`。
- **敏感資料**：`settings.json` 是本機設定且已被忽略，不得提交；公開範例只放 `settings.example.json`。歷史查詢資料與報告（`history/`、`reports/`）不得加入版本庫或貼到公開文件。
- **版本**：目前版本以 `README.md` 開頭標示為準，尚無 GitHub Release；對外發布前先在 `00_Dev-Control-Center` 執行 `python scripts/check_release_versions.py --online` 核對。
