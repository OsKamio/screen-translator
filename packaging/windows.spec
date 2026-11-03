# Windows x64: GUI and a minimal isolated PrintWindow helper share one runtime.
from pathlib import Path
import os
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

root = Path(SPECPATH).parent
datas = [(str(root / 'assets'), 'assets'),
         (str(root / 'THIRD_PARTY_NOTICES.md'), '.'),
         (str(root / 'packaging' / 'generated' / 'licenses'), 'licenses')]
datas += collect_data_files('rapidocr_onnxruntime')
a = Analysis([str(root / 'main.py')], pathex=[str(root)], datas=datas,
             binaries=collect_dynamic_libs('onnxruntime'),
             hiddenimports=['PySide6.QtSvg'],
             excludes=['tkinter', 'matplotlib', 'IPython', 'pytest', 'PyQt5', 'PyQt6'])
# Qt uses the Windows ICU API. A third-party ICU with version-suffixed exports
# is not ABI compatible; keep these operating-system libraries out of the app.
a.binaries = [item for item in a.binaries if Path(item[0]).name.lower() not in
              {'icuuc.dll', 'icuin.dll', 'icudt.dll'}]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ScreenTranslator',
          console=bool(os.environ.get('SCREEN_TRANSLATOR_DEBUG_CONSOLE')),
          icon=str(root / 'assets' / 'screen-translator.ico'),
          version=str(root / 'packaging' / 'version_info.txt'))
w = Analysis([str(root / 'core' / 'window_capture_worker.py')], pathex=[str(root)])
worker = EXE(PYZ(w.pure), w.scripts, [], exclude_binaries=True,
             name='ScreenTranslatorCapture', console=True,
             version=str(root / 'packaging' / 'version_info.txt'))
bundle = COLLECT(exe, worker, a.binaries, a.datas, w.binaries, w.datas,
                 strip=False, upx=False, name='ScreenTranslator')
