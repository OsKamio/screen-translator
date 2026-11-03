# 第三方来源

## 界面参考

液态玻璃的建模思路参考用户提供的 Aceternity UI Liquid Glass 与 Liquid Glass Hero 组件文本。
本项目使用 Qt / NumPy / OpenCV 重新实现圆角 SDF、Snell 折射和 RGB 位移；没有把原 React 组件、在线示例图片或示例营销文案加入仓库。
适配差异见 LIQUID_GLASS.md。设计参考不能替代对应来源的许可说明。

界面动效参考 GSAP 的时序、插值、中断覆盖与性能原则，使用 Qt 原生实现，没有分发 GSAP JavaScript 运行时。
图标由项目的 Qt 绘制脚本生成。界面使用系统字体，不附带 Windows 字体文件。

## 运行依赖

源码版本通过 Python 包安装依赖；Windows 安装版随包提供执行环境、动态库和 OCR 模型。原始授权文字、依赖版本及来源位于安装目录 `_internal/licenses/`，源码仓库不含虚拟环境。各项目来源：

- [PySide / Qt for Python](https://doc.qt.io/qtforpython-6/)
- [RapidOCR](https://github.com/RapidAI/RapidOCR)
- [ONNX Runtime](https://github.com/microsoft/onnxruntime)
- [NumPy](https://github.com/numpy/numpy)
- [OpenCV](https://github.com/opencv/opencv) / [opencv-python](https://github.com/opencv/opencv-python)
- [Requests](https://github.com/psf/requests)
- [python-mss](https://github.com/BoboTiG/python-mss)

FFmpeg 仅用于可选的演示素材导出，不包含 FFmpeg 可执行文件。


安装程序使用 Inno Setup；中文安装文字来自官方源码仓库的 `Files/Languages/Unofficial`，保留文件中的作者声明。建置工具 PyInstaller 不随应用目录分发，其 bootloader 适用官方授权及打包应用例外。来源：

- https://github.com/jrsoftware/issrc/tree/is-6_7_4
- https://pyinstaller.org/en/stable/license.html

Qt/PySide6 动态库按 LGPL v3 选项分发，保留替换兼容动态库与调试修改的权利；授权全文和对应源码位置见 `packaging/licenses/README.txt`。本说明不为 ScreenTranslator 本身指定开源许可证。
