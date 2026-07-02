# 部署指南 — Railway

## 後端部署步驟

### 1. 建立 Railway 專案
1. 前往 https://railway.app 登入
2. 點擊 "New Project" → "Deploy from GitHub repo"
3. 選擇 `finance/backend` 資料夾

### 2. 設定環境變數
在 Railway 的 Variables 頁籤加入：

```
FINMIND_TOKEN=你的FinMind Token
FUGLE_API_KEY=你的富果API Key
DISCORD_TOKEN=你的Discord Bot Token
DISCORD_CHANNEL_ID=你的頻道ID
PORT=8000
```

### 3. 部署
Railway 會自動偵測 `requirements.txt` 並安裝依賴。
啟動指令已在 `railway.json` 和 `Procfile` 中設定。

### 4. 取得後端 URL
部署完成後，Railway 會給你一個 URL（如 `https://your-app.railway.app`）。
把這個 URL 設定到前端的 `.env`：
```
VITE_API_URL=https://your-app.railway.app/api
```

---

## 前端部署步驟（Vercel）

### 1. 建立 Vercel 專案
1. 前往 https://vercel.com 登入
2. Import `finance/frontend` 資料夾
3. Framework Preset: Vite

### 2. 設定環境變數
```
VITE_API_URL=https://your-backend.railway.app/api
```

### 3. 部署
Vercel 會自動建置並部署。

---

## 注意事項
- Railway 免費方案有使用時數限制（每月 500 小時）
- 如果需要 24/7 在線，建議升級付費方案（$5/月）
- Discord Bot 需要穩定的網路連線，Railway 的 DNS 解析沒有問題
- SQLite 快取在 Railway 的 ephemeral storage 中，重新部署會清空（可接受，會自動重建）
