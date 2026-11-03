ScreenTranslator third-party runtime notices

The Windows bundle includes CPython, PySide6/Qt, RapidOCR/ONNX models,
ONNX Runtime, NumPy, OpenCV, Requests, MSS and their dependencies.
dependency-inventory.json records installed distribution versions. Original
license and notice files are retained in the corresponding package folders.

Qt/PySide6/shiboken are dynamically linked under the LGPL v3 option.
The LGPL v3 and referenced GPL v3 texts are included. Recipients may replace
these shared libraries with compatible modified builds; reverse engineering
for debugging such modifications is permitted by the LGPL. The application
does not impose a restriction on those LGPL rights.
Corresponding unmodified sources for the bundled Qt/PySide version:
https://github.com/qt/qtbase/tree/v6.11.2
https://github.com/qt/qtsvg/tree/v6.11.2
https://github.com/qt/pyside-setup/tree/v6.11.2
https://download.qt.io/archive/qt/6.11/6.11.2/submodules/

RapidOCR uses PaddleOCR-derived models. Apache 2.0 texts are included:
https://github.com/RapidAI/RapidOCR
https://github.com/PaddlePaddle/PaddleOCR

Upstream license text provenance:
Qt: https://github.com/qt/qtbase/tree/v6.11.2/LICENSES
RapidOCR: https://github.com/RapidAI/RapidOCR/blob/main/LICENSE
PaddleOCR: https://github.com/PaddlePaddle/PaddleOCR/blob/main/LICENSE

These notices cover third-party components and do not assign a project
license to ScreenTranslator itself. FFmpeg and build compilers are not
included in the Windows application.
