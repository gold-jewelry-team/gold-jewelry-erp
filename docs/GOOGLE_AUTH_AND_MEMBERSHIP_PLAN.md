# Google 登入與家庭成員授權架構

## 目標與已確認決策

- 每位家人使用自己的 Google 帳號登入，不共用 Google 帳號。
- 保留目前管理者 `owner` 帳密作為備援登入方式。
- Google 身分驗證成功不等於取得資料權限；新帳號預設為待核准。
- 由管理者核准成員加入公司／店舖，停用成員後立即拒絕後續請求。
- 第一階段先提供簡單的成員核准與基本角色；細項功能權限可在後續擴充。
- 手機優先、長輩易用：登入只需按「使用 Google 帳號登入」，不要求自行設定系統密碼或輸入驗證碼。

## 現況盤點（main，PR #347 合併後）

- `app/routers/auth.py` 只有單一管理者帳密登入。
- `app/core/auth.py` 使用簽章 Cookie，Session subject 固定比對 `ADMIN_USERNAME`。
- `app/main.py` middleware 將所有已登入請求視為同一管理者，尚無個別使用者或公司成員授權。
- `companies`、`sites` 已有公司與據點資料模型。
- `company_setup.py` 的公司／據點 API 目前依賴全域登入保護，尚未做成員層級授權。
- 正式資料庫目前已完成 migration `0033_inventory_op_requests`；本文件不執行任何資料庫變更。

## 建議資料模型

### 1. users

代表系統中的自然人帳號，不以 email 當唯一身分。

- `id` UUID primary key
- `display_name` 顯示名稱
- `email` 最近一次驗證過的 Google email（可更新）
- `is_active` 是否允許登入
- `created_at`、`updated_at`

### 2. auth_identities

保存外部登入身分，Google 的穩定識別碼是 `sub`，不是 email。

- `id` UUID primary key
- `user_id` FK users
- `provider`（第一階段固定 GOOGLE）
- `provider_subject` Google OIDC `sub`
- `provider_email`、`email_verified`
- unique `(provider, provider_subject)`

禁止只因 email 相同就自動合併兩個使用者；綁定既有帳號必須由已登入使用者明確完成。

### 3. company_memberships

同一位使用者可加入不同公司，且每家公司分別核准。

- `id` UUID primary key
- `company_id` FK companies
- `user_id` FK users
- `status`: PENDING / ACTIVE / REJECTED / SUSPENDED
- `role`: OWNER / MANAGER / STAFF（第一階段可先只啟用 OWNER、STAFF）
- `approved_by_user_id`、`approved_at`
- `created_at`、`updated_at`
- unique `(company_id, user_id)`

未核准或停用的成員不得讀取該公司的任何業務資料。

### 4. user_sessions（建議）

採用可撤銷的伺服器端 Session，保存 session token 的雜湊、使用者、到期時間、撤銷時間與建立時間。Cookie 只保存高熵隨機 token；停用帳號或撤銷 Session 後，下一個請求即失效。不要將 Google access token 或 refresh token 當成應用程式登入 Session。

## Google OAuth / OpenID Connect 安全要求

- 使用 Authorization Code Flow，啟用 state、nonce 與 PKCE。
- 嚴格驗證 ID Token 的簽章、issuer、audience、expiry、nonce，以及 `email_verified=true`。
- 以 Google `sub` 作為外部身分唯一鍵；email 僅作顯示與聯絡資訊。
- OAuth callback 固定為正式站台的 HTTPS callback；禁止任意 redirect URL。
- Client ID / Client Secret 僅存 Render Environment，不進 GitHub。
- OAuth 失敗不得降級為匿名登入；舊管理者登入保留為獨立備援路徑。
- 不在資料庫保存 Google access token / refresh token，除非未來確有呼叫 Google API 的需求。

## 登入與核准流程

1. 使用者在登入頁按「使用 Google 帳號登入」。
2. Google 完成身分驗證後，後端依 `sub` 查找 `auth_identities`。
3. 若是新身分，建立 user 與對應公司的 PENDING membership；不授予任何業務資料權限。
4. 顯示「帳號已送出申請，請等待管理者核准」。
5. 管理者在「成員管理」查看姓名、已驗證 email、申請時間，按核准或拒絕。
6. 核准後建立 ACTIVE membership；使用者重新登入或刷新 Session 後即可進入系統。
7. 管理者停用成員或撤銷 Session 後，該使用者不能再呼叫業務 API。

若系統有多家公司，登入後不得猜測使用哪家公司；需由管理者指定邀請／申請所屬公司，或讓使用者在有多個 ACTIVE membership 時選擇公司。

## API 與資料隔離要求

- Middleware 只負責驗證 Session，並建立明確的 actor context（user id、登入方式）。
- 每個公司範圍的 API 必須確認 actor 有該 company 的 ACTIVE membership。
- 管理成員、核准申請、停用成員等操作僅 OWNER / MANAGER 可執行。
- 不能只在前端隱藏按鈕；後端每個 API 都要做授權。
- 不能接受使用者自行傳入的 user id 作為操作者；created_by / updated_by 一律由已驗證 actor 注入。
- 逐步將庫存異動、銷售、退貨、採購、付款、日結等寫入資料記錄操作者。
- 保留既有資料；歷史資料的操作者應標示為 LEGACY / SYSTEM，不可虛構成某位家人。

## 分階段實作建議

### Phase A：身分資料與安全基礎
- 建立 users、auth_identities、company_memberships、user_sessions。
- 保留 owner 環境變數登入，並建立可識別的 legacy owner actor。
- 加入測試：Google subject 唯一性、membership 狀態、Session 撤銷、停用使用者。
- 只新增 schema，不改動現有業務資料。

### Phase B：Google OAuth 登入
- 加入 Google OIDC callback、state/nonce/PKCE、cookie session。
- 登入頁新增大按鈕；長輩不需要額外設定密碼。
- 需要管理者先在 Google Cloud 建立本系統專用 OAuth Web Client，並把 Client ID / Secret 設定在 Render。
- Google OAuth 尚未設定時，保留 owner 帳密登入且不顯示可用的 Google 登入按鈕。

### Phase C：成員核准管理
- 建立成員申請、核准、拒絕、停用、撤銷 Session 的管理畫面與 API。
- 首位 OWNER 由既有 owner 管理者安全 bootstrap，不允許任何人自助成為 OWNER。

### Phase D：API 授權與操作者稽核
- 逐批為公司範圍 API 加上 membership/role 檢查。
- 把實際 actor 寫入業務異動與稽核紀錄。
- 完成 API 權限測試後，才開放家人正式使用。

## 上線安全順序

1. 先在測試分支完成模型、測試與 migration。
2. PR 合併前確認 CI、migration upgrade/downgrade、舊 owner 登入相容測試。
3. 正式 Migration 前先建立 Neon snapshot，並由使用者明確授權。
4. 先部署仍保留 owner 備援的程式，再設定 Google OAuth 環境變數。
5. 先用管理者自己的 Google 帳號測試核准流程，再邀請家人。
6. 完成所有公司範圍 API 的後端授權檢查後，才視為可正式多人使用。

## 不在本階段做的事

- 不強迫長輩自行建立系統密碼。
- 不依 email 自動合併帳號。
- 不讓首次 Google 登入者自動取得公司資料權限。
- 不把 Google OAuth client secret 放入 GitHub。
- 不直接修改正式 Render 環境變數或正式資料庫。
- 不在尚未完成後端授權前，開放家人使用正式資料。
