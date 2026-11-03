"""真实 Qt 事件循环下记录切换延迟、导航/页面绘制、底层控件重绘量。"""
import argparse, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication
from core.config import Config
from ui import motion, glass, design as d
from ui.settings import SettingsWindow
from ui.navigation import CapsuleNavigation
from ui.widgets import SettingsCard
import main as M

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--theme', choices=['system', 'light', 'dark', 'glass'], default='system')
parser.add_argument('--scheme', choices=['light', 'dark'])
parser.add_argument('report', nargs='?', type=Path,
                    default=Path(__file__).parent/'_tmp_cfg'/'switch-benchmark.json')
args = parser.parse_args()

app = QApplication([]); M.setup_application(app)
motion.system_allows_motion = lambda: True
motion.configure(True)
d.set_theme(args.theme, {'light': Qt.ColorScheme.Light, 'dark': Qt.ColorScheme.Dark}.get(args.scheme))
active = [None]
rows = []
original_nav = CapsuleNavigation.paintEvent
original_play = motion.PageTransition.play
original_page = motion.PageTransition.paintEvent
original_card = SettingsCard.paintEvent

def nav(self,event):
    start=time.perf_counter();original_nav(self,event);end=time.perf_counter()
    if active[0] is not None:
        active[0]['nav_ms'].append((end-start)*1000)
        active[0]['frames_ms'].append((end-active[0]['started'])*1000)

def play(self,*args):
    start=time.perf_counter();original_play(self,*args)
    if active[0] is not None: active[0]['capture_ms'].append((time.perf_counter()-start)*1000)

def page(self,event):
    start=time.perf_counter();original_page(self,event)
    if active[0] is not None: active[0]['overlay_ms'].append((time.perf_counter()-start)*1000)

def card(self,event):
    start=time.perf_counter();original_card(self,event)
    if active[0] is not None:
        active[0]['card_paints']+=1
        active[0]['card_ms'].append((time.perf_counter()-start)*1000)

CapsuleNavigation.paintEvent=nav
motion.PageTransition.play=play
motion.PageTransition.paintEvent=page
SettingsCard.paintEvent=card
cfg = Config(str(Path(__file__).parent/'_tmp_cfg'/'switch-profile.json'))
cfg.set('ui.theme', args.theme)
window=SettingsWindow(cfg);window.resize(920,740);window.show()
last=[time.perf_counter()]
def heartbeat():
    now=time.perf_counter()
    if active[0] is not None:active[0]['loop_ms'].append((now-last[0])*1000)
    last[0]=now
timer=QTimer();timer.setTimerType(Qt.PreciseTimer);timer.setInterval(4);timer.timeout.connect(heartbeat);timer.start()
steps=iter([1,2,3,4,0,1,2,3,4,0])
def next_step():
    if active[0] is not None: rows.append(active[0]);active[0]=None
    index=next(steps,None)
    if index is None:
        app.exit(0);return
    row=dict(target=index,started=time.perf_counter(),nav_ms=[],frames_ms=[],capture_ms=[],overlay_ms=[],card_ms=[],card_paints=0,loop_ms=[],material_builds_start=glass._build_count)
    active[0]=row
    start=time.perf_counter();window._navigation.setCurrentRow(index)
    row['click_ms']=(time.perf_counter()-start)*1000
    row['material_builds_sync']=glass._build_count-row['material_builds_start']
    QTimer.singleShot(440,next_step)
QTimer.singleShot(600,next_step)
app.exec();window.hide()
args.report.parent.mkdir(parents=True, exist_ok=True)
args.report.write_text(json.dumps(dict(dpr=window.devicePixelRatioF(),
    refresh_hz=window.screen().refreshRate(),theme=args.theme,scheme=d.CURRENT_THEME,rows=rows),indent=2),encoding='utf-8')
for row in rows:
    times=[t for t in row['frames_ms'] if t<330]
    gaps=[b-a for a,b in zip(times,times[1:])]
    print(json.dumps(dict(target=row['target'],click_ms=round(row['click_ms'],2),capture_ms=[round(v,2) for v in row['capture_ms']],frames=len(times),max_gap_ms=round(max(gaps),2) if gaps else 0,nav_total_ms=round(sum(row['nav_ms']),2),card_paints=row['card_paints'],card_total_ms=round(sum(row['card_ms']),2),loop_max_ms=round(max(row['loop_ms']),2))))
