# 黃金珠寶進銷存暨營運管理系統

本專案為獨立的黃金珠寶門市／倉庫管理系統，與家庭記帳系統使用不同 Repository、資料庫及部署服務。

## 技術架構
- Python 3.12、FastAPI
- PostgreSQL、SQLAlchemy 2.x、Alembic
- Docker、GitHub Actions
- Render 雲端部署；保留店內 LAN 部署彈性

## 已建立的核心基礎
- 公司、據點、儲存位置
- Decimal 計價服務：舊金折算、工錢、刷卡費、整數元捨入，以及進貨成本計算
- 公司共用與據點覆寫的買入／賣出金價歷史及有效價格查詢
- 銷售訂單與逐商品成交價格快照
- 商品分類、單件商品主檔與公司內唯一商品編號／條碼
- 庫存異動流水：進貨、銷售、調撥、調整、退貨及送修／維修返還
- 供應商主檔、採購單、採購明細、送出／取消及部分到貨驗收 API
- 驗收成功才建立入庫流水；部分到貨按比例分配重量，最後一批吸收精度尾差

## 資料模型與 Migration
Alembic 版本鏈：
1. `0001_core`：公司、據點、儲存位置
2. `0002_gold_prices`：金價歷史
3. `0003_sales_snapshots`：銷售訂單及成交快照
4. `0004_products_inventory`：商品分類、商品主檔及庫存異動流水
5. `0005_suppliers_purchasing`：供應商、採購單及採購明細

以上僅代表程式碼與 Migration 檔案已建立；**尚未建立正式 Neon 資料庫，也尚未對任何正式資料庫執行 Migration**。

## 重要設計
- 每筆商品資料代表一件可獨立追蹤的珠寶商品；條碼在同一公司內唯一。
- 庫存以異動流水為依據計算，不直接覆寫歷史庫存紀錄。
- 調撥必須同時記錄來源與目的儲存位置。
- 金價變更以新增歷史紀錄處理；已完成交易保存成交當下的金價、單位及計價規則快照。
- 舊金比例、刷卡費率與計價規則需可版本化；舊版公式只作為相容參考，不應擅自擴大套用範圍。
- PostgreSQL 不直接暴露公網；Render Private Network 不等同店內 LAN。
- 尚未確認正式營運規則的流程，不會以示意公式直接作為正式成交依據。

## 本地啟動
1. 複製 `.env.example` 為 `.env` 並設定 `DATABASE_URL`。
2. 安裝依賴：`pip install -r requirements.txt`
3. 啟動：`uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
4. 開啟 `/docs` 查看 API。

## API
- `GET/POST /companies/{company_id}/suppliers`：供應商查詢與新增
- `GET/PATCH /companies/{company_id}/suppliers/{supplier_id}`：供應商明細與更新
- `POST /companies/{company_id}/suppliers/{supplier_id}/deactivate`：停用供應商
- `GET/POST /companies/{company_id}/purchases`：採購單查詢與建立
- `GET /companies/{company_id}/purchases/{purchase_id}`：採購單明細
- `POST .../{purchase_id}/submit|cancel|receive`：送出、取消及驗收入庫
- `GET /companies/{company_id}/inventory/stock`：依據點、儲存位置、商品及時間查詢庫存
- `GET /companies/{company_id}/inventory/movements`：查詢異動流水
- `POST /companies/{company_id}/inventory/adjustments`：盤點增減調整
- `POST /companies/{company_id}/inventory/transfers`：儲存位置調撥；來源庫存不足會拒絕

## 尚待開發
- 銷售結帳與銷售出庫的原子化流程
- 銷售結帳流程與庫存扣帳的原子性交易
- 退貨、盤點、差異調整、送修流程
- 權限、稽核、報表、備份與復原測試
- PostgreSQL 真實環境 Migration 驗證

## 資源與上線安全
不會在未經確認前建立 Neon／Render 付費資源、部署正式服務或執行正式資料庫 Migration。正式上線前仍須完成完整測試、資料庫演練、權限與資安檢查。


### Sales API

Sales are created as drafts with server-calculated prices and immutable product / gold-price snapshots. The backend requires an effective BUY and SELL gold price at the time of creation, and the price unit must match the product weight unit.

- `POST /companies/{company_id}/sales` — create a priced draft; each line identifies one individually tracked product and its source storage location.
- `GET /companies/{company_id}/sales/{sale_id}` — read the sale and its snapshots.
- `POST /companies/{company_id}/sales/{sale_id}/complete` — atomically append one SALE inventory movement per line and complete the sale.
- `POST /companies/{company_id}/sales/{sale_id}/void` — void a draft only. Completed sales must use a future return workflow.

The sale-line inventory references are nullable at the database level for historical compatibility, but the sales API requires both product and source location. A sale cannot complete twice; stock insufficiency rolls back the whole completion transaction.


### Sales returns

- `POST /companies/{company_id}/sales/{sale_id}/returns` — return one or more individually tracked items from a completed sale. Provide the original `sale_line_ids`; the API appends a `RETURN` movement to each item's original source location.
- `GET /companies/{company_id}/sales/{sale_id}/returns/{return_id}` — retrieve the return and item snapshots.

Each sale line can be returned only once because each product row represents one individually barcoded item. Draft or void sales cannot be returned. Return creation and all stock-restocking movements share one database transaction; a failure rolls back the entire return.

The signed `settlement_reversal_amount` is the opposite of the original sale-line settlement: a negative value means the store owes the customer, while a positive value means the customer owes the store. This records the settlement obligation only; it does **not** issue a cash/card/bank refund. Actual payment/refund execution will be handled by the finance and payment ledger workflow.


### Daily business closing

- `POST /companies/{company_id}/sites/{site_id}/daily-closings` — create the one-time closing snapshot for a Taipei business date.
- `GET /companies/{company_id}/sites/{site_id}/daily-closings` — list closing snapshots; optional `from_date` and `to_date` filters.
- `GET /companies/{company_id}/sites/{site_id}/daily-closings/{closing_id}` — retrieve the snapshot and payment-method summaries.

The snapshot includes completed sales, returns created on that business date, and signed net sales by the original sale's payment method. The business-day boundary is Asia/Taipei. A site may be closed only once per date. Once closed, new sale completions and returns for that business date are blocked to keep the snapshot stable.

This is an operational sales/return summary, not a cash count, bank reconciliation, or proof that a card/bank settlement has arrived. Actual tender collection, cash drawer variance, refund execution, and bank settlement matching remain separate finance workflows. There is no reopen or edit endpoint in this phase; corrections require a controlled adjustment workflow rather than changing a historical snapshot.
