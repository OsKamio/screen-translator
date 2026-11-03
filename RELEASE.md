# 0.2.0 私有審閱版

此版本供維護者確認，倉庫保持私有，GitHub Release 為草稿。沒有開放公開發佈。

## 下載內容

- `ScreenTranslator-0.2.0-Setup-x64.exe`：Windows 10 1809+ / 11 x64 安裝包，包含執行環境與 OCR 模型。
- `ScreenTranslator-0.2.0-Portable-x64.zip`：完整解壓後執行 ScreenTranslator.exe。
- `SHA256SUMS.txt`：上述檔案的 SHA-256 校驗值。

安裝包尚未進行程式碼簽章。更新前先結束程式；安裝、更新與解除安裝均不刪除 APPDATA 中的使用者設定。

## 建置與驗證

建置方式見 DEVELOPMENT.md。驗證包含原始碼桌面回歸、凍結程式 OCR／視窗／隔離擷取自檢，以及隔離目錄安裝、升級覆蓋與解除安裝。
使用目前 Windows 本機測試，不宣稱已覆蓋所有乾淨 Windows、硬體、混合 DPI、多螢幕或網路情境。

## 發佈前

確認功能與文件後，再由維護者決定公開時間。公開前需確認專案授權、依賴聲明、程式碼簽章及更完整的 Windows 相容性驗證。
