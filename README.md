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
- Alembic Migration 完整版本鏈由 `alembic/versions/` 管理；新增版本必須提交 Migration 檔案，不可只修改資料模型。
- GitHub Actions CI 使用獨立 PostgreSQL 測試資料庫，驗證完整升級、降版及重新升級流程；CI 不連接 Neon production。
- 正式 Neon production 的實際版本以資料庫中的 `alembic_version` 及手動 Migration Workflow 結果為準，不以程式碼版本或 Render 部署成功推定。

## 正式環境 Migration 與部署流程
正式環境的資料庫結構變更與應用程式部署分開執行。Docker 容器啟動時只啟動 FastAPI，不會自動執行 `alembic upgrade`；Render 自動部署也不得成為正式資料庫 Migration 的觸發方式。

需要新增資料庫結構時，採取向前相容的分階段流程：
1. **先提交 Migration-only PR**：只加入向前相容的資料庫變更，確認 GitHub Actions CI 全部成功後合併。
2. **執行正式 Migration**：合併後，前往 GitHub Actions，手動執行 `Manual Production Alembic Migration`，並在 `confirm_production` 欄位輸入 `RUN PRODUCTION MIGRATION`。此 Workflow 固定從 `main` 讀取 Migration，先顯示現況，再執行 `alembic upgrade head`，最後比對資料庫目前版本與 Repository 的 Alembic heads。
3. **確認 Migration 成功**：只有 Workflow 成功且 Neon production 的版本已到達程式碼目前的 Alembic heads，才進行依賴新結構的應用程式 PR。
4. **再部署應用程式**：合併應用程式 PR 後，Render 應設定為 `After CI Checks Pass`（Blueprint 欄位 `autoDeployTrigger: checksPass`），只在該提交的 GitHub CI 全部通過後部署；接著檢查 Render Deploy 狀態及 `/health`。

若變更涉及刪欄位、改名、資料轉換或其他不向前相容操作，必須拆成多階段 expand/contract 變更，先確保舊版與新版應用程式可在過渡期間共存，不可把破壞性 Migration 與依賴它的新程式碼一次部署。沒有資料庫結構變更的程式碼可照一般 PR 流程合併。

**安全界線：** 不得由一般 CI、Docker 啟動程序或 Render 自動部署執行 production Migration。正式 Migration 僅能由上述手動 Workflow 執行，且必須有使用者明確授權；不可將 CI 測試資料庫與 Neon production 混用。

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

## 目前部署與資料安全狀態
- Render 正式服務：`https://gold-jewelry-erp.onrender.com`
- 使用者介面：`/app`；API 文件：`/docs`；健康檢查：`/health`
- Render Blueprint 將 `autoDeployTrigger` 設為 `checksPass`；Render Dashboard 的 Auto-Deploy 也應確認為 `After CI Checks Pass`，避免 CI 尚未完成就部署。每次部署仍須確認 Render Deploy 狀態及健康檢查。
- 正式 Neon production 資料庫已存在；不可將本機測試、CI 測試資料庫與 production 混為一談。
- 未經使用者明確授權，不得對 production 執行 Migration、資料寫入、刪除或重設。
- 測試期間不建立虛構商品或交易資料；商品建檔及實際標籤列印須使用使用者提供的真實資料與設備驗證。

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

The snapshot includes completed sales, returns created on that business date, signed net sales by the original sale's payment method, and actual collections, customer refunds, and supplier disbursements recorded on that business date. The business-day boundary is Asia/Taipei. A site may be closed only once per date. Once closed, new sale completions and returns for that business date are blocked to keep the snapshot stable.

This is an operational sales/return summary, not a cash count, bank reconciliation, or proof that a card/bank settlement has arrived. Actual tender collection, cash drawer variance, refund execution, and bank settlement matching remain separate finance workflows. There is no reopen or edit endpoint in this phase; corrections require a controlled adjustment workflow rather than changing a historical snapshot.


### Payment transactions

- `POST /companies/{company_id}/sales/{sale_id}/payments` — record a partial or full payment/collection for a completed sale.
- `GET /companies/{company_id}/sales/{sale_id}/payments` — list payment transactions for a sale.
- `POST /companies/{company_id}/sales/returns/{return_id}/payments` — record the actual refund or additional collection for a return.
- `GET /companies/{company_id}/sales/returns/{return_id}/payments` — list payment transactions for a return.

Payment transactions are append-only, positive-amount entries with direction `IN` or `OUT`. Sale obligations with a positive final amount are collected (`IN`); negative sale amounts are paid to the customer (`OUT`). For returns, the signed settlement reversal determines the direction. Partial payments are supported, and the API rejects amounts above the remaining obligation. Payment method can be CASH, CARD, TRANSFER, or OTHER.

Daily closing now separately reports expected sales/return totals and actual collections, refunds, and net cash flow by payment method, including supplier outflows. A recorded payment uses the actual payment date in Asia/Taipei for closing. This ledger records payment events but does not yet connect to a bank, card acquirer, or payment gateway. Payment entries are immutable; a controlled reversal/correction workflow is a later phase.


### Supplier accounts payable

- `POST /companies/{company_id}/supplier-payables/bills` — record a supplier invoice/bill with an explicitly entered amount; optionally link it to a purchase order.
- `GET /companies/{company_id}/supplier-payables/bills` — list bills with paid/outstanding balances; filter by supplier, status, or due date.
- `GET /companies/{company_id}/supplier-payables/bills/{bill_id}` — retrieve a bill.
- `POST /companies/{company_id}/supplier-payables/payments` — record one supplier disbursement allocated across one or more bills.
- `GET /companies/{company_id}/supplier-payables/payments` and `GET /companies/{company_id}/supplier-payables/payments/{payment_id}` — list or retrieve supplier disbursements.

Supplier invoice amounts are entered explicitly and are not inferred from purchase-line unit costs, because the current purchase-line cost basis has not yet been formalized as a universal payable formula. Payments support partial settlement and multi-bill allocation, reject overpayment and mixed currencies, and are included as supplier cash outflows in daily closing. Supplier payment entries are append-only; correction/reversal workflow is a later phase.
