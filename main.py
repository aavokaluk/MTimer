import sys
import ctypes
from pathlib import Path
import json
import winreg

from PySide6.QtCore import (
    Qt,
    QTimer,
    QUrl,
    QPoint,
    QEvent,
)
from PySide6.QtGui import (
    QColor,
    QPainter,
    QIcon,
    QFontMetrics,
    QDesktopServices,
)
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QPushButton,
    QLabel,
    QMenu,
    QLineEdit,
    QDialog,
    QVBoxLayout,
    QCheckBox,
    QDialogButtonBox,
    QFrame,
    QSlider,
    QHBoxLayout,
)


# ============================================================
# Пути
# ============================================================

def resource_path(relative_path):
    """Корректный путь для ресурсов (картинки, звуки) внутри сборки PyInstaller"""
    try:
        base_path = Path(sys._MEIPASS)
    except AttributeError:
        base_path = Path(__file__).resolve().parent
    return base_path / relative_path


ICON_PATH = resource_path("assets/MTimer_logo.ico")
MEDIA_DIR = resource_path("media")
CLICK_SOUND = MEDIA_DIR / "klick.wav"
DONE_SOUND = MEDIA_DIR / "timer_done.wav"

CONFIG_FILE = (
    Path(sys.executable).parent / "mtimer_config.json"
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent / "mtimer_config.json"
)


# ============================================================
# Windows API
# ============================================================

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

HWND_TOPMOST = -1

SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "MTimer"


# ============================================================
# Размеры
# ============================================================

TIMER_WIDTH = 150
TIMER_HEIGHT = 42

NOTE_MIN_WIDTH = 80
NOTE_MAX_WIDTH = 350
NOTE_HEIGHT = 30
NOTE_MAX_LENGTH = 38


# ============================================================
# Конфигурация
# ============================================================

DEFAULT_CONFIG = {
    "minutes": 25,
    "button_sound": True,
    "timer_sound": True,
    "timer_sound_loop": False,
    "autostart": False,
    "note_opacity": 95,
    "window_x": None,
    "window_y": None,
}


def load_config():
    config = DEFAULT_CONFIG.copy()
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "r", encoding="utf-8") as file:
                saved = json.load(file)
                if isinstance(saved, dict):
                    config.update(saved)
    except Exception:
        pass

    try:
        config["minutes"] = int(config.get("minutes", 25))
        if config["minutes"] <= 0:
            config["minutes"] = 25
    except Exception:
        config["minutes"] = 25

    config["button_sound"] = bool(config.get("button_sound", True))
    config["timer_sound"] = bool(config.get("timer_sound", True))
    config["timer_sound_loop"] = bool(config.get("timer_sound_loop", False))
    config["autostart"] = bool(config.get("autostart", False))

    try:
        config["note_opacity"] = int(config.get("note_opacity", 95))
        config["note_opacity"] = max(20, min(100, config["note_opacity"]))
    except Exception:
        config["note_opacity"] = 95

    try:
        if config.get("window_x") is not None:
            config["window_x"] = int(config["window_x"])
    except Exception:
        config["window_x"] = None

    try:
        if config.get("window_y") is not None:
            config["window_y"] = int(config["window_y"])
    except Exception:
        config["window_y"] = None

    return config


def save_config(config):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as file:
            json.dump(config, file, indent=4, ensure_ascii=False)
    except Exception:
        pass


# ============================================================
# Windows Autostart
# ============================================================

def is_autostart_enabled():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_READ)
        try:
            winreg.QueryValueEx(key, APP_NAME)
            return True
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False


def set_autostart(enabled):
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_SET_VALUE)
        try:
            if enabled:
                if getattr(sys, "frozen", False):
                    command = f'"{sys.executable}"'
                else:
                    command = f'"{sys.executable}" "{Path(__file__).resolve()}"'
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
        finally:
            winreg.CloseKey(key)
        return True
    except Exception:
        return False


# ============================================================
# Action Button
# ============================================================

class ActionButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pause_mode = False
        self.setFixedSize(20, 20)
        self.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: rgba(220, 225, 230, 190);
                font-size: 15px;
                padding: 0px;
            }
            QPushButton:hover {
                color: rgba(255, 255, 255, 255);
            }
            QPushButton:pressed {
                color: white;
            }
            QPushButton:disabled {
                color: rgba(120, 125, 130, 100);
            }
        """)

    def setPauseMode(self, enabled):
        self.pause_mode = enabled
        if enabled:
            self.setText("")
        self.update()

    def paintEvent(self, event):
        if not self.pause_mode:
            super().paintEvent(event)
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(220, 225, 230, 190))
        painter.drawRoundedRect(5, 5, 4, 10, 1.5, 1.5)
        painter.drawRoundedRect(11, 5, 4, 10, 1.5, 1.5)


# ============================================================
# Окно заметки
# ============================================================

class NoteWindow(QWidget):
    def __init__(self, owner):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.owner = owner
        self.drag_position = None

        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedHeight(NOTE_HEIGHT)
        self.setMinimumWidth(NOTE_MIN_WIDTH)
        self.setMaximumWidth(NOTE_MAX_WIDTH)

        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))

        self.editor = QLineEdit(self)
        self.editor.setPlaceholderText("Note...")
        self.editor.setMaxLength(NOTE_MAX_LENGTH)
        self.editor.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        self.editor.setStyleSheet("""
            QLineEdit {
                color: rgba(240, 242, 244, 255);
                background: transparent;
                border: none;
                padding: 0px 10px;
                font-size: 12px;
                font-weight: 700;
                selection-background-color: #4A535C;
            }
            QLineEdit:focus {
                border: none;
            }
        """)

        self.editor.returnPressed.connect(self.finish_editing)
        self.editor.textChanged.connect(self.update_note_size)

        self.installEventFilter(self)
        self.editor.installEventFilter(self)

        self.update_note_size()
        self.hide()

    def get_opacity_alpha(self):
        if self.owner is None:
            return 242
        opacity = max(20, min(100, self.owner.note_opacity))
        return int(255 * opacity / 100)

    def update_opacity(self):
        alpha_factor = self.get_opacity_alpha() / 255.0
        self.editor.setStyleSheet(f"""
            QLineEdit {{
                background: transparent;
                border: none;
                font-weight: bold;
                color: rgba(255, 255, 255, {alpha_factor:.2f});
            }}
        """)
        self.update()
        self.editor.update()

    def update_note_size(self):
        text = self.editor.text()
        display_text = text if text else self.editor.placeholderText()
        font_metrics = QFontMetrics(self.editor.font())
        text_width = font_metrics.horizontalAdvance(display_text)

        new_width = max(NOTE_MIN_WIDTH, min(NOTE_MAX_WIDTH, text_width + 34))
        self.setFixedSize(new_width, NOTE_HEIGHT)
        self.editor.setGeometry(4, 3, self.width() - 8, NOTE_HEIGHT - 6)

        cursor_pos = self.editor.cursorPosition()
        self.editor.setCursorPosition(0)
        self.editor.setCursorPosition(cursor_pos)

        if self.isVisible():
            self.update_position()

    def update_position(self):
        if self.owner is None:
            return
        timer_geometry = self.owner.frameGeometry()
        x = timer_geometry.center().x() - self.width() // 2
        y = timer_geometry.center().y() - self.height() // 2 - 35
        self.move(x, y)

    def show_note(self):
        self.update_note_size()
        self.update_position()
        self.show()
        self.raise_()
        self.activateWindow()
        self.editor.setFocus()
        self.editor.setCursorPosition(len(self.editor.text()))

    def start_editing(self):
        if not self.isVisible():
            return
        self.activateWindow()
        self.editor.setFocus()
        self.editor.setCursorPosition(len(self.editor.text()))

    def finish_editing(self):
        if self.owner is None:
            return
        text = self.editor.text().strip()
        self.owner.note_text = text
        self.owner.note_editing = False
        self.editor.clearFocus()
        self.update_note_size()

        if not text:
            QTimer.singleShot(0, self.owner.hide_note)

    def hide_note(self):
        self.editor.clearFocus()
        self.hide()

    def focusOutEvent(self, event):
        if self.owner is not None and self.owner.note_editing:
            self.finish_editing()
        super().focusOutEvent(event)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress:
            if obj is self.editor:
                if self.owner is not None:
                    self.owner.note_editing = True
                self.editor.setFocus()
            else:
                if self.owner is not None and self.owner.note_editing:
                    self.finish_editing()
        elif event.type() == QEvent.WindowDeactivate:
            if self.owner is not None:
                if self.owner.note_editing:
                    self.finish_editing()
                elif not self.owner.note_text.strip():
                    QTimer.singleShot(0, self.owner.hide_note)
        elif event.type() == QEvent.FocusOut:
            if obj is self.editor and self.owner is not None and self.owner.note_editing:
                QTimer.singleShot(0, self.finish_editing)

        return super().eventFilter(obj, event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and self.drag_position is not None:
            new_position = event.globalPosition().toPoint() - self.drag_position
            self.move(new_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_position = None
            if self.owner is not None:
                self.update_position()
            event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        alpha = self.get_opacity_alpha()

        for i in range(4):
            shadow_alpha = int((18 - i * 4) * alpha / 255)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QColor(0, 0, 0, max(shadow_alpha, 2)))
            painter.drawRoundedRect(i, i, self.width() - 1 - i * 2, self.height() - 1 - i * 2, 14, 14)

        painter.setBrush(QColor(21, 25, 30, alpha))
        border_alpha = int(255 * alpha / 255)
        painter.setPen(QColor(60, 67, 75, border_alpha))
        painter.drawRoundedRect(1, 1, self.width() - 3, self.height() - 3, 14, 14)


# ============================================================
# Settings Dialog
# ============================================================

class SettingsDialog(QDialog):
    def __init__(self, button_sound, timer_sound, timer_sound_loop, autostart, note_opacity, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MTimer Settings")
        self.setFixedWidth(320)

        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))

        self.setStyleSheet("""
            QDialog {
                background: #15191E;
                color: #F0F2F4;
            }
            QLabel {
                color: #F0F2F4;
                font-size: 13px;
            }
            QCheckBox {
                color: #F0F2F4;
                font-size: 13px;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 15px;
                height: 15px;
            }
            QCheckBox::indicator:unchecked {
                border: 1px solid #59616A;
                background: #20252B;
                border-radius: 4px;
            }
            QCheckBox::indicator:checked {
                border: 1px solid #8A949E;
                background: #7D8791;
                border-radius: 4px;
            }
            QSlider::groove:horizontal {
                height: 4px;
                background: #343B42;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #7D8791;
                width: 14px;
                margin: -5px 0px;
                border-radius: 7px;
            }
            QPushButton {
                background: #252B31;
                color: #F0F2F4;
                border: 1px solid #3D454D;
                border-radius: 6px;
                padding: 6px 14px;
            }
            QPushButton:hover {
                background: #30373F;
            }
            QPushButton:pressed {
                background: #1D2227;
            }
        """)

        layout = QVBoxLayout()
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        # Sounds
        sound_title = QLabel("Sounds")
        sound_title.setStyleSheet("font-size: 15px; font-weight: 700; margin-bottom: 3px;")
        layout.addWidget(sound_title)

        self.button_sound_checkbox = QCheckBox("Button sounds")
        self.button_sound_checkbox.setChecked(button_sound)
        layout.addWidget(self.button_sound_checkbox)

        self.timer_sound_checkbox = QCheckBox("Timer completion sound")
        self.timer_sound_checkbox.setChecked(timer_sound)
        layout.addWidget(self.timer_sound_checkbox)

        self.loop_checkbox = QCheckBox("Loop completion sound")
        self.loop_checkbox.setChecked(timer_sound_loop)
        layout.addWidget(self.loop_checkbox)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #343B42;")
        layout.addWidget(line)

        # Note
        note_title = QLabel("Note")
        note_title.setStyleSheet("font-size: 15px; font-weight: 700; margin-bottom: 3px;")
        layout.addWidget(note_title)

        opacity_layout = QHBoxLayout()
        opacity_label = QLabel("Note opacity")
        self.opacity_value_label = QLabel()
        self.note_opacity_slider = QSlider(Qt.Horizontal)
        self.note_opacity_slider.setMinimum(20)
        self.note_opacity_slider.setMaximum(100)
        self.note_opacity_slider.setValue(note_opacity)
        self.opacity_value_label.setFixedWidth(38)
        self.opacity_value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        opacity_layout.addWidget(opacity_label)
        opacity_layout.addWidget(self.opacity_value_label)
        layout.addLayout(opacity_layout)
        layout.addWidget(self.note_opacity_slider)

        self.update_opacity_label(note_opacity)
        self.note_opacity_slider.valueChanged.connect(self.update_opacity_label)

        line2 = QFrame()
        line2.setFrameShape(QFrame.HLine)
        line2.setStyleSheet("color: #343B42;")
        layout.addWidget(line2)

        # Startup
        autostart_title = QLabel("Startup")
        autostart_title.setStyleSheet("font-size: 15px; font-weight: 700; margin-bottom: 3px;")
        layout.addWidget(autostart_title)

        self.autostart_checkbox = QCheckBox("Start MTimer with Windows")
        self.autostart_checkbox.setChecked(autostart)
        layout.addWidget(self.autostart_checkbox)

        # Patreon
        line3 = QFrame()
        line3.setFrameShape(QFrame.HLine)
        line3.setStyleSheet("color: #343B42;")
        layout.addWidget(line3)

        patreon_label = QLabel('<a href="https://www.patreon.com/cw/Vokaluk">Support MTimer on Patreon</a>')
        patreon_label.setOpenExternalLinks(True)
        patreon_label.setAlignment(Qt.AlignCenter)
        patreon_label.setStyleSheet("""
            QLabel {
                color: #9AA3AC;
                font-size: 12px;
            }
            QLabel a {
                color: #FF6B35;
                text-decoration: none;
            }
            QLabel a:hover {
                color: #FF8A22;
                text-decoration: underline;
            }
        """)
        layout.addWidget(patreon_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)

    def update_opacity_label(self, value):
        self.opacity_value_label.setText(f"{value}%")

    def get_settings(self):
        return {
            "button_sound": self.button_sound_checkbox.isChecked(),
            "timer_sound": self.timer_sound_checkbox.isChecked(),
            "timer_sound_loop": self.loop_checkbox.isChecked(),
            "autostart": self.autostart_checkbox.isChecked(),
            "note_opacity": self.note_opacity_slider.value(),
        }


# ============================================================
# MTimer
# ============================================================

class MTimer(QWidget):
    def __init__(self):
        super().__init__()

        self.config = load_config()
        self.minutes = int(self.config["minutes"])
        self.old_minutes = self.minutes
        self.button_sound_enabled = bool(self.config["button_sound"])
        self.timer_sound_enabled = bool(self.config["timer_sound"])
        self.timer_sound_loop = bool(self.config["timer_sound_loop"])
        self.autostart_enabled = bool(self.config["autostart"])
        self.note_opacity = int(self.config["note_opacity"])

        real_autostart = is_autostart_enabled()
        if real_autostart != self.autostart_enabled:
            self.autostart_enabled = real_autostart
            self.config["autostart"] = real_autostart
            save_config(self.config)

        self.setWindowTitle("MTimer")
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.radius = 14
        self.drag_position = None

        self.setFixedSize(TIMER_WIDTH, TIMER_HEIGHT)

        self.editing = False
        self.remaining_seconds = self.minutes * 60
        self.running = False
        self.paused = False
        self.finished = False

        self.note_visible = False
        self.note_editing = False
        self.note_text = ""
        self.note_window = NoteWindow(self)

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)

        self.position_timer = QTimer(self)
        self.position_timer.setInterval(50)
        self.position_timer.timeout.connect(self.update_note_position)

        self.click_sound = QSoundEffect(self)
        self.click_sound.setVolume(0.35)
        if CLICK_SOUND.exists():
            self.click_sound.setSource(QUrl.fromLocalFile(str(CLICK_SOUND)))

        self.done_sound = QSoundEffect(self)
        self.done_sound.setVolume(0.7)
        if DONE_SOUND.exists():
            self.done_sound.setSource(QUrl.fromLocalFile(str(DONE_SOUND)))

        self.done_sound_loop_active = False
        self.done_sound_loop_timer = QTimer(self)
        self.done_sound_loop_timer.setSingleShot(True)
        self.done_sound_loop_timer.timeout.connect(self.restart_done_sound)

        # Time label (Верхний ярус)
        self.time_label = QLabel(self)
        self.time_label.setStyleSheet("""
            QLabel {
                color: #F0F2F4;
                font-size: 13px;
                font-weight: 700;
                background: transparent;
            }
        """)

        # Time edit
        self.time_edit = QLineEdit(self)
        self.time_edit.setAlignment(Qt.AlignCenter)
        self.time_edit.setPlaceholderText("min")
        self.time_edit.setStyleSheet("""
            QLineEdit {
                color: #F0F2F4;
                font-size: 13px;
                font-weight: 700;
                background: transparent;
                border: none;
                padding: 0px;
            }
        """)
        self.time_edit.setFixedSize(54, 18)
        self.time_edit.hide()
        self.time_edit.returnPressed.connect(self.confirm_edit)

        # Note button
        self.note_button = QPushButton("📄", self)
        self.note_button.setFixedSize(18, 18)
        self.note_button.setToolTip("Note")
        self.note_button.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: rgba(220, 225, 230, 190);
                font-size: 12px;
                padding: 0px;
            }
            QPushButton:hover {
                color: rgba(255, 255, 255, 255);
            }
            QPushButton:pressed {
                color: white;
            }
        """)
        self.note_button.clicked.connect(self.toggle_note)

        # Quick Adjust Buttons: '-' и '+' (Нижний ярус строго под цифрами)
        quick_btn_style = """
            QPushButton {
                background: #1C2128;
                border: 1px solid #333945;
                border-radius: 3px;
                color: rgba(200, 205, 210, 180);
                font-size: 11px;
                font-weight: bold;
                padding: 0px;
                padding-bottom: 1px;
            }
            QPushButton:hover {
                background: #252D37;
                border-color: #FF9800;
                color: #FFFFFF;
            }
            QPushButton:pressed {
                background: #14171D;
                border-color: #E65100;
                color: #FF9800;
            }
            QPushButton:disabled {
                background: #15191E;
                border-color: #262B33;
                color: rgba(120, 125, 130, 70);
            }
        """
        self.sub_button = QPushButton("−", self)
        self.sub_button.setFixedSize(18, 10)
        self.sub_button.setToolTip("−1 min (Shift/Ctrl: −5 min)")
        self.sub_button.setStyleSheet(quick_btn_style)
        self.sub_button.clicked.connect(lambda: self.adjust_time(-1, -5))

        self.add_button = QPushButton("+", self)
        self.add_button.setFixedSize(18, 10)
        self.add_button.setToolTip("+1 min (Shift/Ctrl: +5 min)")
        self.add_button.setStyleSheet(quick_btn_style)
        self.add_button.clicked.connect(lambda: self.adjust_time(1, 5))

        # Action button (Play / Pause / Confirm)
        self.action_button = ActionButton(self)
        self.action_button.setText("▶")
        self.action_button.clicked.connect(self.action_clicked)

        # Stop button
        self.stop_button = QPushButton("■", self)
        self.stop_button.setFixedSize(18, 18)
        self.stop_button.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: rgba(220, 225, 230, 180);
                font-size: 12px;
                padding: 0px;
            }
            QPushButton:hover {
                color: rgba(255, 255, 255, 255);
            }
            QPushButton:pressed {
                color: white;
            }
            QPushButton:disabled {
                color: rgba(120, 125, 130, 80);
            }
        """)
        self.stop_button.clicked.connect(self.stop_and_reset)
        self.stop_button.hide()

        # Close button
        self.close_button = QPushButton("×", self)
        self.close_button.setFixedSize(18, 18)
        self.close_button.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: rgba(180, 185, 190, 150);
                font-size: 15px;
                font-weight: normal;
                padding: 0px;
            }
            QPushButton:hover {
                color: rgba(240, 240, 240, 230);
            }
            QPushButton:pressed {
                color: white;
            }
            QPushButton:disabled {
                color: rgba(100, 105, 110, 70);
            }
        """)
        self.close_button.clicked.connect(self.close_or_cancel)

        self.update_time_display()
        self.update_layout()
        self.restore_window_position()

    # ========================================================
    # Quick Adjust Control
    # ========================================================

    def set_adjust_buttons_enabled(self, enabled: bool):
        self.sub_button.setEnabled(enabled)
        self.add_button.setEnabled(enabled)

    def adjust_time(self, default_step_min: int, fast_step_min: int):
        if self.editing or self.running or self.paused:
            return

        self.play_click()
        modifiers = QApplication.keyboardModifiers()
        if modifiers & (Qt.ShiftModifier | Qt.ControlModifier):
            step = fast_step_min
        else:
            step = default_step_min

        new_minutes = max(1, self.minutes + step)
        self.minutes = new_minutes
        self.remaining_seconds = self.minutes * 60
        self.config["minutes"] = self.minutes
        save_config(self.config)
        self.update_time_display()

    # ========================================================
    # Note
    # ========================================================

    def toggle_note(self):
        self.play_click()
        if not self.note_visible:
            self.note_visible = True
            self.note_editing = True
            self.note_window.editor.setText(self.note_text)
            self.note_window.show_note()
            self.position_timer.start()
            return
        self.hide_note()

    def hide_note(self):
        if not self.note_visible:
            return
        self.note_visible = False
        self.note_editing = False
        self.note_window.hide_note()
        self.position_timer.stop()
        self.note_text = ""
        self.note_window.editor.clear()

    def update_note_position(self):
        if not self.note_visible:
            return
        self.note_window.update_position()

    # ========================================================
    # Sounds
    # ========================================================

    def play_click(self):
        if not self.button_sound_enabled or not CLICK_SOUND.exists():
            return
        self.click_sound.stop()
        self.click_sound.play()

    def play_done_sound(self):
        if not self.timer_sound_enabled or not DONE_SOUND.exists():
            return
        self.stop_done_sound()
        if not self.timer_sound_loop:
            self.done_sound.play()
            return
        self.done_sound_loop_active = True
        self.done_sound.play()
        self.schedule_done_sound_loop()

    def schedule_done_sound_loop(self):
        if not self.done_sound_loop_active:
            return
        self.done_sound_loop_timer.start(100)

    def restart_done_sound(self):
        if not self.done_sound_loop_active or not self.timer_sound_enabled or not self.timer_sound_loop:
            self.stop_done_sound()
            return
        if not self.done_sound.isPlaying():
            self.done_sound.play()
        self.schedule_done_sound_loop()

    def stop_done_sound(self):
        self.done_sound_loop_active = False
        self.done_sound_loop_timer.stop()
        self.done_sound.stop()

    # ========================================================
    # Layout
    # ========================================================

    def update_layout(self):
        width = TIMER_WIDTH
        center_y = TIMER_HEIGHT // 2

        # 1. Боковые кнопки
        self.note_button.move(6, center_y - self.note_button.height() // 2)
        self.action_button.move(width - 46, center_y - self.action_button.height() // 2)
        self.stop_button.move(width - 30, center_y - self.stop_button.height() // 2)
        self.close_button.move(width - 22, 0)

        # Смещение центрального блока влево
        CENTER_OFFSET = 10

        # 2. Цифры таймера (верхний ярус)
        self.time_label.adjustSize()
        label_x = (width - self.time_label.width()) // 2 - CENTER_OFFSET
        self.time_label.move(label_x, 8)
        self.time_edit.move((width - self.time_edit.width()) // 2 - CENTER_OFFSET, 5)

        # 3. Кнопки '-' и '+' (нижний ярус, строго под цифрами)
        btn_y = 27
        spacing = 6
        total_btns_width = self.sub_button.width() + spacing + self.add_button.width()
        start_x = (width - total_btns_width) // 2 - CENTER_OFFSET

        self.sub_button.move(start_x, btn_y)
        self.add_button.move(start_x + self.sub_button.width() + spacing, btn_y)

    # ========================================================
    # Main button & Control
    # ========================================================

    def action_clicked(self):
        self.play_click()
        if self.editing:
            self.confirm_edit()
            return
        if self.finished:
            self.reset_finished_timer()
            return
        if self.running:
            self.pause_timer()
            return
        if self.paused:
            self.resume_timer()
            return
        self.start_timer()

    def start_timer(self):
        if self.remaining_seconds <= 0:
            return
        self.stop_done_sound()
        self.running = True
        self.paused = False
        self.finished = False
        self.timer.start()

        self.set_adjust_buttons_enabled(False)

        self.action_button.setPauseMode(True)
        self.stop_button.hide()
        self.stop_button.setEnabled(False)
        self.close_button.setEnabled(False)
        self.update_layout()

    def pause_timer(self):
        if not self.running:
            return
        self.running = False
        self.paused = True
        self.timer.stop()

        self.set_adjust_buttons_enabled(False)

        self.action_button.setPauseMode(False)
        self.action_button.setText("▶")
        self.stop_button.setEnabled(True)
        self.stop_button.show()
        self.close_button.setEnabled(True)
        self.update_layout()

    def resume_timer(self):
        if not self.paused or self.remaining_seconds <= 0:
            return
        self.running = True
        self.paused = False
        self.timer.start()

        self.set_adjust_buttons_enabled(False)

        self.action_button.setPauseMode(True)
        self.stop_button.setEnabled(False)
        self.stop_button.hide()
        self.close_button.setEnabled(False)
        self.update_layout()

    def stop_and_reset(self):
        if self.running:
            return
        self.play_click()
        self.stop_done_sound()
        self.timer.stop()
        self.running = False
        self.paused = False
        self.finished = False
        self.remaining_seconds = self.minutes * 60

        self.set_adjust_buttons_enabled(True)

        self.action_button.setPauseMode(False)
        self.action_button.setText("▶")
        self.stop_button.setEnabled(True)
        self.stop_button.hide()
        self.close_button.setEnabled(True)

        self.update_time_display()
        self.update_layout()

    def reset_finished_timer(self):
        self.stop_done_sound()
        self.timer.stop()
        self.running = False
        self.paused = False
        self.finished = False
        self.remaining_seconds = self.minutes * 60

        self.set_adjust_buttons_enabled(True)

        self.action_button.setPauseMode(False)
        self.action_button.setText("▶")
        self.stop_button.setEnabled(True)
        self.stop_button.hide()
        self.close_button.setEnabled(True)

        self.update_time_display()
        self.update_layout()

    def tick(self):
        if self.remaining_seconds <= 0:
            self.finish_timer()
            return
        self.remaining_seconds -= 1
        self.update_countdown_display()
        if self.remaining_seconds <= 0:
            self.finish_timer()

    def finish_timer(self):
        self.remaining_seconds = 0
        self.running = False
        self.paused = False
        self.finished = True
        self.timer.stop()

        self.set_adjust_buttons_enabled(True)

        self.stop_button.hide()
        self.stop_button.setEnabled(False)
        self.close_button.setEnabled(True)
        self.action_button.setPauseMode(False)
        self.action_button.setText("↻")

        self.update_countdown_display()
        self.play_done_sound()
        self.update_layout()

    def update_countdown_display(self):
        total_seconds = self.remaining_seconds
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        if hours > 0:
            text = f"{hours}:{minutes:02d}:{seconds:02d}"
        else:
            text = f"{minutes}:{seconds:02d}"

        self.time_label.setText(text)
        self.time_label.adjustSize()
        self.update_layout()

    def update_time_display(self):
        total_minutes = self.minutes
        hours = total_minutes // 60
        minutes = total_minutes % 60

        if hours > 0:
            text = f"{hours}:{minutes:02d}:00"
        else:
            text = f"{minutes}:00"

        self.time_label.setText(text)
        self.time_label.adjustSize()
        self.update_layout()

    def start_editing(self):
        if self.editing or self.running or self.paused or self.finished:
            return
        self.play_click()
        self.editing = True
        self.old_minutes = self.minutes
        self.time_edit.setText(str(self.minutes))
        self.time_label.hide()
        self.time_edit.show()

        self.set_adjust_buttons_enabled(False)

        self.action_button.setPauseMode(False)
        self.action_button.setText("✓")
        self.time_edit.setFocus()
        self.time_edit.selectAll()
        self.update_layout()

    def confirm_edit(self):
        if not self.editing:
            return
        value = self.time_edit.text().strip()
        if not value.isdigit() or int(value) <= 0:
            return

        self.minutes = int(value)
        self.remaining_seconds = self.minutes * 60
        self.running = False
        self.paused = False
        self.finished = False
        self.timer.stop()
        self.stop_done_sound()

        self.config["minutes"] = self.minutes
        save_config(self.config)

        self.editing = False
        self.time_edit.hide()
        self.time_label.show()

        self.set_adjust_buttons_enabled(True)

        self.action_button.setPauseMode(False)
        self.action_button.setText("▶")
        self.stop_button.setEnabled(True)
        self.stop_button.hide()
        self.close_button.setEnabled(True)

        self.update_time_display()
        self.update_layout()

    def close_or_cancel(self):
        if self.running:
            return
        self.play_click()
        if self.editing:
            self.minutes = self.old_minutes
            self.time_edit.hide()
            self.time_label.show()
            self.editing = False
            self.set_adjust_buttons_enabled(True)
            self.action_button.setPauseMode(False)
            self.action_button.setText("▶")
            self.stop_button.setEnabled(True)
            self.stop_button.hide()
            self.update_time_display()
            self.update_layout()
            return

        self.stop_done_sound()
        self.timer.stop()
        self.hide_note()
        self.save_window_position()
        QApplication.quit()

    def mouseDoubleClickEvent(self, event):
        if event.button() != Qt.LeftButton or self.running or self.paused or self.finished:
            return
        if self.time_label.geometry().contains(event.position().toPoint()):
            self.start_editing()

    def contextMenuEvent(self, event):
        if self.running:
            event.accept()
            return

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #181D22;
                color: #F0F2F4;
                border: 1px solid #3D454D;
                padding: 4px;
            }
            QMenu::item {
                padding: 2px 24px 2px 12px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background: #30373F;
            }
            QMenu::separator {
                height: 1px;
                background: #343B42;
                margin: 4px 8px;
            }
        """)

        settings_action = menu.addAction("Settings")
        action = menu.exec(event.globalPos())
        if action == settings_action:
            self.open_settings()

    def open_settings(self):
        if self.running:
            return

        dialog = SettingsDialog(
            self.button_sound_enabled,
            self.timer_sound_enabled,
            self.timer_sound_loop,
            self.autostart_enabled,
            self.note_opacity,
            self,
        )

        if dialog.exec() != QDialog.Accepted:
            return

        settings = dialog.get_settings()
        self.button_sound_enabled = settings["button_sound"]
        self.timer_sound_enabled = settings["timer_sound"]
        self.timer_sound_loop = settings["timer_sound_loop"]
        self.note_opacity = settings["note_opacity"]

        requested_autostart = settings["autostart"]
        if requested_autostart != self.autostart_enabled:
            success = set_autostart(requested_autostart)
            self.autostart_enabled = requested_autostart if success else is_autostart_enabled()

        self.config["minutes"] = self.minutes
        self.config["button_sound"] = self.button_sound_enabled
        self.config["timer_sound"] = self.timer_sound_enabled
        self.config["timer_sound_loop"] = self.timer_sound_loop
        self.config["autostart"] = self.autostart_enabled
        self.config["note_opacity"] = self.note_opacity
        save_config(self.config)

        self.note_window.update_opacity()

        if not self.timer_sound_enabled:
            self.stop_done_sound()
        elif not self.timer_sound_loop:
            self.done_sound_loop_active = False
            self.done_sound_loop_timer.stop()

    def restore_window_position(self):
        x = self.config.get("window_x")
        y = self.config.get("window_y")
        if x is not None and y is not None:
            self.move(int(x), int(y))
            self.keep_inside_work_area()
            return

        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.availableGeometry()
        x = geometry.left() + (geometry.width() - self.width()) // 2
        y = geometry.top() + (geometry.height() - self.height()) // 2
        self.move(x, y)

    def save_window_position(self):
        self.config["window_x"] = self.x()
        self.config["window_y"] = self.y()
        save_config(self.config)

    def get_work_area_for_window(self):
        screen = self.screen() or QApplication.primaryScreen()
        return screen.availableGeometry() if screen else None

    def keep_inside_work_area(self):
        geometry = self.get_work_area_for_window()
        if geometry is None:
            return
        x = max(geometry.left(), min(self.x(), geometry.right() - self.width() + 1))
        y = max(geometry.top(), min(self.y(), geometry.bottom() - self.height() + 1))
        if x != self.x() or y != self.y():
            self.move(x, y)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and self.drag_position is not None:
            new_pos = event.globalPosition().toPoint() - self.drag_position
            geometry = self.get_work_area_for_window()
            if geometry is not None:
                x = max(geometry.left(), min(new_pos.x(), geometry.right() - self.width() + 1))
                y = max(geometry.top(), min(new_pos.y(), geometry.bottom() - self.height() + 1))
                new_pos = QPoint(x, y)
            self.move(new_pos)
            self.update_note_position()
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_position = None
            self.save_window_position()
            self.update_note_position()
            event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Shadow
        for i in range(4):
            alpha = 18 - i * 4
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QColor(0, 0, 0, max(alpha, 2)))
            painter.drawRoundedRect(i, i, TIMER_WIDTH - 1 - i * 2, TIMER_HEIGHT - 1 - i * 2, self.radius, self.radius)

        # Background
        painter.setBrush(QColor(21, 25, 30, 245))
        # Border
        painter.setPen(QColor(60, 67, 75, 255))
        painter.drawRoundedRect(1, 1, TIMER_WIDTH - 3, TIMER_HEIGHT - 3, self.radius, self.radius)


# ============================================================
# Single Instance Check (Защита от повторного запуска)
# ============================================================

MUTEX_NAME = "MTimer_App_Instance_Mutex_Unique"
app_mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)

if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
    hwnd = user32.FindWindowW(None, "MTimer")
    if hwnd:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
    sys.exit(0)


# ============================================================
# Application Entry Point
# ============================================================

myappid = "mycompany.mtimer.app.1.0"
ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

app = QApplication(sys.argv)
app.setApplicationName("MTimer")
app.setApplicationDisplayName("MTimer")

if ICON_PATH.exists():
    app.setWindowIcon(QIcon(str(ICON_PATH)))

window = MTimer()
window.show()
window.keep_inside_work_area()


# ============================================================
# Topmost Enforcement
# ============================================================

def force_topmost():
    try:
        hwnd = int(window.winId())
        user32.SetWindowPos(
            hwnd,
            HWND_TOPMOST,
            0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
        )

        if window.note_visible:
            note_hwnd = int(window.note_window.winId())
            user32.SetWindowPos(
                note_hwnd,
                HWND_TOPMOST,
                0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
            )
    except Exception:
        pass


force_topmost()

topmost_timer = QTimer()
topmost_timer.setInterval(1000)
topmost_timer.timeout.connect(force_topmost)
topmost_timer.start()


# ============================================================
# Execution & Clean Shutdown
# ============================================================

exit_code = app.exec()

if app_mutex:
    kernel32.CloseHandle(app_mutex)

sys.exit(exit_code)