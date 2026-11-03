"""一键离线回归；--desktop 另跑真实桌面/真实 OCR/本地 HTTP。"""
import argparse, json, os, subprocess, sys, time
from pathlib import Path

BASE = [
 'check_names.py', 'test_live_quality.py', 'smoke_config.py', 'smoke_custom_backend.py',
 'smoke_settings.py', 'smoke_menu.py', 'smoke_place.py', 'smoke_ui.py',
 'smoke_live_engine.py', 'smoke_live_window.py', 'smoke_theme.py',
 'smoke_motion.py', 'check_live_after_settings.py', 'check_live_interaction.py', 'check_video_design.py',
 'check_switch_performance.py',
 'check_glass_theme.py',
]
DESKTOP = ['check_hint_layout.py', 'check_live_no_flicker.py', 'smoke_window_capture.py',
           'check_live_local_e2e.py', 'stress_live.py', 'check_native_frame.py']

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--desktop', action='store_true')
    parser.add_argument('--report', type=Path)
    args=parser.parse_args()
    root=Path(__file__).resolve().parent
    rows=[]
    for name in BASE+(DESKTOP if args.desktop else []):
        env=os.environ.copy();env['PYTHONIOENCODING']='utf-8'
        if name in DESKTOP: env.pop('QT_QPA_PLATFORM',None)
        else: env['QT_QPA_PLATFORM']='offscreen'
        start=time.perf_counter()
        try:
            result=subprocess.run([sys.executable,str(root/name)],env=env,capture_output=True,
                                  text=True,encoding='utf-8',errors='replace',timeout=60)
            row=dict(script=name,passed=result.returncode==0,seconds=round(time.perf_counter()-start,2),
                     output=result.stdout+result.stderr)
        except subprocess.TimeoutExpired:
            row=dict(script=name,passed=False,seconds=60,output='超过 60 秒，已停止此脚本')
        rows.append(row)
        print(('PASS' if row['passed'] else 'FAIL')+' '+name+f" ({row['seconds']}s)",flush=True)
        if not row['passed']: print(row['output'],flush=True)
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f"CHECKS: {sum(r['passed'] for r in rows)}/{len(rows)} passed",flush=True)
    return int(any(not r['passed'] for r in rows))

if __name__=='__main__': sys.exit(main())
