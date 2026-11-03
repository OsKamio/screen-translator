"""生成与视频参考改版一致的墨黑/白字/橙点多尺寸图标，不需要外部图片。"""
from pathlib import Path
import struct
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PySide6.QtCore import QByteArray, QBuffer, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication
from ui import design as d

SIZES = [16, 24, 32, 48, 64, 128, 256]


def draw_icon(size):
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor('#17181B'))
    p.drawRoundedRect(QRectF(0, 0, size, size), size*.30, size*.30)
    if size < 32:
        pen = QPen(QColor('#FFFFFF'), max(1.3, size*.075))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        for y, xend in [(.48, .68), (.68, .58)]:
            p.drawLine(QPointF(size*.30, size*y), QPointF(size*xend, size*y))
    else:
        p.setPen(QColor('#FFFFFF'))
        p.setFont(d.font(size*.56, d.W_SEMI))
        p.drawText(image.rect(), Qt.AlignmentFlag.AlignCenter, '译')
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor('#F36942'))
    p.drawEllipse(QPointF(size*.78, size*.23), max(1.5, size*.055), max(1.5, size*.055))
    p.end()
    return image


def main():
    app = QApplication([])
    out = Path(__file__).resolve().parent.parent/'assets'
    entries = []
    for size in SIZES:
        image = draw_icon(size)
        data = QByteArray()
        buf = QBuffer(data)
        buf.open(QBuffer.OpenModeFlag.WriteOnly)
        image.save(buf, 'PNG')
        buf.close()
        entries.append((size, bytes(data)))
        if size == 256:
            image.save(str(out/'screen-translator.png'))
    offset = 6+16*len(entries)
    directory, payload = b'', b''
    for size, data in entries:
        dim = 0 if size == 256 else size
        directory += struct.pack('<BBBBHHII', dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        payload += data
    (out/'screen-translator.ico').write_bytes(struct.pack('<HHH', 0, 1, len(entries))+directory+payload)
    print('UI_ICON_READY (16/24/32/48/64/128/256)')


if __name__ == '__main__':
    main()
