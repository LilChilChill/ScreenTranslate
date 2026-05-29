import json
from pathlib import Path
from typing import Optional, Tuple

from PyQt5.QtCore import Qt, QThread, pyqtSignal, QRect, QPoint
from PyQt5.QtGui import QColor, QPainter, QPen, QFont
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QTextEdit,
    QGroupBox, QStatusBar, QDoubleSpinBox, QMessageBox,
)

import capture
import ocr_engine
import translator as trans_mod

CONFIG_PATH = Path.home() / ".screentranslate.json"

STYLE = """
QWidget {
    background: #1e1e2e;
    color: #cdd6f4;
    font-family: 'Segoe UI';
    font-size: 9pt;
}
QGroupBox {
    border: 1px solid #45475a;
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 6px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 8px;
    color: #89b4fa;
}
QLineEdit, QComboBox, QDoubleSpinBox, QTextEdit {
    background: #313244;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 4px 8px;
    color: #cdd6f4;
}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QTextEdit:focus {
    border-color: #89b4fa;
}
QPushButton {
    background: #45475a;
    border: none;
    border-radius: 4px;
    padding: 6px 14px;
    font-weight: 500;
}
QPushButton:hover  { background: #585b70; }
QPushButton:pressed { background: #313244; }
QPushButton:disabled { color: #6c7086; background: #2a2a3e; }
QStatusBar { background: #181825; color: #a6adc8; font-size: 8pt; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView {
    background: #313244;
    border: 1px solid #45475a;
    selection-background-color: #45475a;
    outline: none;
}
QScrollBar:vertical {
    background: #313244; width: 8px; border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #585b70; min-height: 20px; border-radius: 4px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _tag_to_name(tag: str) -> str:
    return next(
        (n for n, t in ocr_engine.SUPPORTED_LANGUAGES.items() if t == tag), tag
    )


def _set_combo(combo: QComboBox, text: str) -> None:
    idx = combo.findText(text)
    if idx >= 0:
        combo.setCurrentIndex(idx)


# ─────────────────────────────────────────────────────────────────────────────
# Overlay chọn vùng màn hình
# ─────────────────────────────────────────────────────────────────────────────

class SelectionOverlay(QWidget):
    region_selected = pyqtSignal(tuple)
    cancelled = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._p0: Optional[QPoint] = None
        self._p1: Optional[QPoint] = None
        self._active = False

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setCursor(Qt.CrossCursor)

        # Bao phủ tất cả màn hình
        geom = QApplication.primaryScreen().virtualGeometry()
        self.setGeometry(geom)
        self.showFullScreen()

    def paintEvent(self, _):
        p = QPainter(self)

        # Làm tối toàn màn hình
        p.fillRect(self.rect(), QColor(0, 0, 0, 140))

        if self._p0 and self._p1:
            rect = QRect(self._p0, self._p1).normalized()

            # Khoét lỗ trong vùng chọn (trong suốt)
            p.setCompositionMode(QPainter.CompositionMode_Clear)
            p.fillRect(rect, QColor(0, 0, 0, 0))

            # Vẽ viền xanh cho vùng chọn
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            p.setPen(QPen(QColor(64, 160, 255), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRect(rect)

            # Nhãn kích thước
            dim = f" {rect.width()} × {rect.height()} "
            fm = p.fontMetrics()
            tr = fm.boundingRect(dim)
            tr.adjust(-4, -2, 4, 2)
            tr.moveTopLeft(rect.bottomRight() + QPoint(4, 4))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(64, 160, 255, 220))
            p.drawRoundedRect(tr, 3, 3)
            p.setPen(Qt.white)
            p.drawText(tr, Qt.AlignCenter, dim)
        else:
            p.setPen(Qt.white)
            p.setFont(QFont("Segoe UI", 14))
            p.drawText(
                self.rect(),
                Qt.AlignCenter,
                "Kéo chuột để chọn vùng cần dịch\n(ESC để hủy)",
            )

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._p0 = self._p1 = e.pos()
            self._active = True

    def mouseMoveEvent(self, e):
        if self._active:
            self._p1 = e.pos()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or not self._active:
            return
        self._active = False
        self._p1 = e.pos()
        rect = QRect(self._p0, self._p1).normalized()
        if rect.width() > 10 and rect.height() > 10:
            g = self.mapToGlobal(rect.topLeft())
            self.region_selected.emit((g.x(), g.y(), rect.width(), rect.height()))
        else:
            self.cancelled.emit()
        self.close()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.cancelled.emit()
            self.close()


# ─────────────────────────────────────────────────────────────────────────────
# Worker threads
# ─────────────────────────────────────────────────────────────────────────────

class OneShotWorker(QThread):
    """Thực hiện một lần: chụp → OCR → dịch."""
    result = pyqtSignal(str, str)
    error  = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(self, region, src: str, tgt: str, api_key: str):
        super().__init__()
        self.region  = region
        self.src     = src
        self.tgt     = tgt
        self.api_key = api_key

    def run(self):
        try:
            self.status.emit("Đang chụp màn hình…")
            img = capture.capture_region(self.region)

            self.status.emit("Đang nhận dạng văn bản (OCR)…")
            text = ocr_engine.recognize(img, self.src)
            if not text.strip():
                self.status.emit("Không nhận dạng được văn bản trong vùng đã chọn.")
                return

            self.status.emit("Đang dịch…")
            translation = trans_mod.translate(
                text.strip(), _tag_to_name(self.src), _tag_to_name(self.tgt), self.api_key
            )
            self.result.emit(text.strip(), translation)
            self.status.emit("Hoàn thành")
        except Exception as exc:
            self.error.emit(str(exc))
            self.status.emit("Lỗi — xem bên dưới")


class AutoWorker(QThread):
    """Tự động lặp: chụp → OCR → dịch → chờ → lặp lại."""
    result = pyqtSignal(str, str)
    error  = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.region   = None
        self.src      = "en"
        self.tgt      = "vi"
        self.api_key  = ""
        self.interval = 2.0
        self._stop    = False
        self._last    = ""

    def stop(self):
        self._stop = True

    def run(self):
        self._stop = False
        while not self._stop:
            if self.region:
                try:
                    self.status.emit("Đang chụp màn hình…")
                    img = capture.capture_region(self.region)

                    self.status.emit("Đang OCR…")
                    text = ocr_engine.recognize(img, self.src)
                    clean = text.strip()

                    if clean and clean != self._last:
                        self._last = clean
                        self.status.emit("Đang dịch…")
                        translation = trans_mod.translate(
                            clean, _tag_to_name(self.src), _tag_to_name(self.tgt), self.api_key
                        )
                        self.result.emit(clean, translation)

                    self.status.emit("Sẵn sàng — đang theo dõi…")
                except Exception as exc:
                    self.error.emit(str(exc))
                    self.status.emit("Lỗi — xem bên dưới")

            # Ngủ ngắn để có thể dừng nhanh
            elapsed = 0.0
            while not self._stop and elapsed < self.interval:
                self.msleep(100)
                elapsed += 0.1


# ─────────────────────────────────────────────────────────────────────────────
# Cửa sổ chính
# ─────────────────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._region: Optional[Tuple] = None
        self._auto_worker: Optional[AutoWorker] = None
        self._oneshot_worker: Optional[OneShotWorker] = None
        self._cfg = _load_config()
        self._build_ui()
        self._load_settings()
        self.setStyleSheet(STYLE)

    # ── Xây dựng giao diện ────────────────────────────────────────────────

    def _build_ui(self):
        self.setWindowTitle("ScreenTranslate")
        self.setMinimumSize(460, 640)
        self.resize(480, 720)

        root = QWidget()
        self.setCentralWidget(root)
        vbox = QVBoxLayout(root)
        vbox.setSpacing(8)
        vbox.setContentsMargins(12, 10, 12, 10)

        # API Key
        g = QGroupBox("Claude API Key")
        h = QHBoxLayout(g)
        self.w_key = QLineEdit()
        self.w_key.setEchoMode(QLineEdit.Password)
        self.w_key.setPlaceholderText("sk-ant-…")
        h.addWidget(self.w_key)
        show_btn = QPushButton("Hiện")
        show_btn.setFixedWidth(54)
        show_btn.setCheckable(True)
        show_btn.toggled.connect(
            lambda on: self.w_key.setEchoMode(
                QLineEdit.Normal if on else QLineEdit.Password
            )
        )
        h.addWidget(show_btn)
        vbox.addWidget(g)

        # Ngôn ngữ
        g = QGroupBox("Ngôn ngữ")
        h = QHBoxLayout(g)
        h.addWidget(QLabel("Nguồn:"))
        self.w_src = QComboBox()
        self.w_src.addItems(ocr_engine.SUPPORTED_LANGUAGES.keys())
        h.addWidget(self.w_src, 1)
        swap_btn = QPushButton("⇄")
        swap_btn.setFixedWidth(36)
        swap_btn.setToolTip("Hoán đổi ngôn ngữ")
        swap_btn.clicked.connect(self._swap_langs)
        h.addWidget(swap_btn)
        h.addWidget(QLabel("Đích:"))
        self.w_tgt = QComboBox()
        self.w_tgt.addItems(ocr_engine.SUPPORTED_LANGUAGES.keys())
        h.addWidget(self.w_tgt, 1)
        vbox.addWidget(g)

        # Chụp & điều khiển
        g = QGroupBox("Chụp & Dịch")
        v = QVBoxLayout(g)

        h = QHBoxLayout()
        self.w_select = QPushButton("Chọn vùng màn hình")
        self.w_select.clicked.connect(self._pick_region)
        h.addWidget(self.w_select)
        self.w_region_lbl = QLabel("Chưa chọn vùng")
        self.w_region_lbl.setStyleSheet("color: #6c7086;")
        h.addWidget(self.w_region_lbl, 1)
        v.addLayout(h)

        h = QHBoxLayout()
        h.addWidget(QLabel("Tự động cập nhật mỗi:"))
        self.w_interval = QDoubleSpinBox()
        self.w_interval.setRange(0.5, 60.0)
        self.w_interval.setValue(2.0)
        self.w_interval.setSuffix("  giây")
        self.w_interval.setSingleStep(0.5)
        h.addWidget(self.w_interval)
        h.addStretch()
        v.addLayout(h)

        h = QHBoxLayout()
        self.w_once = QPushButton("Dịch một lần")
        self.w_once.setEnabled(False)
        self.w_once.clicked.connect(self._translate_once)
        h.addWidget(self.w_once)
        self.w_auto = QPushButton("▶  Bắt đầu tự động")
        self.w_auto.setEnabled(False)
        self.w_auto.clicked.connect(self._toggle_auto)
        h.addWidget(self.w_auto)
        v.addLayout(h)

        vbox.addWidget(g)

        # Kết quả
        g = QGroupBox("Kết quả")
        v = QVBoxLayout(g)

        h = QHBoxLayout()
        h.addWidget(QLabel("Văn bản gốc (OCR):"))
        h.addStretch()
        cp1 = QPushButton("Sao chép")
        cp1.setFixedWidth(80)
        cp1.clicked.connect(lambda: self._copy(self.w_ocr))
        h.addWidget(cp1)
        v.addLayout(h)
        self.w_ocr = QTextEdit()
        self.w_ocr.setReadOnly(True)
        self.w_ocr.setMaximumHeight(130)
        self.w_ocr.setPlaceholderText("Văn bản nhận dạng sẽ xuất hiện ở đây…")
        v.addWidget(self.w_ocr)

        h = QHBoxLayout()
        h.addWidget(QLabel("Bản dịch:"))
        h.addStretch()
        cp2 = QPushButton("Sao chép")
        cp2.setFixedWidth(80)
        cp2.clicked.connect(lambda: self._copy(self.w_trans))
        h.addWidget(cp2)
        v.addLayout(h)
        self.w_trans = QTextEdit()
        self.w_trans.setReadOnly(True)
        self.w_trans.setPlaceholderText("Bản dịch sẽ xuất hiện ở đây…")
        v.addWidget(self.w_trans, 1)

        vbox.addWidget(g, 1)

        self.w_status = QStatusBar()
        self.w_status.showMessage("Sẵn sàng")
        self.setStatusBar(self.w_status)

    # ── Cài đặt ──────────────────────────────────────────────────────────

    def _load_settings(self):
        self.w_key.setText(self._cfg.get("api_key", ""))
        _set_combo(self.w_src, self._cfg.get("src_lang", "English"))
        _set_combo(self.w_tgt, self._cfg.get("tgt_lang", "Tiếng Việt"))
        self.w_interval.setValue(self._cfg.get("interval", 2.0))

    def _save_settings(self):
        self._cfg.update({
            "api_key":  self.w_key.text(),
            "src_lang": self.w_src.currentText(),
            "tgt_lang": self.w_tgt.currentText(),
            "interval": self.w_interval.value(),
        })
        _save_config(self._cfg)

    def _swap_langs(self):
        a, b = self.w_src.currentText(), self.w_tgt.currentText()
        _set_combo(self.w_src, b)
        _set_combo(self.w_tgt, a)

    # ── Chọn vùng ────────────────────────────────────────────────────────

    def _pick_region(self):
        overlay = SelectionOverlay()
        overlay.region_selected.connect(self._on_region_selected)

    def _on_region_selected(self, region: tuple):
        self._region = region
        x, y, w, h = region
        self.w_region_lbl.setText(f"{w} × {h}  tại  ({x}, {y})")
        self.w_region_lbl.setStyleSheet("color: #a6e3a1;")
        self.w_once.setEnabled(True)
        self.w_auto.setEnabled(True)

    # ── Dịch một lần ─────────────────────────────────────────────────────

    def _translate_once(self):
        if not self._validate():
            return
        self._save_settings()

        self.w_once.setEnabled(False)
        src = ocr_engine.SUPPORTED_LANGUAGES[self.w_src.currentText()]
        tgt = ocr_engine.SUPPORTED_LANGUAGES[self.w_tgt.currentText()]

        self._oneshot_worker = OneShotWorker(
            self._region, src, tgt, self.w_key.text().strip()
        )
        self._oneshot_worker.result.connect(self._on_result)
        self._oneshot_worker.error.connect(
            lambda e: (
                QMessageBox.warning(self, "Lỗi dịch thuật", e),
                self.w_status.showMessage("Lỗi"),
            )
        )
        self._oneshot_worker.status.connect(self.w_status.showMessage)
        self._oneshot_worker.finished.connect(
            lambda: self.w_once.setEnabled(True)
        )
        self._oneshot_worker.start()

    # ── Tự động ──────────────────────────────────────────────────────────

    def _toggle_auto(self):
        if self._auto_worker and self._auto_worker.isRunning():
            self._stop_auto()
        else:
            if not self._validate():
                return
            self._start_auto()

    def _start_auto(self):
        self._save_settings()
        src = ocr_engine.SUPPORTED_LANGUAGES[self.w_src.currentText()]
        tgt = ocr_engine.SUPPORTED_LANGUAGES[self.w_tgt.currentText()]

        self._auto_worker = AutoWorker()
        self._auto_worker.region   = self._region
        self._auto_worker.src      = src
        self._auto_worker.tgt      = tgt
        self._auto_worker.api_key  = self.w_key.text().strip()
        self._auto_worker.interval = self.w_interval.value()
        self._auto_worker.result.connect(self._on_result)
        self._auto_worker.error.connect(
            lambda e: self.w_status.showMessage(f"Lỗi: {e[:100]}")
        )
        self._auto_worker.status.connect(self.w_status.showMessage)
        self._auto_worker.start()

        self.w_auto.setText("⏹  Dừng lại")
        self.w_auto.setStyleSheet(
            "background: #f38ba8; color: #1e1e2e; font-weight: bold;"
        )
        self.w_select.setEnabled(False)
        self.w_once.setEnabled(False)

    def _stop_auto(self):
        if self._auto_worker:
            self._auto_worker.stop()
            self._auto_worker.wait(3000)
            self._auto_worker = None

        self.w_auto.setText("▶  Bắt đầu tự động")
        self.w_auto.setStyleSheet("")
        self.w_select.setEnabled(True)
        self.w_once.setEnabled(True)
        self.w_status.showMessage("Đã dừng")

    # ── Helpers ───────────────────────────────────────────────────────────

    def _validate(self) -> bool:
        if not self.w_key.text().strip():
            QMessageBox.warning(self, "Thiếu API Key", "Vui lòng nhập Claude API Key.")
            return False
        if not self._region:
            QMessageBox.warning(self, "Chưa chọn vùng",
                                "Vui lòng nhấn 'Chọn vùng màn hình' trước.")
            return False
        return True

    def _on_result(self, ocr_text: str, translation: str):
        self.w_ocr.setPlainText(ocr_text)
        self.w_trans.setPlainText(translation)

    def _copy(self, widget: QTextEdit):
        text = widget.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.w_status.showMessage("Đã sao chép vào clipboard", 2000)

    def closeEvent(self, event):
        self._stop_auto()
        self._save_settings()
        super().closeEvent(event)
