# 0.2.0

公開下載：[ScreenTranslator 0.2.0](https://github.com/OsKamio/screen-translator/releases/tag/v0.2.0)。

提供框選翻譯、即時字幕、本地 OCR、多種翻譯服務、優先順序與失敗回退，以及可錄製的譯文視窗。

## 下載內容

- `ScreenTranslator-0.2.0-Setup-x64.exe`：Windows 10 1809+ / 11 x64 安裝包，包含執行環境與 OCR 模型。
- `ScreenTranslator-0.2.0-Portable-x64.zip`：完整解壓後執行 ScreenTranslator.exe。
- `SHA256SUMS.txt`：上述檔案的 SHA-256 校驗值。

安裝包尚未進行程式碼簽章。更新前先結束程式；安裝、更新與解除安裝均不刪除 APPDATA 中的使用者設定。

## 建置與驗證

建置方式見 DEVELOPMENT.md。驗證包含原始碼桌面回歸、凍結程式 OCR／視窗／隔離擷取自檢，以及隔離目錄安裝、升級覆蓋與解除安裝。
使用目前 Windows 本機測試，不宣稱已覆蓋所有乾淨 Windows、硬體、混合 DPI、多螢幕或網路情境。

## 維護發佈

後續版本需重新執行功能回歸、安裝流程與密鑰排除檢查，再產生對應校驗檔。第三方元件聲明見 THIRD_PARTY_NOTICES.md；本專案尚未指定獨立專案授權。
