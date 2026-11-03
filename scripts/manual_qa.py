"""本地体验台：真实窗口/抓屏/OCR，翻译只连接本进程的 127.0.0.1。

不读取实盘配置。五分钟后自动退出，也可从悬浮入口退出。
"""
import json, os, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QApplication, QWidget
from core.config import Config
from ui import design as d
import main as M

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        data=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
        translated='请打开设置窗口，然后点击保存。' if 'settings' in data['text'].lower() else '实时翻译窗口已更新，阅读位置保持稳定。'
        body=json.dumps({'translation':translated},ensure_ascii=False).encode('utf-8')
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)

class Source(QWidget):
    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setWindowTitle('ScreenTranslator QA Source')
        self.setGeometry(100,100,720,150)
        self.text='Please open the settings window and click Save.'
    def paintEvent(self,event):
        p=QPainter(self);p.fillRect(self.rect(),QColor('white'));p.setPen(QColor('black'));p.setFont(d.font(26))
        p.drawText(self.rect().adjusted(18,15,-18,-15),Qt.AlignLeft|Qt.AlignVCenter|Qt.TextWordWrap,self.text);p.end()

def main():
    app=QApplication([]);M.setup_application(app)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    cfg=Config(os.path.join(os.path.dirname(__file__),'_tmp_cfg','manual-qa.json'))
    cfg.set('translate.backends',['custom']);cfg.set('translate.enabled',{'custom':True})
    cfg.set('api.custom.url',f'http://127.0.0.1:{server.server_port}/translate');cfg.set('api.custom.response_path','translation')
    cfg.set('live.enabled',False);cfg.set('live.capture_excluded',False);cfg.set('live.interval_ms',500);cfg.set('live.show_stats',True)
    cfg.set('live.geometry',[100,100,720,150]);cfg.set('live.bg_opacity',85)
    ctrl=M.Controller(cfg);source=Source();source.show();ctrl.show_live_window();ctrl._live.setWindowTitle('实时翻译 · 本地体验测试')
    counts=[0];latency=[];last=[time.perf_counter()]
    def heartbeat():
        stamp=time.perf_counter();latency.append((stamp-last[0])*1000);last[0]=stamp
    timer=QTimer();timer.setInterval(16);timer.timeout.connect(heartbeat);timer.start()
    def sample(res):
        if res.translated or res.error:
            counts[0]+=1
            print(json.dumps(dict(event='translated',original=res.original,translated=res.translated,ocr_ms=res.ocr_ms,tr_ms=res.tr_ms,cache=res.cache_hit),ensure_ascii=True),flush=True)
    ctrl.live_result.connect(sample)
    QTimer.singleShot(1200, ctrl.open_settings)
    def change():
        source.text='The live translation window is updated.';source.update()
    QTimer.singleShot(20_000,change)
    QTimer.singleShot(300_000,ctrl.quit)
    try: app.exec()
    finally:
        ctrl.hide_live_window();server.shutdown();source.hide()
        values=sorted(latency)
        print(json.dumps(dict(results=counts[0],heartbeat_p95_ms=round(values[int(.95*(len(values)-1))],2) if values else None,heartbeat_max_ms=round(max(values),2) if values else None)),flush=True)

if __name__ == "__main__":
    main()
