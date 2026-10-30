# GitHub Pages 部署指南（不用覆蓋原本的程式與 README）

本資料包以公開的 `crazylittleJ/epaper-weather-dashboard` v1.2.0 設計，所有連線方式均以原專案 `README.zh-TW.md` 第 8 節為準。網站是純靜態 HTML / CSS，**無須 Jekyll、npm、Python 或 GitHub Actions**，也不會修改你的 Raspberry Pi 韌體/網頁功能。

## 這個 ZIP 的內容

```text
repo 根目錄/
├── (原本的程式、README.md、README.zh-TW.md 都保留)
└── docs/                       ← 請新增的資料夾
    ├── index.html              ← GitHub Pages 手機版說明書
    ├── print-a6.html           ← A6 直式小卡（瀏覽器可列印）
    ├── README.md               ← 家人專用 Markdown 說明
    ├── .nojekyll
    └── assets/
        ├── style.css
        ├── wifi-setup-demo.jpg ← 你提供的實機 Wi-Fi 示意照片
        ├── manual-qr.png      ← QR 指向公開說明書（非配對碼）
        └── favicon.svg
```

另提供 `README_GITHUB_SECTION.md`：供你**複製內容**加到原專案根目錄 `README.md` 或 `README.zh-TW.md`，不要用它取代原 README。

## 關於組裝完成照片

網站包含：

- 你先前提供的 `wifi-setup-demo.jpg`：Wi-Fi 配對流程說明用圖，已放入 ZIP。
- 原本 GitHub README 的實機成果 `img/result_photo_cat.jpg` 與 `img/result_photo_milkyway.jpg`：直接引用 GitHub 公開圖片網址，瀏覽網站時需要可存取 GitHub raw 圖片。

**此回合的「最新組裝完成外觀照片」並未以可讀取的附件檔案出現在執行環境，因此目前無法把那張新圖直接打包。** 網頁中已保留「實機展示」版位；你取得照片原檔後，可將它命名為 `finished-device.jpg` 放入 `docs/assets/`，再把 `docs/index.html` 的實機展示圖片路徑改成 `assets/finished-device.jpg`，即可使用自己的照片。不需換 QR Code。

## 1. 加入 repository

把本資料包的 `docs/` 整個資料夾放進你的專案根目錄。假設已經 `git clone`：

```bash
cd epaper-weather-dashboard
# 把本 ZIP 解壓縮後的 docs/ 複製到此處，確認 index.html 位於 docs/index.html
git add docs/
git commit -m "docs: add family guide website and A6 QR card"
git push origin main
```

若要在現有 README 加入入口，把 `README_GITHUB_SECTION.md` 的區塊貼到適當位置再提交。

## 2. 啟用 GitHub Pages

前往專案 **Settings → Pages → Build and deployment**：

1. Source 選 **Deploy from a branch**。
2. Branch 選 **main**，Folder 選 **/docs**。
3. 按 **Save**，等待 GitHub Pages 完成部署。
4. 開啟網站，檢查照片、字體、小卡以及 QR Code。

- 手機版說明書：<https://crazylittlej.github.io/epaper-weather-dashboard/>
- A6 小卡：<https://crazylittlej.github.io/epaper-weather-dashboard/print-a6.html>

> 在啟用 GitHub Pages 之前，上述 Pages 網址 **不保證可存取**。請先部署並使用手機實際掃碼確認，才列印貼紙。

## 3. 列印 A6 小卡

1. 開啟上述 `print-a6.html` 網址，按「列印這張小卡」。
2. 紙張尺寸選 **A6（105 × 148 mm）**，方向直式、縮放 **100%**、邊界設「無」。
3. 開啟「列印背景圖形」，以保留原本配色。
4. 若印表機不支援 A6，可先用「另存 PDF」，再由列印軟體以實際尺寸印出。
5. 手機掃描印好的 QR Code，確認開的是**公開說明書**而非 Wi-Fi 配對頁。

## 4. 維護與客製化

- 改首頁文字：`docs/index.html`
- 改配色／版面：`docs/assets/style.css`
- 換 Wi-Fi 設定示意照片：`docs/assets/wifi-setup-demo.jpg`
- 改紙本小卡：`docs/print-a6.html`
- 修改家人版 Markdown：`docs/README.md`

同一個 Pages 網址維持不變時，後續修改說明書無須換掉實體 QR Code。

若你以後**更名 GitHub 使用者、Repository、或使用自己的網域**，請同步修改所有 Pages 連結，並**重新產生 QR Code**，否則舊卡片可能失效。

## 5. 注意事項（對家人很重要）

- `https://crazylittlej.github.io/.../` 是**公開說明書**：在任何有網路的地方都能閱讀。
- `http://10.42.0.1/` 是**設定熱點網址**：僅手機連到相框建立的熱點時能開啟。
- `http://epaper.local` 是**裝置日常設定網址**：通常僅同一個家中區域網路能開啟。
- 示意照片的 QR Code / PIN 是**舊照片範例**，請以實際裝置螢幕為準。
- 原專案說明設定熱點預設不加密，Wi-Fi 密碼可能在配對期間被附近監聽；建議選擇可信任的環境，或先驗證 Pi 能否使用 WPA2 熱點後再啟用該選項。

## 6. 網頁設計特色

- 響應式（手機優先）版面，原生 HTML + CSS，不使用第三方 CDN。
- FAQ 可展開收合，方便家人排除問題。
- 頁面標註清楚：**家人手冊 QR** vs **裝置配對 QR**。
- 印表機友善 A6 `@page` 設定，QR 黑字白底提高掃描辨識率。
- GitHub Pages 僅讀取靜態檔案，**不會嘗試遠端操作你的 Raspberry Pi**。
