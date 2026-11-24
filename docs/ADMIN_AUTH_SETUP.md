# 管理者登入部署設定

本專案目前採用單一管理者登入，暫不建立員工帳號、角色或權限資料表。登入只保護系統入口與所有業務 API；健康檢查 `/health`、`/health/db` 保持公開，供 Render 檢查服務狀態。

## Render 環境變數

在 Render 的 `gold-jewelry-erp` Web Service → Environment 設定以下值：

| Key | 設定方式 |
| --- | --- |
| `ENVIRONMENT` | `production` |
| `APP_MAINTENANCE_MODE` | 初期保持 `true` |
| `ADMIN_USERNAME` | 自訂管理者帳號 |
| `ADMIN_PASSWORD` | 建議至少 16 字元、不可重複使用的強密碼 |
| `SESSION_SECRET_KEY` | 至少 32 字元的高熵隨機字串 |
| `SESSION_MAX_AGE_SECONDS` | `2592000`（目前 Render 正式環境為 30 天） |
| `SESSION_COOKIE_SECURE` | `true` |

帳號、密碼及簽章金鑰只填在 Render Environment，不要放進 GitHub 檔案、程式碼、Issue 或 PR。建議使用密碼管理器產生並保存管理者密碼與簽章金鑰。不要把密碼貼到 ChatGPT 對話。

## 安全啟用順序

1. 先合併含登入功能的 PR，等待 Render 部署完成。維護模式仍為 `true`，因此系統不會提前對外開放。
2. 在 Render 設好上表全部登入環境變數，確認更新完成。
3. 確認 `/health` 回傳 `{"status":"ok"}`。
4. 最後才將 `APP_MAINTENANCE_MODE` 改成 `false`。
5. 開啟 `/login`，使用管理者帳密登入；登入後才可進入 `/app`。
6. 登出會清除瀏覽器的 HttpOnly Cookie。Cookie 使用 Secure（HTTPS）、HttpOnly、SameSite=Strict；目前 Render 設定有效 30 天。每個瀏覽器／裝置第一次都要登入一次，之後換 Wi-Fi 或手機網路不會使 Cookie 失效。

## 未完成設定時的保護

在 `ENVIRONMENT=production` 下，只要登入設定不完整，所有非健康檢查路徑都會回傳 HTTP 503，不會退回無登入保護的模式。維護模式開啟時，仍優先回傳維護訊息。

## 登入失敗防護

- 同一來源在 15 分鐘內連續輸入 5 次錯誤帳密，第 5 次起會收到 HTTP 429，並暫停該來源登入 15 分鐘。
- 只在記憶體保存經 HMAC 處理的來源識別碼，不保存原始 IP；成功登入會清除該來源先前的錯誤次數。
- 目前 Render 服務維持單一執行個體與單一 Uvicorn worker，因此這個階段可跨一般請求生效。
- **限制：** 記憶體計數會在服務重啟／重新部署時清空，也不會跨多個執行個體或 worker 共用。正式多人使用或擴充執行個體前，必須改成共用的持久化速率限制儲存（例如 Render Key Value），不能把此版本視為跨執行個體的完整防暴力破解方案。

## 範圍與限制

- 這是單一管理者帳號，不是多員工帳號或細項權限系統。
- 目前密碼由 Render 環境變數提供，不存入資料庫。
- Session 為簽章 Cookie；登出會清除目前瀏覽器 Cookie。若懷疑 Cookie 外洩，應立即輪替 `SESSION_SECRET_KEY`，使舊 Session 全部失效。
- 登入與修改資料的 POST 請求會檢查 Origin／Fetch Metadata，拒絕跨來源請求。
