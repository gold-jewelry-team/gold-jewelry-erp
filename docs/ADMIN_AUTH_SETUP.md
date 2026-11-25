# 管理者登入、員工登入與公司權限部署設定

本文件描述 Phase D 的雙軌登入與公司範圍授權。管理者帳號與 Google 員工帳號是兩條不同的登入路徑，兩者不能互相取代。

## 一、管理者登入（既有帳密）

管理者使用 Render 環境變數提供的帳號密碼，進入系統管理工作區。帳號密碼不寫入 GitHub、不存入資料庫，也不放在前端程式。

| 環境變數 | 用途 | 建議 |
| --- | --- | --- |
| `ENVIRONMENT` | 執行環境 | Staging 設為 `staging`；正式環境設為 `production` |
| `APP_MAINTENANCE_MODE` | 維護模式 | 正式切換期間可先設為 `true` |
| `ADMIN_USERNAME` | 管理者帳號 | 使用專用管理帳號 |
| `ADMIN_PASSWORD` | 管理者密碼 | 至少 16 字元的高熵隨機密碼 |
| `SESSION_SECRET_KEY` | Cookie 簽章金鑰 | 至少 32 字元的高熵隨機字串 |
| `SESSION_MAX_AGE_SECONDS` | 管理者 Session 有效秒數 | 依環境設定；Staging 目前為 43200 秒 |
| `SESSION_COOKIE_SECURE` | HTTPS Secure Cookie | Render HTTPS 環境設為 `true` |

**密碼及簽章金鑰只在 Render Environment 管理。** 不要把它們貼到 GitHub、Issue、PR、程式碼或一般文件。若要輪替密碼，直接在對應 Render 服務的 Environment 更新 `ADMIN_PASSWORD`；若要使所有既有管理者 Session 失效，輪替 `SESSION_SECRET_KEY`。

管理者登入端點為 `POST /auth/login`；目前管理者身分可由 `GET /auth/me` 確認。登入 Cookie 使用 HttpOnly、Secure（依環境設定）、SameSite=Strict。登出會清除目前瀏覽器的管理者 Cookie。

## 二、Google 員工登入與公司成員

Google OAuth 是員工身分登入路徑，與管理者帳密分離。Google 登入本身不等於獲得公司資料權限。

每次公司範圍 API 請求都會在伺服器驗證：
- Google Session 有效、未到期且未撤銷。
- 使用者帳號啟用中。
- URL 指定的公司仍啟用。
- 使用者在該公司具有明確的 ACTIVE 成員關係。
- 該次操作具有對應資源與動作的有效權限及資料範圍。
- 跨模組資料與操作符合相依模組授權。

Google 登入後進入獨立的 `/employee` 員工工作區，不會取得管理者工作區或管理者 API 權限。PENDING、REJECTED、SUSPENDED 或公司停用中的成員，只能查看自己的申請／狀態資訊，不能操作公司業務資料。

### Google OAuth 環境變數

| 環境變數 | 用途 |
| --- | --- |
| `GOOGLE_OAUTH_ENABLED` | 功能開關 |
| `GOOGLE_CLIENT_ID` | Google OAuth Client ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth Client Secret |
| `GOOGLE_REDIRECT_URI` | Google OAuth callback URL |
| `SESSION_SECRET_KEY` | Google Session 簽章也使用此金鑰 |
| `GOOGLE_SESSION_MAX_AGE_SECONDS` | Google Session 有效秒數 |

Staging 與 Production 目前都維持 `GOOGLE_OAUTH_ENABLED=false`。只有在完成 Google OAuth 設定、回呼網址驗證、資料庫 Migration、Staging 端到端測試，並取得明確啟用授權後，才可以開啟。不可只因為設定了 Google Client ID 就開放登入。

## 三、公司角色與細項權限

Migration `0035_company_role_permissions` 建立公司自訂角色與細項權限資料結構。權限目錄目前為 24 種資源 × 4 種動作：

- 動作：查看（view）、新增（create）、修改（update）、作廢（void）。
- 資料範圍：全公司（ALL）或僅本人建立（OWN）。
- 角色範圍：每間公司各自管理系統角色及自訂角色。
- 成員可同時指派多個角色；允許權限採加總方式合併，ALL 範圍優先於 OWN。
- 自訂角色預設不授予權限；未知或未列入授權目錄的公司 API 一律拒絕。

### 系統角色預設值

| 角色 | 預設權限 |
| --- | --- |
| OWNER（負責人） | 全部資源的四種動作，資料範圍 ALL |
| MANAGER（管理者） | 全部資源僅查看，資料範圍 ALL |
| STAFF（一般成員） | 預設不授予權限，由負責人依工作職務設定 |

### OWN 範圍限制

OWN 目前只適用於獨立交易資料的有限讀取／新增情境：採購、銷售、客戶訂單及營運費用。共用主檔、庫存與金額餘額、銀行對帳、黃金餘額、廠商應付、現金櫃及彙總報表必須使用 ALL。OWN 範圍的修改與作廢目前由伺服器拒絕。

歷史紀錄不會根據推測自動分配建立者；沒有建立者歸屬資料的舊紀錄，不會出現在 OWN 範圍結果中。

## 四、目前員工工作區範圍

目前員工工作區已提供權限導向的唯讀頁面，包括商品／庫存查詢、銷售與退貨紀錄、採購與驗收紀錄、廠商應付與付款紀錄、客戶訂單／訂金／退款紀錄。

以下員工操作流程仍需各自完成畫面、權限相依檢查、錯誤復原及 Staging 驗收，尚不可視為已開放：
- 銷售結帳與退款收付。
- 採購建立與進貨驗收。
- 客戶訂單建立、訂金收款與退款。
- 盤點及盤點差異調整。
- 廠商應付結清。
- 現金櫃收支與每日結帳。

在這些流程完成並通過 Staging 驗收前，不應邀請員工以此版本進行正式日常營運。

## 五、Staging 與 Production 隔離

| 項目 | Staging | Production |
| --- | --- | --- |
| Render | `gold-jewelry-erp-staging-xbk3` | `gold-jewelry-erp` |
| 分支 | `feature/phase-d-company-access-control` | `main` |
| Neon Project | `gold-jewelry-erp-staging` | `gold-jewelry-erp` |
| Migration 0035 | 已套用 | 尚未套用 |
| Google OAuth | 關閉 | 關閉 |

Staging 使用獨立 Neon Project 與 Render Web Service，不可共用 Production 的 `DATABASE_URL`、密碼或 Session 金鑰。Staging 資料庫目前不包含 Production 營運資料。Staging Blueprint 與服務自動部署均關閉；變更程式碼後需明確手動同步／部署 Staging。

**不得因 Staging 測試成功就自動合併 PR、執行 Production Migration 或開啟 Google OAuth。** 正式切換前必須先確認正式資料庫備份與還原方案、Migration 相容性、部署順序、健康檢查、管理者登入，以及回復方案；Production Migration、合併／部署與 OAuth 啟用各自都需要負責人明確授權。

## 六、安全與驗收檢查

- `/health` 與 `/health/db` 保持公開，僅供服務健康檢查；其他管理頁與管理 API 必須有有效管理者 Session。
- 在 `ENVIRONMENT=production` 下，登入環境變數未完整設定時採 fail-closed，非健康檢查路徑回傳 HTTP 503。
- 登入失敗防護目前以單一 Staging／Render 執行個體的記憶體計數器實作；服務重啟會清空計數，不代表多執行個體的共用防暴力破解機制。擴充執行個體前需改用共用持久化速率限制儲存。
- 管理者登入與變更資料的寫入請求會檢查 Origin／Fetch Metadata，拒絕跨來源請求。
- 每次角色、成員或權限修改，都必須同時驗證 UI 行為與伺服器 API；隱藏按鈕或頁面連結不能取代伺服器授權。

### Staging 驗收清單

1. `/health/db` 回傳 HTTP 200，確認 Staging 資料庫可連線。
2. 未登入時，管理者頁面及 `/admin/api` 應拒絕存取。
3. 使用 Staging 管理者帳密登入，`/auth/me` 應回傳 administrator。
4. 建立測試公司或選擇測試公司，驗證 OWNER／MANAGER／STAFF 預設權限。
5. 建立自訂角色，變更查看／新增／修改／作廢與 ALL／OWN，儲存後重新載入確認持久化。
6. 指派成員多個角色，驗證權限加總及 ALL 優先規則。
7. 使用員工測試帳號驗證未授權 API 被拒絕、OWN 只能查詢本人建立的支援資料，且不能修改或作廢。
8. 登出後再次確認管理者 API 不再可用。

CI 另有獨立 PostgreSQL／Chromium 測試，包含 Migration 0035 upgrade、downgrade、clean re-upgrade、角色權限管理 UI 與管理者登入 E2E；CI 成功不等於 Production 已套用 Migration 或 Google OAuth 已啟用。
