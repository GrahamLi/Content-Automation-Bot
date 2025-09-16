# Vibe Coding 專案 - Notion 整合功能開發 ToDo List

> **目標**：將專案自動抓取的內容（摘要、逐字稿等），儲存到指定的 Notion 資料庫中，打造一個自動化的知識管理系統。
> **狀態**：規劃中

---

### Git 工作流程指南

- **同步遠端更新**：在開發新功能前，先執行 `git pull`（例如 `git pull origin main`），確保本機分支與遠端保持一致。
- **測試遠端 PR**：如需驗證尚未合併的 PR，可執行 `git fetch origin pull/<PR#>/head:feature` 將其抓到本地，接著 `git checkout feature` 在獨立分支進行測試。
- **套用單獨的 Patch**：收到 `.patch` 檔或郵件 patch 時，可使用 `git apply <patch>` 將改動直接套用到工作目錄，再進行驗證與提交。

> ⚠️ 請避免從 diff 介面手動複製貼上整段程式碼；改用上述 Git 指令來套用變更，以降低遺漏或貼錯的風險。

### 階段一：Notion 端設定 (Prerequisites)

在開始寫程式碼之前，必須先在 Notion 完成的準備工作。

- [ ] **建立一個新的 Notion Integration**
  - 前往 Notion 的 [My Integrations](https://www.notion.so/my-integrations) 頁面。
  - 點擊 "New integration"，為其命名（例如："Vibe Coding Bot"）。
  - 選擇它關聯的 Workspace。

- [ ] **取得並儲存 Internal Integration Token**
  - 建立後，在 Integration 的設定頁面複製 "Internal Integration Token"。
  - **(重要)** 將這串 `secret_...` 開頭的 Token 妥善保管，稍後要寫入 `config.json`。

- [ ] **建立一個用於存放內容的 Notion 資料庫 (Database)**
  - 在你的 Notion Workspace 中，建立一個新的頁面，並選擇「Database - Full page」。
  - 將其命名為「自動化內容知識庫」或你喜歡的名稱。

- [ ] **設計資料庫欄位 (Properties)**
  - 根據我們的需求，建立以下建議欄位：
    - `標題` (Title)：預設欄位，用於存放文章/影片標題。
    - `來源網址` (URL)：用於存放原始連結。
    - `類型` (Select)：用於標示內容來源，例如 `YouTube`, `RSS`。
    - `發布日期` (Date)：用於存放原始發布日期。
    - `AI 摘要` (Text)：用於存放 LLM 產生的摘要。
    - `關鍵字` (Multi-select)：(可選) 用於存放內容的關鍵字標籤。

- [ ] **分享資料庫給建立好的 Integration**
  - 回到你剛剛建立的資料庫頁面。
  - 點擊右上角的 "Share" -> "Invite"。
  - 在搜尋框中找到並選取你建立的 Integration ("Vibe Coding Bot")。
  - 確保給予它 "Can edit" (可以編輯) 的權限。

### 階段二：Python 環境設定

- [ ] **在虛擬環境 (`venv`) 中安裝新的函式庫**
  - 啟動虛擬環境 (`venv\Scripts\activate`)。
  - 執行 `pip install notion-client`。

- [ ] **將 `notion-client` 新增到 `requirements.txt` 中**
  - 打開 `requirements.txt` 檔案，在最後一行新增 `notion-client`。

### 階段三：程式碼開發

- [ ] **更新 `config.json`**
  - 新增兩個欄位：
    - `"NOTION_TOKEN": "貼上你取得的 Internal Integration Token"`
    - `"NOTION_DATABASE_ID": "貼上你的 Notion 資料庫 ID"`
  - (提示：資料庫 ID 是 Notion 網址中，workspace 名稱後面，`?` 問號前面那串長長的亂碼)。

- [ ] **編寫 Notion 處理函式** (建議在一個新檔案 `notion_handler.py` 中，或直接加入 `main.py`)
  - [ ] 編寫初始化 Notion Client 的程式碼。
  - [ ] 編寫 `add_item_to_notion(item_data)` 函式，這是寫入操作的核心。
    - 函式需接收一個包含標題、網址、摘要等資訊的字典。
    - 函式內部需要建構符合 Notion API 格式的 JSON 物件。
    - 函式需處理 API 請求，並包含錯誤處理機制。

### 階段四：整合與測試

- [ ] **在 `main.py` 中整合 Notion 功能**
  - 從 Notion 處理模組匯入 `add_item_to_notion` 函式。
  - 修改 `process_item` 函式，在 `save_to_markdown` 之後，新增一行呼叫 `add_item_to_notion` 的程式碼，將處理好的內容傳入。

- [ ] **進行測試**
  - 執行 `python content_automation_bot.py`。
  - 檢查程式是否能成功執行，並且在 Notion 資料庫中看到新的一筆資料被自動新增。
  - 確認所有欄位（標題、網址、摘要等）都正確對應並填入。

### 階段五：未來可擴充功能 (可選)

- [ ] **雙向同步**：讓程式在處理前，先讀取 Notion 資料庫，檢查該網址是否已存在，作為另一層的重複內容過濾。
- [ ] **更新 Notion 頁面**：如果發現內容有更新（例如摘要重新產生），程式可以選擇更新現有的 Notion 頁面，而不是新增一筆。
- [ ] **將逐字稿存入頁面內容**：目前是將摘要存入欄位，未來可將完整的逐字稿寫入到該筆資料的「頁面內容 (Page Content)」中。