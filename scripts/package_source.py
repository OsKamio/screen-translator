"""按允许列表制作 GitHub 源码候选包，排除配置、密钥探针、截图、缓存和历史备份。"""
import argparse, hashlib, json, zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
TOP=['main.py','README.md','DEVELOPMENT.md','.gitignore','requirements.txt',
     'requirements-tested-windows.txt','run.bat','RELEASE.md','SECURITY.md','CHANGELOG.md','LIQUID_GLASS.md',
     '.gitattributes','THIRD_PARTY_NOTICES.md']
SCRIPTS=['check_names.py','test_live_quality.py','smoke_config.py','smoke_custom_backend.py',
 'smoke_settings.py','smoke_menu.py','smoke_place.py','smoke_ui.py','smoke_live_engine.py',
 'smoke_live_window.py','smoke_theme.py','smoke_motion.py','check_live_after_settings.py',
 'check_live_interaction.py','check_hint_layout.py','check_live_no_flicker.py',
 'smoke_window_capture.py','check_live_local_e2e.py','stress_live.py','manual_qa.py','check_video_design.py',
 'run_checks.py','package_source.py','benchmark_ocr.py','make_ui_icon.py',
 'check_switch_performance.py','benchmark_switch.py','check_glass_theme.py','check_native_frame.py',
 'audit_publication.py','create_public_media.py']

def source_files():
    paths=[ROOT/name for name in TOP]+[ROOT/'scripts'/name for name in SCRIPTS]
    paths += list((ROOT/'core').glob('*.py'))+list((ROOT/'ui').glob('*.py'))
    paths += [p for p in (ROOT/'assets').iterdir() if p.suffix.lower() == '.svg'
              or p.name in {'screen-translator.ico','screen-translator.png'}]
    paths += list((ROOT/'.github'/'workflows').glob('*.yml'))
    paths += list((ROOT/'.github'/'ISSUE_TEMPLATE').glob('*.yml'))
    paths += list((ROOT/'docs').glob('*.md'))
    paths += [p for p in (ROOT/'docs'/'media').glob('*') if p.suffix.lower() in {'.png','.gif','.mp4'}]
    missing=[str(p.relative_to(ROOT)) for p in paths if not p.is_file()]
    if missing: raise RuntimeError('缺少发布文件：'+', '.join(missing))
    for path in paths:
        if path.is_symlink(): raise RuntimeError('不打包符号链接：'+str(path))
    return sorted(set(paths))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    files=source_files();args.output.parent.mkdir(parents=True,exist_ok=True)
    manifest=[]
    with zipfile.ZipFile(args.output,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for file in files:
            name=file.relative_to(ROOT).as_posix();data=file.read_bytes()
            info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(info,data)
            manifest.append(dict(path=name,size=len(data),sha256=hashlib.sha256(data).hexdigest()))
    with zipfile.ZipFile(args.output) as z:
        assert z.testzip() is None
        assert set(z.namelist())=={p.relative_to(ROOT).as_posix() for p in files}
        assert all(not any(part.startswith('_backup') or part=='_tmp_cfg' for part in Path(n).parts)
                   and Path(n).name!='config.json' for n in z.namelist())
    digest=hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.output.with_suffix('.manifest.json').write_text(json.dumps(dict(archive_sha256=digest,files=manifest),ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'SOURCE_PACKAGE_PASS ({len(files)} files; sha256={digest})')

if __name__=='__main__': main()
