# 开发说明

项目使用 Python / PySide6，运行代码位于 `main.py`、`core/`、`ui/`。

| 目录 | 内容 |
| --- | --- |
| core | 配置、区域抓屏、隔离的下层窗口捕获、本地 OCR、翻译接口链和实时流水线 |
| ui | 悬浮入口、框选遮罩、实时与结果窗口、设置与窗口交互 |
| scripts | 精选回归、自检、性能采样、公开素材生成与发布审计 |
| docs/media | 仅包含示例内容的公开图片、GIF 和 MP4 |

## 本机运行

建议创建虚拟环境并安装 requirements.txt。精确的本机验证版本另见 requirements-tested-windows.txt。
默认配置的凭据为空；不要把自己的配置复制进 Git 仓库。

```powershell
python scripts/run_checks.py
python scripts/run_checks.py --desktop --report checks.json
```

基础组使用离屏 Qt；桌面组需要交互式 Windows 桌面，包括真实抓屏、真实 OCR、localhost 翻译和窗口行为。
测试以模拟翻译服务或预设内容运行，不消耗维护者的外部 API 额度。

## 实时窗口约束

录屏可见模式不周期性清空译文。优先使用有超时保护的隔离下层窗口捕获；失败时分离原文取景与译文。
停止、暂停、换区与配置变化使用代次保护，丢弃迟到结果。正文排版和动画不改变取景几何。
外框、动效和材质缓存均有独立验证；不要通过重新创建 HWND 来刷新界面。

## 展示素材

生成方法与内容边界见 docs/MEDIA.md。展示窗口只使用新的 Config 默认对象，不读取用户运行配置。
重新生成素材前，检查示例文字及所有界面字段；不要录制私人桌面或真实 API 设置页。

## 发布审计

```powershell
python scripts/audit_publication.py --root .
# 可选：对照本机配置值，只在内存中比对，不会把配置写入报告
python scripts/audit_publication.py --root . --private-config "$env:APPDATA\ScreenTranslator\config.json" --report audit-local.json
```

审计检查 Git 暂存区及已有历史中的文件、密钥形态、禁止路径和可选私人配置的原文/转义/编码形式。
报告仅含计数、文件名与命中类型，不含匹配值。它不替代对截图、视频和自定义接口模板的人工检查。

## Windows 安裝包建置

使用 Windows x64 Python，安裝應用依賴與 `requirements-build.txt`，另備 Inno Setup 6.7 以上版本。

```powershell
python -m pip install -r requirements.txt -r requirements-build.txt
python scripts/build_windows.py --iscc "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
.\dist\ScreenTranslator\ScreenTranslator.exe --self-test "$PWD\build\frozen-check.json"
```

預設輸出 `dist/`：安裝 EXE、免安裝 ZIP 與 SHA256SUMS.txt。建置腳本只收集程式資源和依賴；使用者配置不在收集清單內。授權文字及依賴版本清單放在安裝目錄的 `_internal/licenses/`。

`ScreenTranslatorCapture.exe` 是無介面的隔離擷取程序，由主程式以隱藏模式呼叫。不要刪除它或單獨搬移主 EXE。
`--self-test` 使用獨立空白配置和本地樣本，不載入使用者配置，也不呼叫外部翻譯服務。

安裝程式採目前使用者模式，不需要管理員權限。可用 `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR="完整測試路徑"` 做隔離安裝驗證；先確認目錄是專用測試目錄，避免覆蓋正在使用的版本。
