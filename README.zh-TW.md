> &nbsp;
> ### <div style="text-align: right"> <font color="#02c59b">E-Paper Photo Frame</font> </div>
> ### <div style="text-align: right"> <font color="#ffcc00">Spectra 6 (E6) Full-Color e-Paper Weather Dashboard on Raspberry Pi 3</font></div>
>
> <div style="text-align: right"> Version: 1.2.0 </div>
> <div style="text-align: right"> Author: J </div>
> <div style="text-align: right"> Date: 2026/10/09 </div>

File History :
|         Type          |                         Description                          | Name |    Date    |
| :-------------------: | :----------------------------------------------------------: | :--: | :--------: |
| v1.0.0 first release  | 7.3" E6 (epd7in3e) photo frame + weather dashboard + hourly update | J | 2026/09/21 |
| v1.1.0 second release | 移除右上角天氣圖示；新增 `--lat` / `--lon` / `--loc` 參數與防呆     | J | 2026/09/29 |
| v1.2.0 third release  | 新增 Wi-Fi 設定模式（熱點 + QR Code + captive portal）與設定網頁；地點改存於 `config.json` | J | 2026/10/09 |

<div style="page-break-after: always;"></div>

# Table of contents
- [Table of contents](#table-of-contents)
- [Test Environment](#test-environment)
- [0. 專案簡介 Overview](#0-專案簡介-overview)
- [1. 硬體 Hardware](#1-硬體-hardware)
  - [1.1. 面板規格 Panel specification](#11-面板規格-panel-specification)
  - [1.2. 接線 Wiring](#12-接線-wiring)
- [2. 系統設定 Raspberry Pi setup](#2-系統設定-raspberry-pi-setup)
- [3. 安裝本專案 Install this project](#3-安裝本專案-install-this-project)
- [4. 設定 Configuration](#4-設定-configuration)
- [5. 使用方式 Usage](#5-使用方式-usage)
- [6. 顏色校正 Color calibration](#6-顏色校正-color-calibration)
- [7. 開機與每小時自動更新 Auto update with systemd](#7-開機與每小時自動更新-auto-update-with-systemd)
- [8. Wi-Fi 設定與設定網頁 Wi-Fi setup & settings page](#8-wi-fi-設定與設定網頁-wi-fi-setup--settings-page)
- [9. 運作原理 How it works](#9-運作原理-how-it-works)
- [10. 成果 Result](#10-成果-result)
- [11. 注意事項 Precautions](#11-注意事項-precautions)
- [12. 疑難排解 Troubleshooting](#12-疑難排解-troubleshooting)
- [13. 更換面板 Porting to another panel](#13-更換面板-porting-to-another-panel)
- [14. 參考資料 References](#14-參考資料-references)

# Test Environment

| Item        | Version / Model                                   | Comments                                   |
| ----------- | ------------------------------------------------- | ------------------------------------------ |
| Board       | Raspberry Pi 3 Model B V1.2                       | 3B / 3B+ 同樣適用                           |
| OS          | Raspberry Pi OS                                   | Python 3.13                                |
| e-Paper     | Waveshare 7.3inch e-Paper HAT (E)                 | E Ink Spectra 6 (E6), 800 × 480            |
| Driver      | waveshare/e-Paper `epd7in3e`                      | `RaspberryPi_JetsonNano/python/lib`        |
| Python libs | python3-pil, python3-numpy, spidev, gpiozero, python3-flask, python3-qrcode | 皆由 apt 安裝                               |
| Font        | fonts-noto-cjk                                    | 中文字型                                    |
| Weather API | [Open-Meteo](https://open-meteo.com/)             | 免 API key                                 |

# 0. 專案簡介 Overview

把 Waveshare 7.3 吋 Spectra 6 六色電子紙接上 Raspberry Pi 3，做成一個「照片 + 天氣」的電子相框：

- 背景是自己的照片，每天自動換一張（或指定某一張）
- 照片上疊加目前溫度、天氣文字、體感、濕度、風速、降雨機率與未來四天預報
- 可用 `--lat` / `--lon` / `--loc` 臨時查詢其他地點，不影響排程使用的預設值
- 開機連上網路後更新一次，之後每小時整點更新
- 沒網路就不刷新；但超過 20 小時沒刷新會用快取資料強制刷一次（面板規格要求 24 小時內至少刷一次）
- 畫面內容沒變（只差時間戳）就跳過刷新，減少閃爍與面板耗損
- 連不上網路時面板會顯示 QR Code，用手機就能設定 Wi-Fi 與地點；之後可以在設定網頁更換地點、上傳照片，不需要 SSH（見[第 8 節](#8-wi-fi-設定與設定網頁-wi-fi-setup--settings-page)）

主要腳本：

| Script            | 用途                                                             |
| ----------------- | ---------------------------------------------------------------- |
| `epaper_photo.py` | 影像處理 pipeline（色域壓縮 + dither）、面板設定、單張照片顯示、顏色校正 |
| `dashboard.py`    | 天氣看板主程式：抓天氣、疊加文字圖示、刷新面板                         |
| `recover.py`      | 面板診斷（全黑測試）與殘影救援（黑白 / 六色交替全刷）                   |
| `portal.py`       | Wi-Fi 設定模式（熱點、面板 QR Code、captive portal）與設定網頁           |
| `wifi.py`         | `nmcli` 包裝：掃描、開關熱點、連線                                     |
| `config.py`       | `config.json`（地點、時區）讀寫與驗證，`dashboard.py` 與 `portal.py` 共用 |

# 1. 硬體 Hardware

### 1.1. 面板規格 Panel specification

| Item                 | Spec                                   |
| -------------------- | -------------------------------------- |
| Resolution           | 800 × 480                              |
| Display area         | 160.0 mm × 96.0 mm                     |
| Dot pitch            | 0.2 mm（約 127 ppi）                    |
| Colors               | E6：黑、白、黃、紅、藍、綠                |
| Full refresh time    | 約 25 s（刷新過程會閃爍，屬正常現象）       |
| Interface            | SPI (mode 0)                           |
| Operating voltage    | 3.3 V / 5 V                            |
| Operating temp.      | 0 ~ 50 ℃                               |

### 1.2. 接線 Wiring

驅動板可以直接插在 Pi 的 40PIN 排針上，或用附的 8PIN 線連接。用 8PIN 線時對照下表：

| e-Paper | BCM   | Board pin |
| :-----: | :---: | :-------: |
| VCC     | 3.3V  | 3.3V      |
| GND     | GND   | GND       |
| DIN     | MOSI  | 19        |
| CLK     | SCLK  | 23        |
| CS      | CE0   | 24        |
| DC      | 25    | 22        |
| RST     | 17    | 11        |
| BUSY    | 24    | 18        |

> Raspberry Pi pinout（來源：Waveshare Wiki）
>
> ![pinout](img/pinout.png)

> 實際接線：8PIN 線連接 7.3inch e-Paper HAT (E) 與 Raspberry Pi 3 Model B
>
> ![wiring](img/wiring.jpg)

接線要點：

- 驅動板上的 **SPI Select 開關撥到 `0`（4-line SPI）**
- 8PIN 延長線不要超過 20 cm，太長可能造成資料遺失、畫面偏移
- 面板的 FPC 排線很脆弱：**只能沿螢幕水平方向彎**，不要垂直折、不要往螢幕正面折、不要反覆彎。FPC 連接器是 0.5 mm pitch 後掀式，插拔前先把壓條掀起，完全斷電再操作

# 2. 系統設定 Raspberry Pi setup

**Step 1. 開啟 SPI**

```shell
$ sudo raspi-config
# Interface Options -> SPI -> Yes
$ sudo reboot
$ ls /dev/spi*        # 應看到 /dev/spidev0.0 /dev/spidev0.1
```

**Step 2. 安裝套件**

```shell
$ sudo apt update
$ sudo apt install python3-pip python3-pil python3-numpy python3-spidev python3-gpiozero fonts-noto-cjk \
                 python3-flask python3-qrcode avahi-daemon
```

**Step 3. 使用者群組（不需要 sudo 執行）**

一般使用者只要在 `spi`、`gpio` 群組就能驅動面板。本專案的腳本**一律不要用 sudo 執行**（見 [12. 疑難排解](#12-疑難排解-troubleshooting)）。

```shell
$ id                                  # 確認有 spi、gpio
$ sudo usermod -aG spi,gpio $USER     # 若沒有，加入後重新登入
```

**Step 4. 下載 Waveshare 官方驅動並先跑官方範例**

先確認硬體與接線沒問題，再跑本專案：

```shell
$ mkdir -p ~/workspace && cd ~/workspace
$ git clone https://github.com/waveshare/e-Paper.git
$ cd e-Paper/RaspberryPi_JetsonNano/python/examples
$ python3 epd_7in3e_test.py
```

官方範例能正常顯示六色圖形與範例圖片，才進行下一步。

# 3. 安裝本專案 Install this project

目錄結構：

```
~/epaper/
├── epaper_photo.py
├── dashboard.py
├── recover.py
├── portal.py
├── wifi.py
├── config.py
├── config.json              # 地點與時區，由設定網頁寫入（第一次設定後才會出現）
├── templates/               # 設定網頁模板
├── help/                    # 使用說明網頁（build_help.py 由 README 產生）
├── lib -> ~/workspace/e-Paper/RaspberryPi_JetsonNano/python/lib   (symlink)
├── bg/                      # 背景照片，放 jpg / png / bmp
├── systemd/
│   ├── epaper-dash.service
│   ├── epaper-dash.timer
│   └── epaper-portal.service
├── polkit/
│   └── 50-epaper-networkmanager.rules
├── networkmanager/
│   └── captive-portal.conf
└── img/                     # README 用圖
```

```shell
$ mkdir -p ~/epaper/bg && cd ~/epaper
# 放入所有 .py、help/、img/、templates/、systemd/、polkit/、networkmanager/

# 把 Waveshare 的 python lib 接進來（注意是 python/lib 這層，不是 waveshare_epd）
$ ln -s ~/workspace/e-Paper/RaspberryPi_JetsonNano/python/lib ~/epaper/lib
$ ls ~/epaper/lib/waveshare_epd/epd7in3e.py      # 能列出檔案才代表連結正確

# 放幾張背景照片
$ cp ~/Pictures/*.jpg ~/epaper/bg/
```

> 如果 `~/epaper/lib` 已經是一個存在的目錄，`ln -s` 會在裡面建出 `lib/lib`，import 仍然失敗。先 `rm` 掉再建。

# 4. 設定 Configuration

**`epaper_photo.py`：面板與影像處理**

| 參數             | 預設                | 說明                                                   |
| ---------------- | ------------------- | ------------------------------------------------------ |
| `DRIVER`         | `"epd7in3e"`        | Waveshare 驅動模組名稱                                  |
| `W, H`           | `800, 480`          | 面板解析度                                              |
| `PALETTE_SRGB`   | 估計值               | 面板實測六原色，**務必校正**（見第 6 節）                   |
| `EXPOSURE`       | `1.25`              | >1 提亮中間調；照片偏暗就往上調                             |
| `SATURATION`     | `1.25`              | 飽和度預補償（dither 會讓顏色變淡）                         |
| `LOCAL_AMOUNT`   | `0.55`              | 局部對比（unsharp），0 關閉                                |

**`dashboard.py`：看板內容與刷新策略**

| 參數              | 預設                    | 說明                                             |
| ----------------- | ----------------------- | ------------------------------------------------ |
| `DEFAULT_LAT/LON` | 讀自 `config.json`       | 預設天氣查詢座標，可用 `--lat` / `--lon` 覆寫           |
| `DEFAULT_PLACE`   | 讀自 `config.json`       | 預設顯示地名，可用 `--loc` 覆寫                        |
| `TZ`              | 讀自 `config.json`       | 時區                                              |
| `SCRIM`           | `0.0`                   | 背景壓暗程度。0 = 照片原樣；文字靠黑色描邊維持可讀性       |
| `SCRIM_BANDS`     | `False`                 | 額外壓暗上下兩條 UI 區域                             |
| `MIN_INTERVAL`    | `180`                   | 最短刷新間隔（秒），面板規格要求                        |
| `MAX_AGE`         | `20 * 3600`             | 超過此時間沒刷新就強制刷新（面板規格要求 < 24 h）         |

**`config.json`：地點與時區**

由設定網頁寫入，也可以手動編輯。檔案不存在或某個值不合法時，該值改用 `config.py` 的 `DEFAULTS`（新竹 `24.8138, 120.9675`、`Asia/Taipei`），看板照常運作。

```json
{
  "lat": 24.8138,
  "lon": 120.9675,
  "place": "新竹",
  "tz": "Asia/Taipei"
}
```

# 5. 使用方式 Usage

> 所有指令都以一般使用者執行，**不加 sudo**。

**天氣看板 `dashboard.py`**

```shell
$ cd ~/epaper
$ python3 dashboard.py                              # 正常更新（受刷新保護規則約束）
$ python3 dashboard.py --force                      # 略過所有保護規則，立即刷新
$ python3 dashboard.py --bg bg/a.jpg --force        # 指定背景照片（不走每日輪替）
$ python3 dashboard.py --preview /tmp/p.png         # 只輸出 PNG，不碰面板
$ python3 dashboard.py --lat=25.033 --lon=121.5654 --loc=台北 --force
$ python3 dashboard.py --help                       # 完整參數說明
```

**地點參數 `--lat` / `--lon` / `--loc`**

不指定時使用 `config.json` 的地點（由設定網頁寫入；檔案不存在時為新竹）。systemd service 不帶這些參數，所以**自動更新一律使用 `config.json` 的地點**，臨時用參數查別的地點不會影響排程。

防呆規則：

| 規則                                         | 說明                                              |
| -------------------------------------------- | ------------------------------------------------- |
| `--lat` 必須是 -90 ~ 90 的數字                 | 非數字或超出範圍直接報錯退出（exit code 2）           |
| `--lon` 必須是 -180 ~ 180 的數字               | 同上                                              |
| `--loc` 不可為空白、不可含控制字元、長度上限 12 字   | 避免標題列被撐爆                                     |
| 給了 `--lat` / `--lon` 就必須一起給 `--loc`      | 否則標題會顯示錯誤地名（座標換了、地名沒換）             |

座標不同時，離線快取 `weather.json` 會被判定為不同地點而不採用，避免顯示上一個地點的天氣。

> ⚠️ `--preview` 的參數是**輸出**路徑。不要寫成 `bg/` 裡的來源檔，程式會拒絕寫入 `bg/`。

**單張照片 `epaper_photo.py`（不疊加天氣）**

```shell
$ python3 epaper_photo.py bg/a.jpg
$ python3 epaper_photo.py bg/a.jpg --preview /tmp/p.png
```

這支沒有 UI 遮擋，是調 `EXPOSURE`、驗證顏色校正最乾淨的工具。

**面板診斷與救援 `recover.py`**

```shell
$ python3 recover.py --black       # 全黑一次，用來判斷條紋是殘影還是硬體損傷
$ python3 recover.py               # 黑白交替 8 輪（約 1 小時，每次間隔 185 s）
$ python3 recover.py --colours     # 先刷紅綠藍黃再黑白交替（效果較強）
```

**建議的調整流程**：先用 `--preview` 在 PNG 上把版面與亮度調好，確認滿意才上實機，避免為了試參數反覆刷新面板。

# 6. 顏色校正 Color calibration

E6 面板的實際原色比標稱色暗、飽和度低得多，而且**不同批次會有色差**。dither 若拿標稱色（純 0 / 255）計算誤差，結果會又髒又暗。每片面板都應該量一次：

```shell
$ python3 epaper_photo.py --calib
```

1. 面板會顯示六個純色色塊（黑、白、黃、紅、藍、綠）
2. 在白光（日光）下**正面**拍照，避免反光
3. 用影像軟體取每個色塊中央的 RGB 平均值
4. 填回 `epaper_photo.py` 的 `PALETTE_SRGB`（順序：black, white, yellow, red, blue, green）
5. 清掉背景快取後重跑

```shell
$ rm -f .bg_cache.npz .frame_sig
$ python3 dashboard.py --force
```

# 7. 開機與每小時自動更新 Auto update with systemd

`systemd/epaper-dash.service`（`User`、路徑請改成自己的帳號）

```ini
[Unit]
Description=e-Paper weather dashboard
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=ej
WorkingDirectory=/home/ej/epaper
ExecStart=/usr/bin/python3 /home/ej/epaper/dashboard.py
```

`systemd/epaper-dash.timer`

```ini
[Unit]
Description=Refresh e-Paper dashboard hourly and at boot

[Timer]
OnBootSec=2min
OnCalendar=*-*-* *:00:00
Persistent=true
RandomizedDelaySec=30

[Install]
WantedBy=timers.target
```

| 設定                  | 作用                                           |
| --------------------- | ---------------------------------------------- |
| `OnBootSec=2min`      | 開機、連上網路後更新一次                           |
| `OnCalendar=*:00:00`  | 每小時整點更新                                    |
| `Persistent=true`     | 錯過的排程（例如關機期間）開機後補跑                  |
| `RandomizedDelaySec`  | 避免整點瞬間同時觸發                               |

service 的 `ExecStart` 不帶地點參數，因此自動更新永遠使用 `config.json` 的地點。要改排程用的地點，用設定網頁（見[第 8 節](#8-wi-fi-設定與設定網頁-wi-fi-setup--settings-page)）或直接編輯 `config.json`，不要改 service 檔。

安裝與確認：

```shell
$ sudo cp ~/epaper/systemd/epaper-dash.* /etc/systemd/system/
$ sudo systemctl daemon-reload
$ sudo systemctl enable --now epaper-dash.timer
$ systemctl list-timers epaper-dash.timer
$ journalctl -u epaper-dash.service -n 50 --no-pager
```

每次執行時 `dashboard.py` 依序判斷：

```mermaid
flowchart TD
    A[timer 觸發] --> S{Wi-Fi 設定畫面顯示中?}
    S -- 是 --> X[跳過]
    S -- 否 --> B{距上次刷新 < 180s?}
    B -- 是 --> X[跳過]
    B -- 否 --> C{有網路?}
    C -- 否 --> D{超過 20h 沒刷新?}
    D -- 否 --> X
    D -- 是 --> E[讀快取天氣，標記「離線」]
    C -- 是 --> F[抓 Open-Meteo 天氣]
    E --> G[合成畫面]
    F --> G
    G --> H{畫面與上次相同?<br/>忽略時間戳}
    H -- 是 --> X
    H -- 否 --> I[init → display → sleep]
```

# 8. Wi-Fi 設定與設定網頁 Wi-Fi setup & settings page

讓使用者不用 SSH、不用改程式碼，就能在自己家把看板連上網路並設定地點與照片。流程和市售智慧插座類似：連不上網路時，Pi 自己開一個 Wi-Fi 熱點，面板顯示 QR Code，用手機設定。

```mermaid
flowchart TD
    A[開機] --> B{90 秒內連上已存的網路?<br/>Wi-Fi 或有線}
    B -- 是 --> N["一般模式<br/>設定網頁 主機名稱.local"]
    B -- 否 / 開機時按住重設鈕 --> S[掃描附近 Wi-Fi]
    S --> H[開熱點 ePaper-Setup-XXXX]
    H --> P[面板顯示設定畫面與兩個 QR Code]
    P --> W[手機連上熱點，自動跳出設定頁<br/>選 Wi-Fi、輸入密碼與城市]
    W --> C{連線成功?}
    C -- 是 --> G[查詢城市座標，寫入 config.json]
    G --> D[刷新天氣看板]
    D --> N
    C -- 否 --> H
```

**使用者的操作步驟**

1. 插電開機。約 2 分鐘後，面板會顯示「Wi-Fi 設定」畫面
2. 用手機相機掃描左邊的 QR Code 加入熱點（或手動加入畫面上的熱點名稱與密碼）
3. 手機通常會自動跳出設定頁；沒有的話，掃描右邊的 QR Code，或開啟 `http://10.42.0.1/`
4. 選擇家中的 Wi-Fi，輸入密碼與城市名稱，按「連線」
5. 手機切回家中的 Wi-Fi。成功的話，1–4 分鐘內面板會換成天氣看板；失敗的話熱點會重新出現，再連上一次，設定頁會顯示錯誤原因

之後在同一個網路下開啟 `http://<主機名稱>.local`（例如 `http://epaper.local`），可以：

- 搜尋城市並更換地點（使用 Open-Meteo Geocoding API，不需要自己查經緯度），可以自訂看板上顯示的名稱
- 上傳或刪除背景照片，並看到今天輪到哪一張
- 立即更新畫面
- 重新設定 Wi-Fi（換路由器或改密碼時使用）
- 閱讀使用說明 `http://<主機名稱>.local/help`：就是這份 README，可以中英文切換（預設依瀏覽器語言，`?lang=zh-TW` / `?lang=en` 可指定；`/help-zh-TW`、`/help-en` 也能用）。流程圖需要網路才能顯示，離線時會顯示原始文字

使用說明是預先轉好的 HTML（`help/help-zh-TW.html`、`help/help-en.html`），Pi 上不需要安裝 Markdown 套件。修改 README 後，在電腦上重新產生並和 README 一起 commit：

```shell
$ pip install markdown
$ python3 build_help.py
```

> 設定網頁：目前設定與地點（可搜尋城市，或手動輸入經緯度）
>
> ![wifi_location_info](img/wifi_location_info.png)

> 設定網頁：背景照片上傳與刪除
>
> ![background_update](img/background_update.png)

> 設定網頁：重新設定 Wi-Fi
>
> ![reset_wifi](img/reset_wifi.png)

> 設定頁上的城市搜尋要等連上網路後才能進行：設定模式下 Pi 和手機都沒有網路。所以 Wi-Fi 設定頁只讓使用者輸入城市名稱，連上網路後才查詢座標（取第一筆結果）。查不到時，設定網頁會提示重新搜尋。

> 目前不會套用照片的 EXIF 方向。用手機拍的直式照片，上傳後在面板上可能會轉向。

面板設定畫面的版面：左邊是加入熱點的 QR Code（`WIFI:` 格式，iOS / Android 相機都能直接加入），中間是設定頁網址的 QR Code，右邊是熱點名稱、密碼、網址和「只支援 2.4 GHz」的提示。

**安裝**

需要 Raspberry Pi OS Bookworm 以後的版本（預設使用 NetworkManager）。

```shell
$ cd ~/epaper

# 1. 允許你的帳號操作 NetworkManager（先把檔案裡的 "ej" 改成你的帳號）
$ sudo cp polkit/50-epaper-networkmanager.rules /etc/polkit-1/rules.d/

# 2. captive portal：熱點上所有 DNS 查詢都指向 Pi，手機才會自動跳出設定頁
$ sudo cp networkmanager/captive-portal.conf /etc/NetworkManager/dnsmasq-shared.d/

# 3. 主機名稱，決定設定網頁的網址（這裡是 http://epaper.local）
$ sudo raspi-config nonint do_hostname epaper

# 4. 開機自動啟動（先把 User 與路徑改成自己的帳號）
$ sudo cp systemd/epaper-portal.service /etc/systemd/system/
$ sudo systemctl daemon-reload
$ sudo systemctl enable --now epaper-portal.service
$ journalctl -u epaper-portal.service -f
```

`systemd/epaper-portal.service`

```ini
[Unit]
Description=e-Paper Wi-Fi setup portal and settings page
Wants=NetworkManager.service
After=NetworkManager.service

[Service]
User=ej
WorkingDirectory=/home/ej/epaper
ExecStart=/usr/bin/python3 /home/ej/epaper/portal.py
AmbientCapabilities=CAP_NET_BIND_SERVICE
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

`portal.py` 以一般使用者執行：polkit 規則讓它能操作 NetworkManager，`AmbientCapabilities` 讓它能綁定 80 port（captive portal 必須是 port 80 的 `http://`）。這樣它寫出的狀態檔（`.last_refresh` 等）和 `dashboard.py` 是同一個擁有者。

**測試**

```shell
$ python3 portal.py --preview /tmp/setup.png       # 只看設定畫面長相，不碰面板與網路
$ python3 portal.py --port 8080 --no-panel         # 開發設定網頁（先停掉 service）
```

想實際走一次設定流程，可以在設定網頁按「重新設定 Wi-Fi」，或在開機時按住重設鈕。⚠️ 如果你是透過 Wi-Fi SSH 進來的，連線會中斷。

**重設按鈕（選配）**

在 BCM 26（實體 pin 37）和 GND（pin 39）之間接一顆按鈕，開機時按住就會強制進入設定模式。要換腳位，改 `portal.py` 的 `BUTTON_PIN`；沒接按鈕也不會誤觸發（使用內部上拉），也可以設成 `None`。

**`portal.py` 參數**

| 參數 / 選項            | 預設   | 說明                                                         |
| --------------------- | ------ | ------------------------------------------------------------ |
| `CONNECT_WAIT`        | `90`   | 開機後等已存網路連上的秒數。完全沒存 Wi-Fi 時只等 15 秒（給有線網路） |
| `BUTTON_PIN`          | `26`   | 重設按鈕的 BCM 腳位，`None` 表示不使用                           |
| `--setup`             |        | 強制以設定模式啟動                                              |
| `--preview OUT.PNG`   |        | 只把設定畫面輸出成 PNG                                          |
| `--port`              | `80`   | 網頁的 port                                                   |
| `--no-panel`          |        | 不刷新面板（開發用）                                            |

**和面板保護規則的配合**

- 顯示設定畫面也是一次完整刷新，同樣遵守 180 秒最短間隔，刷完立刻 sleep
- 設定模式期間，`dashboard.py` 會跳過排程更新，不蓋掉設定畫面（以 `.setup_mode` 標記檔判斷）。改由 `portal.py` 在超過 20 小時沒刷新時重刷設定畫面，維持 24 小時內至少刷新一次
- `portal.py` 和 `dashboard.py` 用檔案鎖 `.panel_lock` 互斥，不會同時驅動 SPI
- 設定網頁送出多個刷新請求時會合併成一次

**Pi 3B 的限制**

- 只支援 **2.4 GHz** Wi-Fi，5 GHz 網路不會出現在清單中。雙頻路由器的兩個頻段同名時通常沒有問題
- 只有一顆無線晶片，開著熱點時無法同時掃描，所以清單是開熱點**之前**掃到的。找不到時可以手動輸入名稱（也適用於隱藏網路）
- 支援 WPA2-Personal（含 WPA2/WPA3 混合模式）和開放網路；不支援需要帳號的企業網路（WPA2-Enterprise），也不支援飯店那種要網頁登入的網路

**安全性（第一版的限制）**

- 熱點密碼每台隨機產生（存在 `.ap_psk`，權限 600），只顯示在面板上：看得到螢幕的人才能連
- 設定網頁**沒有登入機制**：同一個區網內的任何人都能修改地點、上傳或刪除照片。只有跨站 POST 會被擋下（檢查 `Origin` header）
- Wi-Fi 密碼透過 `nmcli` 的命令列參數傳遞，連線的那幾秒內，本機其他使用者可以從行程列表看到
- 網頁使用 Flask 內建的伺服器，適合單機、少量使用

# 9. 運作原理 How it works

```mermaid
flowchart LR
    P[背景照片] --> C[fit / crop<br/>800x480]
    C --> L[轉 linear light]
    L --> T[色域 / 動態範圍壓縮<br/>EXPOSURE, SATURATION]
    T --> D[Floyd-Steinberg dither<br/>以實測 PALETTE 計算誤差]
    D --> K[(.bg_cache.npz<br/>每張圖只算一次)]
    K --> M[疊加 UI<br/>純色索引，不 dither]
    W[Open-Meteo 天氣] --> M
    M --> N[轉標稱色 RGB]
    N --> G[Waveshare getbuffer]
    G --> E[e-Paper]
```

幾個關鍵設計：

- **照片 dither、UI 不 dither。** 文字與圖示在 dither **之後**才以純色索引寫入，所以中文小字不會被誤差擴散打成雜點。文字一律白字加黑色描邊，放在任何亮度的照片上都讀得到。
- **用實測色算、用標稱色送。** dither 的誤差用面板實測的 `PALETTE_SRGB` 計算，輸出時再換成標稱色（純 0 / 255）交給 Waveshare 的 `getbuffer()`。因為影像裡只剩那六個精確顏色，`getbuffer()` 的最近色比對是一對一無損的，旋轉與 4bpp 打包、各尺寸面板不同的色碼都交給官方驅動處理。
- **在 linear light 做 dither。** 直接在 sRGB 值域做誤差擴散，中間調會偏暗、漸層會結塊。
- **背景快取。** 照片一天才換一次，dither 結果存成 `.bg_cache.npz`，每小時的更新只重畫文字層。

# 10. 成果 Result

> 實機效果：照片背景 + 天氣資訊
>
> ![result_cat](img/result_photo_cat.jpg)

> 實機效果：夜空照片背景
>
> ![result_milkyway](img/result_photo_milkyway.jpg)

> 刷新過程（4 倍速）。E6 全刷約 25 秒，過程中的閃爍是清除殘影的正常現象
>
> ![refresh_demo](img/refresh_demo.gif)

# 11. 注意事項 Precautions

以下多數來自 Waveshare 官方說明，其中幾條是本專案實際踩過、讓一片 4 吋面板報廢的教訓：

1. **刷新後一定要進 sleep 或斷電。** 面板長時間維持在高壓狀態會造成無法修復的損傷。本專案每次刷新後都會呼叫 `epd.sleep()`。
2. **刷新間隔至少 180 秒。** 除錯時不要用 `--force` 連續刷新；先用 `--preview` 在 PNG 上驗證。
3. **至少每 24 小時刷新一次**，否則長時間停留同一畫面會產生難以修復的殘影。
4. **長期不用前先刷白再收。** 儲存條件：30 ℃ 以下、55 %RH 以下、最長 6 個月，面朝上存放。台灣濕度高，超過這個期限的面板有報廢風險。
5. **FPC 排線只能沿水平方向彎**，不要垂直折、不要往正面折、不要反覆彎。
6. 低溫下刷新可能偏色，需在 25 ℃ 環境放置 6 小時後再刷新。
7. 僅建議室內使用，避免陽光直射。
8. 多色面板不同批次有色差屬正常現象，所以每片都要做[顏色校正](#6-顏色校正-color-calibration)。

# 12. 疑難排解 Troubleshooting

| 症狀                                                         | 原因                                                                  | 解法                                                                      |
| ------------------------------------------------------------ | --------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| `ModuleNotFoundError: No module named 'waveshare_epd'`        | `lib` 符號連結不存在或已斷；或用了 sudo（root 看不到使用者的 pip --user 安裝） | 重建 `lib` 符號連結（見第 3 節），不要用 sudo                                  |
| systemd 失敗但手動執行正常                                     | service 的 `User`、路徑不對；或狀態檔擁有者不同                             | `sudo chown -R $USER:$USER ~/epaper`，檢查 `journalctl -u epaper-dash.service` |
| log 顯示 `background: None`                                  | `bg/` 不在腳本旁邊，或副檔名不符（例如 `a.bmp.txt`）                       | `ls -la ~/epaper/bg/`                                                     |
| 背景沒有換圖                                                  | 只有少量照片時每日輪替不明顯                                              | 多放幾張，或用 `--bg` 指定                                                   |
| 照片偏暗                                                      | `SCRIM` 開著、`EXPOSURE` 太低、`PALETTE_SRGB` 沒校正                      | `SCRIM=0`、調高 `EXPOSURE`、做顏色校正，之後 `rm .bg_cache.npz`               |
| 改了參數畫面沒變                                               | 背景快取仍是舊的（快取 key 只含照片路徑與 SCRIM 設定）                       | `rm -f .bg_cache.npz .frame_sig`                                          |
| 畫面旋轉 90° 並有規則條紋                                       | 繞過 `getbuffer()` 自行打包，與面板掃描方向不符                             | 使用本專案現行版本（透過 `getbuffer()` 送資料）                                  |
| 全白 / 全黑畫面上有固定位置的條紋                                 | 先跑 `recover.py --black`：全黑均勻 → 殘影；同位置有線 → 驅動線或膜層實體損傷  | 殘影跑 `recover.py --colours`；實體損傷無法修復，更換面板（驅動板可沿用）          |
| 一直卡在 `e-Paper busy`                                        | SPI 未啟用或接線錯誤                                                     | 檢查 `ls /dev/spi*`、接線、SPI Select 開關                                   |
| 手機連上熱點後沒有自動跳出設定頁                                   | 沒安裝 `captive-portal.conf`，或手機系統沒偵測到                            | 掃描面板右邊的 QR Code，或手動開啟 `http://10.42.0.1/`                        |
| 設定頁清單裡找不到家裡的 Wi-Fi                                    | 是 5 GHz 網路（Pi 3B 只支援 2.4 GHz），或開熱點前沒掃到                     | 開啟路由器的 2.4 GHz 頻段；或展開「手動輸入名稱」                                |
| `journalctl -u epaper-portal` 出現 `Not authorized` / `Insufficient privileges` | polkit 規則沒裝，或規則裡的帳號不是 service 的 `User`              | 檢查 `/etc/polkit-1/rules.d/50-epaper-networkmanager.rules`                   |
| 手動執行 `portal.py` 出現 `Permission denied` 綁定 80 port           | 一般使用者不能綁 1024 以下的 port                                          | 用 service 啟動（有 `CAP_NET_BIND_SERVICE`），開發時改用 `--port 8080`           |
| 熱點開不起來、log 出現 `nmcli` 錯誤                                 | 系統不是用 NetworkManager（舊版 Raspberry Pi OS 用 dhcpcd）                 | `sudo raspi-config` → Advanced Options → Network Config → NetworkManager      |

# 13. 更換面板 Porting to another panel

面板相關設定只集中在 `epaper_photo.py` 開頭兩行，`dashboard.py` 與 `recover.py` 都從這裡讀取；版面的字級與座標依 `H / 400` 等比縮放。

```python
DRIVER = "epd7in3e"       # 4in0e -> "epd4in0e" | 7.3in E6 -> "epd7in3e"
W, H = 800, 480           # 4in0e -> 600, 400    | 7.3in E6 -> 800, 480
```

換面板後：

1. 確認 `lib/waveshare_epd/` 內有對應的驅動檔
2. 改上面兩行
3. 用 `--preview` 檢查版面
4. 重做[顏色校正](#6-顏色校正-color-calibration)
5. `rm -f .bg_cache.npz .frame_sig .last_refresh`

各面板的色碼不同不需要處理，由 `getbuffer()` 負責。

# 14. 參考資料 References

- [本專案 GitHub repo](https://github.com/crazylittleJ/epaper-weather-dashboard)
- [Waveshare 7.3inch e-Paper HAT (E) Manual](https://www.waveshare.com/wiki/7.3inch_e-Paper_HAT_(E)_Manual)
- [Waveshare 7.3inch e-Paper HAT (E) product page](https://www.waveshare.com/product/raspberry-pi/displays/e-paper/7.3inch-e-paper-hat-e.htm)
- [waveshare/e-Paper (GitHub)](https://github.com/waveshare/e-Paper)
- [E Ink Spectra 6 7.3" (EL073TF1U5)](https://www.eink.com/product/detail/EL073TF1U5)
- [Open-Meteo Weather API](https://open-meteo.com/en/docs)
