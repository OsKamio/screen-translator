"""真实抓屏→真实 OCR→本地 HTTP→真实 UI 的离线端到端回归。"""
import json, os, sys, threading, time
from http.server import ThreadingHTTPServer
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from core.config import Config
from manual_qa import Handler, Source
import main as M

app=QApplication([]);M.setup_application(app)
server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
cfg=Config(os.path.join(os.path.dirname(__file__),'_tmp_cfg','local-e2e.json'))
cfg.set('ui.theme',next((arg.split('=',1)[1] for arg in sys.argv if arg.startswith('--theme=')),'system'))
cfg.set('translate.backends',['custom']);cfg.set('translate.enabled',{'custom':True})
cfg.set('api.custom.url',f'http://127.0.0.1:{server.server_port}/translate');cfg.set('api.custom.response_path','translation')
cfg.set('live.interval_ms',300);cfg.set('live.capture_excluded',False);cfg.set('live.show_stats',True)
source=Source()
source.setGeometry(80,app.primaryScreen().availableGeometry().bottom()-180,680,140)
g=source.geometry();cfg.set('live.geometry',[g.x(),g.y(),g.width(),g.height()])
ctrl=M.Controller(cfg)
results=[];errors=[];gaps=[];last=[time.perf_counter()];changed=[None]
def beat():
    stamp=time.perf_counter();gaps.append((stamp-last[0])*1000);last[0]=stamp
heartbeat=QTimer();heartbeat.setInterval(16);heartbeat.timeout.connect(beat);heartbeat.start()
def receive(res):
    if res.error: errors.append(res.error)
    if not res.translated: return
    results.append(res)
    if changed[0] is None:
        def change():
            source.text='The live translation window is updated.';changed[0]=time.perf_counter();source.update()
        QTimer.singleShot(400,change)
    elif 'updated' in res.original.lower():
        QTimer.singleShot(200,lambda: app.exit(0))
ctrl.live_result.connect(receive)
source.show();ctrl.show_live_window()
QTimer.singleShot(15_000,lambda: app.exit(1))
try:
    app.exec()
    assert results and 'settings' in results[0].original.lower(), results
    assert any('updated' in r.original.lower() for r in results), '字幕换字后没有更新'
    assert ctrl._live.isVisible() and ctrl._live._translated == results[-1].translated
    assert ctrl._live.windowOpacity() == 1
    report={'ocr_ms':[r.ocr_ms for r in results], 'local_http_ms':[r.tr_ms for r in results],
            'heartbeat_p95_ms':round(sorted(gaps)[int(.95*(len(gaps)-1))],2),
            'heartbeat_max_ms':round(max(gaps),2),'results':len(results),'errors':errors}
    if len(sys.argv)>1:
        from pathlib import Path
        Path(sys.argv[1]).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True))
    print('LOCAL_E2E_PASS (real capture, real OCR, sparse caption update, localhost HTTP, visible UI)')
finally:
    ctrl.hide_live_window();ctrl.ball.hide();source.hide();server.shutdown()
