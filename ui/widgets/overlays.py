from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import (
    Qt, pyqtSignal, QPropertyAnimation, QEasingCurve, pyqtProperty, QRect, QPoint, QPointF, QRectF, QTimer
)
from PyQt6.QtGui import (
    QColor, QFont, QFontMetrics, QPainter, QBrush, QPen, QLinearGradient, QConicalGradient, QPainterPath, QPixmap
)
from ui.icons import get_icon, get_mdi_font, Icons
from core.utils import SYSTEM_FONT
from core.temperature_utils import format_temperature
from ui.widgets.dashboard_button_painter import DashboardButtonPainter
from ui.utils.glass_effect import draw_frosted_pill

# ── Shared Overlay Animation Constants ──────────────────────────────
MORPH_OPEN_DURATION   = 400                          # ms – expand from button
MORPH_OPEN_EASING     = QEasingCurve.Type.OutCubic
MORPH_CLOSE_DURATION  = 400                          # ms – shrink back to button
MORPH_CLOSE_EASING    = QEasingCurve.Type.InOutCubic
CLOSE_FADE_EXPONENT   = 0.5                          # painter opacity = progress ** this
CLOSE_FADE_START      = 0.35                          # start fading when progress drops below this
BORDER_SPIN_DURATION  = 1300                         # ms – rainbow/aurora border animation
BORDER_SPIN_EASING    = QEasingCurve.Type.InOutQuad
CONTENT_FADE_DURATION = 300                          # ms – content fade-in after open
CONTENT_FADE_EASING   = QEasingCurve.Type.OutQuad
OVERLAY_CORNER_RADIUS = 12                           # px – rounded rect radius
# ────────────────────────────────────────────────────────────────────


class BaseOverlay(QWidget):
    """
    Shared animation, border drawing, and color logic for all overlays.

    Provides: morph animation, border spin animation, content fade animation,
    luminance-based text color, and common paint helpers.
    Subclasses implement start_morph() and paintEvent().
    """
    finished      = pyqtSignal()
    morph_changed = pyqtSignal(float)   # 0.0 – 1.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.raise_()
        self.hide()

        self._text       = ""
        self._color      = QColor("#FFD700")
        self._base_color = QColor("#2d2d2d")

        # ── Morph animation ──
        self._morph_progress = 0.0
        self.anim = QPropertyAnimation(self, b"morph_progress")
        self.anim.setDuration(MORPH_OPEN_DURATION)
        self.anim.setEasingCurve(MORPH_OPEN_EASING)
        self.anim.finished.connect(self.on_anim_finished)

        # ── Border spin animation ──
        self._border_progress = 0.0
        self.anim_border = QPropertyAnimation(self, b"border_progress")
        self.anim_border.setDuration(BORDER_SPIN_DURATION)
        self.anim_border.setEasingCurve(BORDER_SPIN_EASING)

        # ── Content fade animation ──
        self._content_opacity = 0.0
        self.content_anim = QPropertyAnimation(self, b"content_opacity")
        self.content_anim.setDuration(CONTENT_FADE_DURATION)
        self.content_anim.setEasingCurve(CONTENT_FADE_EASING)
        self.content_anim.setStartValue(0.0)
        self.content_anim.setEndValue(1.0)

        self._border_effect = 'Rainbow'
        self._is_closing    = False
        self._start_geom    = QRect()
        self._target_geom   = QRect()

    # ── Color helpers ──

    def _is_light_bg(self):
        c = self._base_color
        lum = 0.2126 * c.red() + 0.7152 * c.green() + 0.0722 * c.blue()
        return lum > 140

    def _fg_color(self, alpha=255):
        if self._is_light_bg():
            return QColor(0, 0, 0, alpha)
        return QColor(255, 255, 255, alpha)

    # ── Qt properties ──

    def get_morph_progress(self):
        return self._morph_progress

    def set_morph_progress(self, val):
        self._morph_progress = val
        self.morph_changed.emit(val)
        current_rect = QRect(
            int(self._start_geom.x() + (self._target_geom.x() - self._start_geom.x()) * val),
            int(self._start_geom.y() + (self._target_geom.y() - self._start_geom.y()) * val),
            int(self._start_geom.width()  + (self._target_geom.width()  - self._start_geom.width())  * val),
            int(self._start_geom.height() + (self._target_geom.height() - self._start_geom.height()) * val),
        )
        self.setGeometry(current_rect)
        self.update()

    morph_progress = pyqtProperty(float, get_morph_progress, set_morph_progress)

    def get_border_progress(self):
        return self._border_progress

    def set_border_progress(self, val):
        self._border_progress = val
        self.update()

    border_progress = pyqtProperty(float, get_border_progress, set_border_progress)

    def get_content_opacity(self):
        return self._content_opacity

    def set_content_opacity(self, val):
        self._content_opacity = val
        self.update()

    content_opacity = pyqtProperty(float, get_content_opacity, set_content_opacity)

    # ── Lifecycle ──

    def _start_morph_animations(self, start_geo: QRect, target_geo: QRect):
        """Start morph + border animations. Call from subclass start_morph()."""
        self._start_geom      = start_geo
        self._target_geom     = target_geo
        self._is_closing      = False
        self._content_opacity = 0.0

        self.content_anim.stop()

        self.setGeometry(start_geo)
        self.show()
        self.raise_()
        self.activateWindow()

        self.anim.stop()
        self.anim.setDuration(MORPH_OPEN_DURATION)
        self.anim.setEasingCurve(MORPH_OPEN_EASING)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.start()

        self.anim_border.stop()
        self.anim_border.setStartValue(0.0)
        self.anim_border.setEndValue(1.0)
        self.anim_border.start()

    def close_morph(self):
        self._is_closing      = True
        self._content_opacity = 0.0
        self.update()

        self.anim.stop()
        self.anim.setDuration(MORPH_CLOSE_DURATION)
        self.anim.setEasingCurve(MORPH_CLOSE_EASING)
        self.anim.setStartValue(self._morph_progress)
        self.anim.setEndValue(0.0)
        self.anim.start()

    def on_anim_finished(self):
        if self._is_closing:
            self.hide()
            self.finished.emit()
        else:
            self.content_anim.start()

    def set_border_effect(self, effect: str):
        self._border_effect = effect
        self.update()

    # ── Paint helpers ──

    def _draw_close_fade(self, painter):
        """Apply closing fade opacity. Call at the top of paintEvent."""
        if self._is_closing and self._morph_progress < CLOSE_FADE_START:
            t = self._morph_progress / CLOSE_FADE_START
            painter.setOpacity(t ** CLOSE_FADE_EXPONENT)

    def _draw_background(self, painter, rect):
        painter.setBrush(self._base_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, OVERLAY_CORNER_RADIUS, OVERLAY_CORNER_RADIUS)

    def _draw_border_animation(self, painter, rect):
        if self.anim_border.state() != QPropertyAnimation.State.Running:
            return
        if self._border_effect == 'Rainbow':
            self._draw_rainbow_border(painter, rect)
        elif self._border_effect == 'Aurora Borealis':
            self._draw_aurora_border(painter, rect)
        elif self._border_effect == 'Prism Shard':
            self._draw_prism_shard_border(painter, rect)
        elif self._border_effect == 'Liquid Mercury':
            self._draw_liquid_mercury_border(painter, rect)
        painter.setOpacity(1.0)

    # ── Border drawing ──

    def _draw_rainbow_border(self, painter, rect):
        self._draw_gradient_border(painter, rect, ["#4285F4", "#EA4335", "#FBBC05", "#34A853", "#4285F4"])

    def _draw_aurora_border(self, painter, rect):
        self._draw_gradient_border(painter, rect, ["#00C896", "#0078FF", "#8C00FF", "#0078FF", "#00C896"])

    def _draw_prism_shard_border(self, painter, rect):
        self._draw_gradient_border(painter, rect, ["#26C6DA", "#EC407A", "#FFCA28", "#CFD8DC", "#26C6DA"])

    def _draw_liquid_mercury_border(self, painter, rect):
        self._draw_gradient_border(painter, rect, ["#37474F", "#78909C", "#CFD8DC", "#ECEFF1", "#CFD8DC", "#78909C", "#37474F"])

    def _draw_gradient_border(self, painter, rect, colors):
        speed = 0.9 if self._border_effect == 'Prism Shard' else 1.5
        if self._border_effect == 'Liquid Mercury':
            speed = 1.2
        angle = self._border_progress * 360.0 * speed

        opacity = 1.0
        if self._border_progress > 0.8:
            opacity = (1.0 - self._border_progress) / 0.2
        painter.setOpacity(opacity)

        gradient = QConicalGradient(QPointF(rect.center()), angle)
        for i, color in enumerate(colors):
            gradient.setColorAt(i / (len(colors) - 1), QColor(color))

        pen = QPen(QBrush(gradient), 2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(rect).adjusted(1, 1, -1, -1), OVERLAY_CORNER_RADIUS, OVERLAY_CORNER_RADIUS)


# ─────────────────────────────────────────────────────────────────────────────


class DimmerOverlay(BaseOverlay):
    """Overlay slider that morphs from a button."""
    value_changed = pyqtSignal(int)   # 0-100

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value      = 0
        self._text       = "Dimmer"
        self._color      = QColor("#FFD700")
        self._base_color = QColor("#2d2d2d")

    def start_morph(self, start_geo: QRect, target_geo: QRect, initial_value: int, text: str,
                    color: QColor = None, base_color: QColor = None):
        self._value      = initial_value
        self._text       = text
        self._color      = color      or QColor("#FFD700")
        self._base_color = base_color or QColor("#2d2d2d")
        self._start_morph_animations(start_geo, target_geo)
        self.grabMouse()

    def close_morph(self):
        self.releaseMouse()
        super().close_morph()

    def mousePressEvent(self, event):
        event.accept()
        self.grabMouse()
        self.mouseMoveEvent(event)

    def mouseMoveEvent(self, event):
        rect = self.rect()
        if rect.width() == 0:
            return
        local_pos = self.mapFromGlobal(event.globalPosition().toPoint())
        pct = max(0.0, min(1.0, local_pos.x() / rect.width()))
        new_val = int(pct * 100)
        if new_val != self._value:
            self._value = new_val
            self.update()
            self.value_changed.emit(self._value)

    def mouseReleaseEvent(self, event):
        self.close_morph()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._draw_close_fade(painter)

        rect = self.rect()
        self._draw_background(painter, rect)

        fill_width = int(rect.width() * (self._value / 100.0))
        if fill_width > 0:
            grad = QLinearGradient(0, 0, rect.width(), 0)
            grad.setColorAt(0, self._color.darker(120))
            grad.setColorAt(1, self._color)
            painter.setBrush(grad)
            path = QPainterPath()
            path.addRoundedRect(QRectF(rect), OVERLAY_CORNER_RADIUS, OVERLAY_CORNER_RADIUS)
            painter.setClipPath(path)
            painter.drawRect(QRect(0, 0, fill_width, rect.height()))

        painter.setClipping(False)
        DashboardButtonPainter.draw_image_edge_effects(painter, QRectF(rect), is_top_clamped=False, is_light=self._is_light_bg())
        self._draw_border_animation(painter, rect)

        painter.setClipping(False)
        alpha = max(0, int(255 * self._morph_progress))

        font_label = QFont(SYSTEM_FONT, 11, QFont.Weight.DemiBold)
        font_label.setCapitalization(QFont.Capitalization.AllUppercase)
        painter.setFont(font_label)
        text_rect = rect.adjusted(16, 0, -16, 0)
        painter.setPen(self._fg_color(int(alpha * 0.7)))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._text)

        painter.setFont(QFont(SYSTEM_FONT, 20, QFont.Weight.Light))
        painter.setPen(self._fg_color(alpha))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{self._value}%")


# ─────────────────────────────────────────────────────────────────────────────


class ClimateOverlay(BaseOverlay):
    """Overlay for climate control with +/- buttons."""
    value_changed = pyqtSignal(float)   # Temperature value
    mode_changed  = pyqtSignal(str)     # HVAC mode
    fan_changed   = pyqtSignal(str)     # Fan mode

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value      = 20.0
        self._text       = "Climate"
        self._color      = QColor("#EA4335")
        self._base_color = QColor("#2d2d2d")

        self._min_temp            = 5.0
        self._max_temp            = 35.0
        self._step                = 0.5
        self._display_temp_unit   = 'C'
        self._current_hvac_mode   = 'off'
        self._current_fan_mode    = 'auto'
        self._hvac_modes          = []
        self._fan_modes           = []

        self._btn_minus       = QRect()
        self._btn_plus        = QRect()
        self._btn_close       = QRect()
        self._btn_minus_click = QRect()
        self._btn_plus_click  = QRect()
        self._mode_btns       = []
        self._fan_btns        = []

        self._press_rect  = QRect()
        self._press_scale = 1.0
        self._press_anim  = QPropertyAnimation(self, b"press_scale_prop")
        self._press_anim.finished.connect(self._on_press_anim_finished)

    def get_press_scale(self): return self._press_scale
    def set_press_scale(self, v):
        self._press_scale = v
        self.update()
    press_scale_prop = pyqtProperty(float, get_press_scale, set_press_scale)

    def _on_press_anim_finished(self):
        if self._press_scale < 1.0:
            self._press_anim.setDuration(180)
            self._press_anim.setEasingCurve(QEasingCurve.Type.OutBack)
            self._press_anim.setStartValue(self._press_scale)
            self._press_anim.setEndValue(1.0)
            self._press_anim.start()
        else:
            self._press_rect = QRect()

    def _trigger_press_anim(self, btn_rect: QRect):
        self._press_rect = btn_rect
        self._press_anim.stop()
        self._press_anim.setDuration(80)
        self._press_anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._press_anim.setStartValue(1.0)
        self._press_anim.setEndValue(0.85)
        self._press_anim.start()

    def configure_temperature_range(self, min_temp: float, max_temp: float, step: float, display_unit: str | None = None):
        self._min_temp = min_temp
        self._max_temp = max_temp
        self._step = step if step and step > 0 else 0.5
        if display_unit:
            self._display_temp_unit = display_unit

    def update_state(self, current_state: dict):
        if not current_state:
            return
        self._current_hvac_mode = current_state.get('state', 'off')
        attrs = current_state.get('attributes', {})
        self._current_fan_mode = attrs.get('fan_mode', 'auto')
        if attrs.get('hvac_modes'):
            self._hvac_modes = attrs.get('hvac_modes')
        if attrs.get('fan_modes'):
            self._fan_modes = attrs.get('fan_modes')
        self.update()

    def start_morph(self, start_geo: QRect, target_geo: QRect, initial_value: float, text: str,
                    color: QColor = None, base_color: QColor = None, current_state: dict = None):
        self._hvac_modes = ['off', 'heat', 'cool', 'auto']
        self._fan_modes  = ['auto', 'low', 'medium', 'high']
        if current_state:
            self.update_state(current_state)
        self._value      = initial_value
        self._text       = text
        self._color      = color      or QColor("#EA4335")
        self._base_color = base_color or QColor("#2d2d2d")
        self._start_morph_animations(start_geo, target_geo)

    def adjust_temp(self, delta: float):
        new_val = max(self._min_temp, min(self._max_temp, self._value + delta))
        if new_val != self._value:
            self._value = new_val
            self.update()
            self.value_changed.emit(self._value)

    def mousePressEvent(self, event):
        pos = event.pos()
        if self._btn_close.contains(pos):
            self.close_morph()
        elif self._btn_minus_click.contains(pos):
            self.adjust_temp(-self._step)
        elif self._btn_plus_click.contains(pos):
            self.adjust_temp(self._step)
        for rect_btn, mode in self._mode_btns:
            if rect_btn.contains(pos):
                self._trigger_press_anim(rect_btn)
                self._current_hvac_mode = mode
                self.mode_changed.emit(mode)
                self.update()
                return
        for rect_btn, mode in self._fan_btns:
            if rect_btn.contains(pos):
                self._trigger_press_anim(rect_btn)
                self._current_fan_mode = mode
                self.fan_changed.emit(mode)
                self.update()
                return

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._draw_close_fade(painter)

        rect = self.rect()
        self._draw_background(painter, rect)
        DashboardButtonPainter.draw_image_edge_effects(painter, QRectF(rect), is_top_clamped=False, is_light=self._is_light_bg())
        self._draw_border_animation(painter, rect)

        base_alpha = int(255 * self._morph_progress)
        alpha = int(base_alpha * self._content_opacity)
        if alpha < 10:
            return

        is_wide = rect.width() > 420
        if is_wide:
            self._draw_split_layout(painter, rect, alpha)
        else:
            self._draw_stacked_layout(painter, rect, alpha)

    def _draw_stacked_layout(self, painter, rect, alpha):
        close_size = 20
        self._btn_close = QRect(rect.width() - close_size - 12, 8, close_size, close_size)
        painter.setFont(get_mdi_font(18))
        painter.setPen(self._fg_color(int(alpha * 0.5)))
        painter.drawText(self._btn_close, Qt.AlignmentFlag.AlignCenter, get_icon('close'))

        title_rect = QRect(20, 8, rect.width() - 80, 20)
        font_title = QFont(SYSTEM_FONT, 8, QFont.Weight.Bold)
        font_title.setCapitalization(QFont.Capitalization.AllUppercase)
        painter.setFont(font_title)
        painter.setPen(self._fg_color(int(alpha * 0.4)))
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._text)

        self._draw_control_pill(painter, rect.center().x(), 48, alpha)

        if self._content_opacity > 0.01:
            self._draw_advanced_controls(painter, rect, int(alpha * self._content_opacity), start_y=90)

    def _draw_split_layout(self, painter, rect, alpha):
        close_size = 20
        self._btn_close = QRect(rect.width() - close_size - 12, 8, close_size, close_size)
        painter.setFont(get_mdi_font(18))
        painter.setPen(self._fg_color(int(alpha * 0.5)))
        painter.drawText(self._btn_close, Qt.AlignmentFlag.AlignCenter, get_icon('close'))

        title_rect = QRect(20, 8, rect.width() - 80, 20)
        font_title = QFont(SYSTEM_FONT, 8, QFont.Weight.Bold)
        font_title.setCapitalization(QFont.Capitalization.AllUppercase)
        painter.setFont(font_title)
        painter.setPen(self._fg_color(int(alpha * 0.4)))
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._text)

        mid_x = int(rect.width() * 0.40)
        painter.setPen(QPen(self._fg_color(int(alpha * 0.1)), 1))
        painter.drawLine(mid_x, 20, mid_x, rect.height() - 20)

        self._draw_control_pill(painter, mid_x // 2, rect.height() // 2 + 5, alpha)

        if self._content_opacity > 0.01:
            right_rect = QRect(mid_x, 0, rect.width() - mid_x, rect.height())
            self._draw_advanced_controls_split(painter, right_rect, int(alpha * self._content_opacity))

    def _draw_control_pill(self, painter, cx, cy, alpha):
        btn_radius = 13
        spacing    = 16

        font_val = QFont(SYSTEM_FONT, 16, QFont.Weight.Light)
        painter.setFont(font_val)
        fm = painter.fontMetrics()
        val_str = f"{self._value:.1f}".replace('.0', '')
        val_str = f"{val_str}°{self._display_temp_unit}"
        text_w  = fm.horizontalAdvance(val_str)

        inner_w  = btn_radius * 2 + spacing + text_w + 10 + spacing + btn_radius * 2
        pill_h   = 46
        pill_rect = QRect(0, 0, inner_w + 24, pill_h)
        pill_rect.moveCenter(QPoint(cx, cy))

        pill_path = QPainterPath()
        pill_path.addRoundedRect(QRectF(pill_rect), pill_h // 2, pill_h // 2)
        painter.fillPath(pill_path, QColor(0, 0, 0, int(alpha * 0.18)))
        painter.setPen(QPen(QColor(255, 255, 255, int(alpha * 0.12)), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(pill_rect), pill_h // 2, pill_h // 2)

        text_left  = cx - text_w // 2
        text_right = cx + text_w // 2

        btn_x_minus = text_left - spacing - btn_radius
        self._btn_minus_click = QRect(btn_x_minus - btn_radius, cy - btn_radius, btn_radius * 2, btn_radius * 2)
        btn_x_plus  = text_right + spacing + btn_radius
        self._btn_plus_click  = QRect(btn_x_plus - btn_radius, cy - btn_radius, btn_radius * 2, btn_radius * 2)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(66, 133, 244, int(alpha * 0.85)))
        painter.drawEllipse(QPoint(btn_x_minus, cy), btn_radius, btn_radius)

        painter.setBrush(QColor(234, 67, 53, int(alpha * 0.85)))
        painter.drawEllipse(QPoint(btn_x_plus, cy), btn_radius, btn_radius)

        painter.setFont(get_mdi_font(16))
        painter.setPen(QColor(255, 255, 255, alpha))
        painter.drawText(self._btn_minus_click, Qt.AlignmentFlag.AlignCenter, get_icon('minus'))
        painter.drawText(self._btn_plus_click,  Qt.AlignmentFlag.AlignCenter, get_icon('plus'))

        # Baseline position so text is visually centered at cy
        baseline_y = cy + (fm.ascent() - fm.descent()) / 2.0
        painter.setFont(font_val)
        painter.setPen(self._fg_color(alpha))
        painter.drawText(QPointF(text_left, baseline_y), val_str)

    def _draw_icon_pill(self, painter, btn_rect, is_active, alpha):
        path = QPainterPath()
        path.addRoundedRect(QRectF(btn_rect), 10, 10)
        if is_active:
            painter.fillPath(path, QColor(255, 255, 255, int(alpha * 0.14)))
            painter.setPen(QPen(QColor(255, 255, 255, int(alpha * 0.22)), 1))
        else:
            painter.fillPath(path, QColor(255, 255, 255, int(alpha * 0.06)))
            painter.setPen(QPen(QColor(255, 255, 255, int(alpha * 0.08)), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(btn_rect), 10, 10)

    def _draw_advanced_controls_split(self, painter, rect, alpha):
        self._mode_btns = []
        self._fan_btns  = []

        modes     = self._hvac_modes or ['off', 'heat', 'cool']
        fan_modes = self._fan_modes  or ['auto', 'low', 'high']

        margin_left = 20
        y_mode    = 45
        icon_size = 36
        spacing   = 16
        y_fan     = y_mode + icon_size + 30

        painter.setFont(QFont(SYSTEM_FONT, 8, QFont.Weight.Bold))
        painter.setPen(self._fg_color(int(alpha * 0.4)))
        painter.drawText(QRect(rect.left() + margin_left, y_mode - 25, 60, 20),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "MODE")

        start_x = rect.left() + margin_left
        mode_icons = {
            'cool': 'snowflake', 'heat': 'fire', 'off': 'power',
            'auto': 'thermostat-auto', 'dry': 'water-percent',
            'fan_only': 'fan', 'heat_cool': 'sun-snowflake-variant'
        }

        painter.setFont(get_mdi_font(22))
        for i, mode in enumerate(modes):
            x = start_x + (i * (icon_size + spacing))
            if x + icon_size > rect.right() - 10:
                break
            btn_rect = QRect(x, y_mode, icon_size, icon_size)
            self._mode_btns.append((btn_rect, mode))
            is_active = (mode == self._current_hvac_mode)
            scale = self._press_scale if btn_rect == self._press_rect else 1.0
            if scale != 1.0:
                c = btn_rect.center()
                painter.save()
                painter.translate(c.x(), c.y())
                painter.scale(scale, scale)
                painter.translate(-c.x(), -c.y())
            self._draw_icon_pill(painter, btn_rect, is_active, alpha)
            painter.setPen(self._fg_color(alpha if is_active else int(alpha * 0.4)))
            painter.setFont(get_mdi_font(22))
            painter.drawText(btn_rect, Qt.AlignmentFlag.AlignCenter, get_icon(mode_icons.get(mode, 'help-circle-outline')))
            if scale != 1.0:
                painter.restore()

        painter.setFont(QFont(SYSTEM_FONT, 8, QFont.Weight.Bold))
        painter.setPen(self._fg_color(int(alpha * 0.4)))
        painter.drawText(QRect(rect.left() + margin_left, y_fan - 25, 60, 20),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "FAN")

        fan_map = {'low': '1', 'medium': '2', 'high': '3', 'mid': '2', 'min': '1', 'max': 'Max'}

        for i, mode in enumerate(fan_modes):
            x = start_x + (i * (icon_size + spacing))
            if x + icon_size > rect.right() - 10:
                break
            btn_rect = QRect(x, y_fan, icon_size, icon_size)
            self._fan_btns.append((btn_rect, mode))
            is_active = (mode == self._current_fan_mode)
            scale = self._press_scale if btn_rect == self._press_rect else 1.0
            if scale != 1.0:
                c = btn_rect.center()
                painter.save()
                painter.translate(c.x(), c.y())
                painter.scale(scale, scale)
                painter.translate(-c.x(), -c.y())
            self._draw_icon_pill(painter, btn_rect, is_active, alpha)
            painter.setPen(self._fg_color(alpha if is_active else int(alpha * 0.4)))
            mode_lower = mode.lower()
            if mode_lower == 'auto':
                painter.setFont(get_mdi_font(22))
                painter.drawText(btn_rect, Qt.AlignmentFlag.AlignCenter, get_icon('fan-auto'))
            else:
                painter.setFont(QFont(SYSTEM_FONT, 11, QFont.Weight.Bold))
                painter.drawText(btn_rect, Qt.AlignmentFlag.AlignCenter,
                                 fan_map.get(mode_lower, mode_lower.capitalize()[:1]))
            if scale != 1.0:
                painter.restore()

    def _draw_advanced_controls(self, painter, rect, alpha, start_y=78):
        self._mode_btns = []
        self._fan_btns  = []

        modes     = self._hvac_modes or ['off', 'heat', 'cool']
        fan_modes = self._fan_modes  or ['auto', 'low', 'high']

        mode_icons = {
            'cool': 'snowflake', 'heat': 'fire', 'off': 'power',
            'auto': 'thermostat-auto', 'dry': 'water-percent',
            'fan_only': 'fan', 'heat_cool': 'sun-snowflake-variant'
        }

        icon_size   = 32
        spacing     = 12
        y_pos_1     = start_y
        label_width = 80
        avail_width = rect.width() - label_width - 20

        painter.setFont(QFont(SYSTEM_FONT, 8, QFont.Weight.Bold))
        painter.setPen(self._fg_color(int(alpha * 0.4)))
        painter.drawText(QRect(20, y_pos_1, 60, icon_size),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "MODE")

        total_items     = len(modes)
        total_icon_width = (total_items * icon_size) + ((total_items - 1) * spacing)

        if total_icon_width > avail_width:
            spacing = (avail_width - (total_items * icon_size)) / (total_items - 1) if total_items > 1 else 0
            start_x = label_width
        else:
            start_x = label_width + (avail_width - total_icon_width) / 2

        painter.setFont(get_mdi_font(20))
        for i, mode in enumerate(modes):
            x = int(start_x + (i * (icon_size + spacing)))
            btn_rect = QRect(x, y_pos_1, icon_size, icon_size)
            self._mode_btns.append((btn_rect, mode))
            is_active = (mode == self._current_hvac_mode)
            scale = self._press_scale if btn_rect == self._press_rect else 1.0
            if scale != 1.0:
                c = btn_rect.center()
                painter.save()
                painter.translate(c.x(), c.y())
                painter.scale(scale, scale)
                painter.translate(-c.x(), -c.y())
            self._draw_icon_pill(painter, btn_rect, is_active, alpha)
            painter.setPen(self._fg_color(alpha if is_active else int(alpha * 0.5)))
            painter.setFont(get_mdi_font(20))
            painter.drawText(btn_rect, Qt.AlignmentFlag.AlignCenter,
                             get_icon(mode_icons.get(mode, 'help-circle-outline')))
            if scale != 1.0:
                painter.restore()

        y_pos_2 = y_pos_1 + icon_size + 12
        fan_map = {'low': '1', 'medium': '2', 'high': '3', 'mid': '2', 'middle': '2', 'min': '1', 'max': 'Max'}

        painter.setFont(QFont(SYSTEM_FONT, 8, QFont.Weight.Bold))
        painter.setPen(self._fg_color(int(alpha * 0.4)))
        painter.drawText(QRect(20, y_pos_2, 60, icon_size),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "FAN")

        total_items      = len(fan_modes)
        total_icon_width = (total_items * icon_size) + ((total_items - 1) * spacing)

        if total_icon_width > avail_width:
            spacing_fan = (avail_width - (total_items * icon_size)) / (total_items - 1) if total_items > 1 else 0
            start_x = label_width
        else:
            spacing_fan = spacing
            start_x = label_width + (avail_width - total_icon_width) / 2

        for i, mode in enumerate(fan_modes):
            x = int(start_x + (i * (icon_size + spacing_fan)))
            btn_rect = QRect(x, y_pos_2, icon_size, icon_size)
            self._fan_btns.append((btn_rect, mode))
            is_active = (mode == self._current_fan_mode)
            scale = self._press_scale if btn_rect == self._press_rect else 1.0
            if scale != 1.0:
                c = btn_rect.center()
                painter.save()
                painter.translate(c.x(), c.y())
                painter.scale(scale, scale)
                painter.translate(-c.x(), -c.y())
            self._draw_icon_pill(painter, btn_rect, is_active, alpha)
            painter.setPen(self._fg_color(alpha if is_active else int(alpha * 0.5)))
            mode_lower = mode.lower()
            if mode_lower == 'auto':
                painter.setFont(get_mdi_font(20))
                painter.drawText(btn_rect, Qt.AlignmentFlag.AlignCenter, get_icon('fan-auto'))
            else:
                text = fan_map.get(mode_lower)
                if not text:
                    text = mode_lower.capitalize() if len(mode) > 3 else mode.upper()
                painter.setFont(QFont(SYSTEM_FONT, 12, QFont.Weight.DemiBold))
                painter.drawText(btn_rect, Qt.AlignmentFlag.AlignCenter, text)
            if scale != 1.0:
                painter.restore()


# ─────────────────────────────────────────────────────────────────────────────


class PrinterOverlay(BaseOverlay):
    """Overlay for 3D Printer telemetry and controls."""
    action_requested = pyqtSignal(str)   # 'pause', 'stop'

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text       = "3D Printer"
        self._color      = QColor("#FF6D00")
        self._base_color = QColor("#2d2d2d")

        self._state                       = "unknown"
        self._hotend_actual               = 0.0
        self._hotend_target               = 0.0
        self._bed_actual                  = 0.0
        self._bed_target                  = 0.0
        self._progress                    = 0.0
        self._time_remaining              = ""
        self._camera_pixmap               = None
        self._temperature_unit_preference = "celsius"
        self._printer_source_unit         = None

        self._btn_close = QRect()
        self._btn_pause = QRect()
        self._btn_stop  = QRect()

        self._confirm_stop_mode = False
        self._confirm_timer     = QTimer(self)
        self._confirm_timer.setSingleShot(True)
        self._confirm_timer.setInterval(3000)
        self._confirm_timer.timeout.connect(self._reset_confirm_mode)

        self.setMouseTracking(True)
        self._hover_pause = False
        self._hover_stop  = False

    def _reset_confirm_mode(self):
        self._confirm_stop_mode = False
        self.update()

    def update_state(self, current_state: dict):
        self._state = current_state.get('state', 'unknown')
        attrs = current_state.get('attributes', {})

        def safe_float(val):
            try:
                return float(val)
            except (ValueError, TypeError):
                return 0.0

        self._hotend_actual           = safe_float(attrs.get('hotend_actual', 0.0))
        self._hotend_target           = safe_float(attrs.get('hotend_target', 0.0))
        self._bed_actual              = safe_float(attrs.get('bed_actual', 0.0))
        self._bed_target              = safe_float(attrs.get('bed_target', 0.0))
        self._printer_source_unit     = attrs.get('temperature_unit')
        self._progress                = safe_float(attrs.get('progress', 0.0))
        self._time_remaining          = attrs.get('time_remaining', '')
        self.update()

    def set_camera_pixmap(self, pixmap):
        self._camera_pixmap = pixmap
        self.update()

    def set_temperature_unit_preference(self, preference: str):
        self._temperature_unit_preference = preference
        self.update()

    def start_morph(self, start_geo: QRect, target_geo: QRect, label: str,
                    color: QColor = None, base_color: QColor = None, current_state: dict = None):
        if current_state:
            self.update_state(current_state)
        self._text              = label
        self._color             = color      or QColor("#FF6D00")
        self._base_color        = base_color or QColor("#2d2d2d")
        self._confirm_stop_mode = False
        self._start_morph_animations(start_geo, target_geo)

    def mousePressEvent(self, event):
        pos = event.pos()
        if self._btn_close.contains(pos):
            self.close_morph()
        elif self._btn_pause.contains(pos):
            action = 'resume' if self._state.lower() == 'paused' else 'pause'
            self.action_requested.emit(action)
        elif self._btn_stop.contains(pos):
            if not self._confirm_stop_mode:
                self._confirm_stop_mode = True
                self._confirm_timer.start()
                self.update()
            else:
                self._confirm_stop_mode = False
                self._confirm_timer.stop()
                self.action_requested.emit('stop')
                self.close_morph()

    def mouseMoveEvent(self, event):
        pos = event.pos()
        new_hover_pause = self._btn_pause.contains(pos) if hasattr(self, '_btn_pause') else False
        new_hover_stop  = self._btn_stop.contains(pos)  if hasattr(self, '_btn_stop')  else False
        if new_hover_pause != self._hover_pause or new_hover_stop != self._hover_stop:
            self._hover_pause = new_hover_pause
            self._hover_stop  = new_hover_stop
            self.update()

    def leaveEvent(self, event):
        self._hover_pause = False
        self._hover_stop  = False
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._draw_close_fade(painter)

        rect = self.rect()
        self._draw_background(painter, rect)
        DashboardButtonPainter.draw_image_edge_effects(painter, QRectF(rect), is_top_clamped=False, is_light=self._is_light_bg())
        self._draw_border_animation(painter, rect)

        base_alpha = int(255 * self._morph_progress)
        alpha = int(base_alpha * self._content_opacity)
        if alpha < 10:
            return

        is_wide = rect.width() > rect.height() * 1.2
        if is_wide:
            self._draw_split_layout(painter, rect, alpha)
        else:
            self._draw_stacked_layout(painter, rect, alpha)

    def _draw_split_layout(self, painter, rect, alpha):
        padding = 16
        mid_x   = int(rect.width() * 0.6)

        cam_rect = QRect(padding, padding, mid_x - padding * 2, rect.height() - padding * 2)
        self._draw_camera(painter, cam_rect, alpha)

        close_size      = 20
        self._btn_close = QRect(rect.width() - close_size - padding, padding, close_size, close_size)
        painter.setFont(get_mdi_font(18))
        painter.setPen(self._fg_color(int(alpha * 0.5)))
        painter.drawText(self._btn_close, Qt.AlignmentFlag.AlignCenter, get_icon('close'))

        right_rect = QRect(mid_x, padding, rect.width() - mid_x - padding, rect.height() - padding * 2)
        self._draw_telemetry_and_controls(painter, right_rect, alpha)

    def _draw_stacked_layout(self, painter, rect, alpha):
        padding = 16
        cam_h   = int(rect.height() * 0.5)

        cam_rect = QRect(padding, padding, rect.width() - padding * 2, cam_h)
        self._draw_camera(painter, cam_rect, alpha)

        close_size      = 20
        self._btn_close = QRect(rect.width() - close_size - padding, padding, close_size, close_size)
        painter.setFont(get_mdi_font(18))
        painter.setPen(self._fg_color(int(alpha * 0.5)))
        painter.drawText(self._btn_close, Qt.AlignmentFlag.AlignCenter, get_icon('close'))

        bottom_rect = QRect(padding, cam_h + padding * 2, rect.width() - padding * 2, rect.height() - cam_h - padding * 3)
        self._draw_telemetry_and_controls(painter, bottom_rect, alpha, stacked=True)

    def _draw_camera(self, painter, rect, alpha):
        painter.setBrush(QColor(0, 0, 0, int(alpha * 0.4)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, 8, 8)

        if self._camera_pixmap and not self._camera_pixmap.isNull():
            path = QPainterPath()
            path.addRoundedRect(QRectF(rect), 8, 8)
            painter.setClipPath(path)

            scale = max(rect.width() / self._camera_pixmap.width(), rect.height() / self._camera_pixmap.height())
            pw = self._camera_pixmap.width()  * scale
            ph = self._camera_pixmap.height() * scale
            px = rect.x() + (rect.width()  - pw) / 2
            py = rect.y() + (rect.height() - ph) / 2

            painter.setOpacity(alpha / 255.0)
            painter.drawPixmap(QRectF(px, py, pw, ph), self._camera_pixmap, QRectF(self._camera_pixmap.rect()))
            painter.setOpacity(1.0)
            painter.setClipping(False)

            scaled_pixmap = self._camera_pixmap.scaled(
                int(pw), int(ph),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )
            x_off = (pw - rect.width())  / 2
            y_off = (ph - rect.height()) / 2

            painter.translate(rect.x(), rect.y())
            DashboardButtonPainter._draw_pill_label(
                painter, QRect(0, 0, rect.width(), rect.height()), f"{self._progress:.0f}%",
                background_pixmap=scaled_pixmap, x_off=x_off, y_off=y_off, position='top-right'
            )
            painter.translate(-rect.x(), -rect.y())
        else:
            painter.setPen(self._fg_color(int(alpha * 0.3)))
            painter.setFont(get_mdi_font(32))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, get_icon("video-off"))
            painter.setFont(QFont(SYSTEM_FONT, 10))
            painter.drawText(rect.adjusted(0, 40, 0, 0), Qt.AlignmentFlag.AlignCenter, "No Feed")

            painter.translate(rect.x(), rect.y())
            DashboardButtonPainter._draw_pill_label(
                painter, QRect(0, 0, rect.width(), rect.height()), f"{self._progress:.0f}%",
                background_pixmap=None, x_off=0, y_off=0, position='top-right'
            )
            painter.translate(-rect.x(), -rect.y())

    def _draw_telemetry_and_controls(self, painter, rect, alpha, stacked=False):
        y = rect.y()

        painter.setFont(QFont(SYSTEM_FONT, 12, QFont.Weight.Bold))
        painter.setPen(self._fg_color(alpha))
        painter.drawText(QRect(rect.x(), y, rect.width(), 20), Qt.AlignmentFlag.AlignLeft, self._state.upper())
        y += 32

        bar_h    = 4
        bar_rect = QRect(rect.x(), y, rect.width(), bar_h)
        painter.setBrush(self._fg_color(40))
        painter.drawRoundedRect(bar_rect, 2, 2)

        fill_w = int(rect.width() * (self._progress / 100.0))
        if fill_w > 0:
            painter.setBrush(self._color)
            painter.drawRoundedRect(QRect(rect.x(), y, fill_w, bar_h), 2, 2)

        y += 12
        painter.setFont(QFont(SYSTEM_FONT, 9))
        painter.setPen(self._fg_color(alpha))
        painter.drawText(QRect(rect.x(), y, rect.width(), 20), Qt.AlignmentFlag.AlignRight, self._time_remaining)

        btn_y = rect.bottom() - 36
        btn_w = (rect.width() - 8) // 2
        temp_y = btn_y - 36 - 12

        box_rect = QRect(rect.x(), temp_y, rect.width(), 36)
        painter.setBrush(self._fg_color(15))
        painter.setPen(QPen(self._fg_color(40), 1))
        painter.drawRoundedRect(box_rect, 6, 6)

        pause_center = rect.x() + (btn_w // 2)
        stop_center  = rect.x() + btn_w + 8 + (btn_w // 2)

        painter.setPen(self._fg_color(alpha))
        _fmt       = lambda v: format_temperature(v, self._printer_source_unit, self._temperature_unit_preference, precision=0, fallback="0")
        nozzle_val = f"{_fmt(self._hotend_actual)}/{_fmt(self._hotend_target)}"
        bed_val    = f"{_fmt(self._bed_actual)}/{_fmt(self._bed_target)}"

        fm_icon = QFontMetrics(get_mdi_font(14))
        fm_text = QFontMetrics(QFont(SYSTEM_FONT, 10, QFont.Weight.Bold))

        nozzle_w = fm_icon.horizontalAdvance(get_icon('printer-3d-nozzle')) + 6 + fm_text.horizontalAdvance(nozzle_val)
        bed_w    = fm_icon.horizontalAdvance(get_icon('square-medium'))      + 6 + fm_text.horizontalAdvance(bed_val)

        nozzle_x = max(box_rect.x() + 8,     pause_center - (nozzle_w // 2))
        bed_x    = min(box_rect.right() - 8 - bed_w, stop_center - (bed_w // 2))

        nozzle_rect = QRect(int(nozzle_x), temp_y, int(nozzle_w), 36)
        painter.setFont(get_mdi_font(14))
        painter.drawText(nozzle_rect, Qt.AlignmentFlag.AlignLeft  | Qt.AlignmentFlag.AlignVCenter, get_icon('printer-3d-nozzle'))
        painter.setFont(QFont(SYSTEM_FONT, 10, QFont.Weight.Bold))
        painter.drawText(nozzle_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, nozzle_val)

        bed_rect = QRect(int(bed_x), temp_y, int(bed_w), 36)
        painter.setFont(get_mdi_font(14))
        painter.drawText(bed_rect, Qt.AlignmentFlag.AlignLeft  | Qt.AlignmentFlag.AlignVCenter, get_icon('square-medium'))
        painter.setFont(QFont(SYSTEM_FONT, 10, QFont.Weight.Bold))
        painter.drawText(bed_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, bed_val)

        self._btn_pause = QRect(rect.x(), btn_y, btn_w, 36)
        pause_color  = self._fg_color(50) if self._hover_pause else self._fg_color(10)
        pause_border = self._fg_color(100) if self._hover_pause else self._fg_color(30)
        pause_icon   = 'play' if self._state.lower() == 'paused' else 'pause'

        painter.setBrush(pause_color)
        painter.setPen(QPen(pause_border, 1.5))
        painter.drawRoundedRect(self._btn_pause, 6, 6)
        painter.setPen(self._fg_color(alpha))
        painter.setFont(get_mdi_font(16))
        painter.drawText(self._btn_pause, Qt.AlignmentFlag.AlignCenter, get_icon(pause_icon))

        self._btn_stop = QRect(rect.x() + btn_w + 8, btn_y, btn_w, 36)

        if self._confirm_stop_mode:
            stop_color  = QColor("#D32F2F")
            stop_border = QColor(255, 100, 100, 200)
        else:
            stop_color  = self._fg_color(50) if self._hover_stop else self._fg_color(10)
            stop_border = self._fg_color(100) if self._hover_stop else self._fg_color(30)

        painter.setBrush(stop_color)
        painter.setPen(QPen(stop_border, 1.5))
        painter.drawRoundedRect(self._btn_stop, 6, 6)
        painter.setPen(self._fg_color(alpha))

        if self._confirm_stop_mode:
            painter.setFont(QFont(SYSTEM_FONT, 9, QFont.Weight.Bold))
            painter.drawText(self._btn_stop, Qt.AlignmentFlag.AlignCenter, "SURE?")
        else:
            painter.setFont(get_mdi_font(16))
            painter.drawText(self._btn_stop, Qt.AlignmentFlag.AlignCenter, get_icon('stop'))


# ─────────────────────────────────────────────────────────────────────────────


class WeatherOverlay(BaseOverlay):
    """Overlay for weather forecasts."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text       = "Weather"
        self._color      = QColor("#4285F4")
        self._base_color = QColor("#2d2d2d")

        self._current_state               = {}
        self._forecasts                   = []
        self._temperature_unit_preference = "celsius"
        self._btn_close                   = QRect()

    def update_state(self, current_state: dict):
        if not current_state:
            return
        self._current_state = current_state
        self.update()

    def set_temperature_unit_preference(self, preference: str):
        self._temperature_unit_preference = preference
        self.update()

    def start_morph(self, start_geo: QRect, target_geo: QRect, current_state: dict, forecasts: list,
                    text: str, color: QColor = None, base_color: QColor = None):
        self.update_state(current_state)
        self._forecasts  = forecasts or []
        self._text       = text
        self._color      = color      or QColor("#4285F4")
        self._base_color = base_color or QColor("#2d2d2d")
        self._start_morph_animations(start_geo, target_geo)

    def mousePressEvent(self, event):
        if self._btn_close.contains(event.pos()):
            self.close_morph()

    def _get_weather_emoji(self, state: str) -> str:
        import sys
        if sys.platform.startswith('linux'):
            mapping = {
                'clear-night': Icons.WEATHER_NIGHT, 'cloudy': Icons.WEATHER_CLOUDY,
                'fog': Icons.WEATHER_FOG, 'hail': Icons.WEATHER_HAIL,
                'lightning': Icons.WEATHER_LIGHTNING, 'lightning-rainy': Icons.WEATHER_LIGHTNING_RAINY,
                'partlycloudy': Icons.WEATHER_PARTLY_CLOUDY, 'pouring': Icons.WEATHER_POURING,
                'rainy': Icons.WEATHER_RAINY, 'snowy': Icons.WEATHER_SNOWY,
                'snowy-rainy': Icons.WEATHER_SNOWY_RAINY, 'sunny': Icons.WEATHER_SUNNY,
                'windy': Icons.WEATHER_WINDY, 'windy-variant': Icons.WEATHER_WINDY_VARIANT,
                'exceptional': Icons.ALERT_CIRCLE
            }
            return mapping.get(state, Icons.WEATHER_CLOUDY)
        else:
            mapping = {
                'clear-night': '🌙', 'cloudy': '☁️', 'fog': '🌫️',
                'hail': '🌨️', 'lightning': '🌩️', 'lightning-rainy': '⛈️',
                'partlycloudy': '⛅', 'pouring': '🌧️', 'rainy': '🌧️',
                'snowy': '❄️', 'snowy-rainy': '🌨️', 'sunny': '☀️',
                'windy': '💨', 'windy-variant': '🌬️', 'exceptional': '⚠️'
            }
            return mapping.get(state, 'Unknown')

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._draw_close_fade(painter)

        rect = self.rect()
        self._draw_background(painter, rect)
        DashboardButtonPainter.draw_image_edge_effects(painter, QRectF(rect), is_top_clamped=False, is_light=self._is_light_bg())
        self._draw_border_animation(painter, rect)

        base_alpha = int(255 * self._morph_progress)
        alpha = int(base_alpha * self._content_opacity)
        if alpha < 10:
            return

        import sys
        is_linux = sys.platform.startswith('linux')

        close_size      = 20
        self._btn_close = QRect(rect.width() - close_size - 12, 8, close_size, close_size)
        painter.setFont(get_mdi_font(18))
        painter.setPen(self._fg_color(int(alpha * 0.5)))
        painter.drawText(self._btn_close, Qt.AlignmentFlag.AlignCenter, get_icon('close'))

        title_rect = QRect(20, 8, rect.width() - 80, 20)
        font_title = QFont(SYSTEM_FONT, 8, QFont.Weight.Bold)
        font_title.setCapitalization(QFont.Capitalization.AllUppercase)
        painter.setFont(font_title)
        painter.setPen(self._fg_color(int(alpha * 0.4)))
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._text)

        mid_x = int(rect.width() * 0.3)
        painter.setPen(QPen(self._fg_color(int(alpha * 0.1)), 1))
        painter.drawLine(mid_x, 20, mid_x, rect.height() - 20)

        current_st  = self._current_state.get('state', 'unknown')
        attrs       = self._current_state.get('attributes', {})
        temp        = attrs.get('temperature', '--')
        emoji       = self._get_weather_emoji(current_st)
        source_unit = attrs.get('temperature_unit')
        temp_str    = format_temperature(temp, source_unit, self._temperature_unit_preference, precision=1)

        if is_linux:
            painter.setFont(get_mdi_font(36))
        else:
            painter.setFont(QFont(SYSTEM_FONT, 32))
        painter.setPen(self._fg_color(alpha))

        fm     = painter.fontMetrics()
        icon_h = fm.height()
        painter.drawText(QRect(0, rect.height() // 2 - icon_h // 2 - 12, mid_x, icon_h), Qt.AlignmentFlag.AlignCenter, emoji)

        painter.setFont(QFont(SYSTEM_FONT, 14, QFont.Weight.DemiBold))
        painter.drawText(QRect(0, rect.height() // 2 + 18, mid_x, 30), Qt.AlignmentFlag.AlignCenter, temp_str)

        right_rect     = QRect(mid_x, 0, rect.width() - mid_x, rect.height())
        forecast_count = len(self._forecasts)

        if forecast_count > 0:
            item_w        = 65
            avail_w       = right_rect.width() - 20
            max_items     = avail_w // item_w
            display_count = min(forecast_count, max_items)
            start_x       = right_rect.left() + (avail_w - (display_count * item_w)) // 2 + 10

            for i in range(display_count):
                f   = self._forecasts[i]
                fx  = start_x + (i * item_w)
                fy  = rect.height() // 2 - 35
                dt_str = f.get('datetime', '')
                try:
                    from datetime import datetime
                    day_str = datetime.fromisoformat(dt_str).strftime("%a")
                except Exception:
                    day_str = "-"

                f_emoji = self._get_weather_emoji(f.get('condition', 'unknown'))
                high    = format_temperature(f.get('temperature', '--'), source_unit, self._temperature_unit_preference, precision=1)
                low     = format_temperature(f.get('templow', '--'),     source_unit, self._temperature_unit_preference, precision=1, fallback='--')

                painter.setFont(QFont(SYSTEM_FONT, 9, QFont.Weight.DemiBold))
                painter.setPen(self._fg_color(int(alpha * 0.6)))
                painter.drawText(QRect(fx, fy, item_w, 15), Qt.AlignmentFlag.AlignCenter, day_str.upper())

                if is_linux:
                    painter.setFont(get_mdi_font(20))
                else:
                    painter.setFont(QFont(SYSTEM_FONT, 16))
                painter.setPen(self._fg_color(alpha))
                painter.drawText(QRect(fx, fy + 18, item_w, 30), Qt.AlignmentFlag.AlignCenter, f_emoji)

                painter.setFont(QFont(SYSTEM_FONT, 10, QFont.Weight.DemiBold))
                painter.setPen(self._fg_color(int(alpha * 0.95)))
                painter.drawText(QRect(fx, fy + 50, item_w, 16), Qt.AlignmentFlag.AlignCenter, high)

                if not str(low).startswith('--'):
                    painter.setFont(QFont(SYSTEM_FONT, 9, QFont.Weight.Medium))
                    painter.setPen(self._fg_color(int(alpha * 0.4)))
                    painter.drawText(QRect(fx, fy + 68, item_w, 16), Qt.AlignmentFlag.AlignCenter, low)


# ─────────────────────────────────────────────────────────────────────────────


class CameraOverlay(BaseOverlay):
    """Dynamic overlay for full camera view."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._camera_pixmap = None
        self._text          = "Camera"
        self._base_color    = QColor("#2d2d2d")
        self._btn_close     = QRect()

    def on_anim_finished(self):
        if self._is_closing:
            self._camera_pixmap = None
        super().on_anim_finished()

    def set_camera_pixmap(self, pixmap):
        self._camera_pixmap = pixmap
        if self.isVisible():
            self.update()

    def start_morph(self, start_geo: QRect, target_geo: QRect, text: str, base_color: QColor = None):
        self._text       = text
        self._base_color = base_color or QColor("#2d2d2d")
        self._start_morph_animations(start_geo, target_geo)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._draw_close_fade(painter)

        rect = self.rect()
        self._draw_background(painter, rect)

        bg_pix = None
        x_bg   = 0
        y_bg   = 0

        if self._camera_pixmap and not self._camera_pixmap.isNull():
            path = QPainterPath()
            path.addRoundedRect(QRectF(rect), OVERLAY_CORNER_RADIUS, OVERLAY_CORNER_RADIUS)
            painter.setClipPath(path)

            w = rect.width()
            h = rect.height()
            scaled_cam = self._camera_pixmap.scaled(
                int(w), int(h),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )
            x_off = (scaled_cam.width()  - w) / 2
            y_off = (scaled_cam.height() - h) / 2

            painter.drawPixmap(0, 0, scaled_cam, int(x_off), int(y_off), int(w), int(h))

            bg_pix = scaled_cam
            x_bg   = int(x_off)
            y_bg   = int(y_off)

        DashboardButtonPainter.draw_image_edge_effects(painter, QRectF(rect), is_top_clamped=False, is_light=self._is_light_bg())
        self._draw_border_animation(painter, rect)

        rect_int = rect.toRect() if isinstance(rect, QRectF) else rect
        alpha    = int(255 * self._morph_progress)
        if alpha < 10:
            return

        painter.setOpacity(alpha / 255.0)

        is_light = self._is_light_bg()
        pill_bg  = QColor(255, 255, 255) if is_light else QColor(30, 30, 30)
        pill_fg  = QColor(30, 30, 30)   if is_light else QColor(255, 255, 255)

        DashboardButtonPainter._draw_pill_label(
            painter, rect_int, self._text,
            background_pixmap=bg_pix, x_off=x_bg, y_off=y_bg,
            position='top-left', forced_bg_color=pill_bg, forced_text_color=pill_fg
        )

        close_size      = 28
        close_x         = rect_int.width() - close_size - 12
        close_y         = 12
        self._btn_close = QRect(close_x, close_y, close_size, close_size)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(pill_bg)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(self._btn_close), 14, 14)
        painter.restore()

        painter.setFont(get_mdi_font(18))
        painter.setPen(pill_fg)
        painter.drawText(self._btn_close, Qt.AlignmentFlag.AlignCenter, get_icon('close'))

    def mousePressEvent(self, event):
        if self._btn_close.contains(event.pos()):
            self.close_morph()


# ─────────────────────────────────────────────────────────────────────────────


class RobotOverlay(BaseOverlay):
    """
    Base class for robot device overlays (lawn mower, vacuum, etc.).

    Subclasses declare domain-specific constants:
        ACTIVE_STATES  – tuple of HA states that trigger "Pause" mode
        START_ACTION   – service action string emitted when starting
        DOCK_ACTION    – service action string emitted for dock button
        DEFAULT_LABEL  – fallback label when none is provided
    """
    ACTIVE_STATES: tuple = ()
    START_ACTION:  str   = ''
    DOCK_ACTION:   str   = ''
    DEFAULT_LABEL: str   = ''

    action_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text       = self.DEFAULT_LABEL
        self._color      = QColor("#4CAF50")
        self._base_color = QColor("#2d2d2d")

        self._state         = "unknown"
        self._battery_level = -1.0

        self._btn_close       = QRect()
        self._btn_start_pause = QRect()
        self._btn_dock        = QRect()

        self.setMouseTracking(True)
        self._hover_start_pause = False
        self._hover_dock        = False

    def update_state(self, state_dict: dict):
        self._state = state_dict.get('state', 'unknown')
        attrs = state_dict.get('attributes', {})
        try:
            self._battery_level = float(attrs.get('battery_level', -1))
        except (ValueError, TypeError):
            self._battery_level = -1.0
        self.update()

    def start_morph(self, start_geo: QRect, target_geo: QRect, label: str,
                    color: QColor = None, base_color: QColor = None, current_state: dict = None):
        if current_state:
            self.update_state(current_state)
        self._text       = label
        self._color      = color      or QColor("#4CAF50")
        self._base_color = base_color or QColor("#2d2d2d")
        self._start_morph_animations(start_geo, target_geo)

    def mousePressEvent(self, event):
        pos = event.pos()
        if self._btn_close.contains(pos):
            self.close_morph()
        elif self._btn_start_pause.contains(pos):
            if self._state in self.ACTIVE_STATES:
                self.action_requested.emit('pause')
            else:
                self.action_requested.emit(self.START_ACTION)
        elif self._btn_dock.contains(pos):
            self.action_requested.emit(self.DOCK_ACTION)

    def mouseMoveEvent(self, event):
        pos    = event.pos()
        new_sp = self._btn_start_pause.contains(pos)
        new_dk = self._btn_dock.contains(pos)
        if new_sp != self._hover_start_pause or new_dk != self._hover_dock:
            self._hover_start_pause = new_sp
            self._hover_dock        = new_dk
            self.update()

    def leaveEvent(self, event):
        self._hover_start_pause = False
        self._hover_dock        = False
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._draw_close_fade(painter)

        rect = self.rect()
        self._draw_background(painter, rect)
        DashboardButtonPainter.draw_image_edge_effects(painter, QRectF(rect), is_top_clamped=False, is_light=self._is_light_bg())
        self._draw_border_animation(painter, rect)

        base_alpha = int(255 * self._morph_progress)
        alpha      = int(base_alpha * self._content_opacity)
        if alpha < 10:
            return

        padding = 16
        fg      = self._fg_color(alpha)
        dim_fg  = self._fg_color(int(alpha * 0.5))

        close_size      = 20
        self._btn_close = QRect(rect.width() - close_size - padding, padding, close_size, close_size)
        painter.setFont(get_mdi_font(18))
        painter.setPen(dim_fg)
        painter.drawText(self._btn_close, Qt.AlignmentFlag.AlignCenter, get_icon('close'))

        state_display = self._state.replace('_', ' ').capitalize()
        painter.setFont(QFont(SYSTEM_FONT, 13, QFont.Weight.Bold))
        painter.setPen(fg)
        state_rect = QRectF(padding, padding, rect.width() - padding * 2 - close_size, 24)
        painter.drawText(state_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, state_display)

        btn_h         = 36
        gap           = 8
        pill_h        = 22
        pill_gap      = 10
        avail_w       = rect.width() - padding * 2
        btn_w         = (avail_w - gap) / 2
        total_group_h = btn_h + pill_gap + pill_h
        btn_y         = padding + 24 + 4 + (rect.height() - padding * 2 - 24 - 4 - total_group_h) / 2
        pill_y        = btn_y + btn_h + pill_gap
        pill_rect     = QRectF(padding, pill_y, avail_w, pill_h)
        pill_radius   = pill_h / 2

        is_active = self._state in self.ACTIVE_STATES
        sp_rect   = QRectF(padding, btn_y, btn_w, btn_h)
        self._btn_start_pause = sp_rect.toAlignedRect()

        sp_color = QColor(self._color)
        if self._hover_start_pause:
            sp_color = sp_color.lighter(120)
        sp_color.setAlpha(alpha)

        path_sp = QPainterPath()
        path_sp.addRoundedRect(sp_rect, OVERLAY_CORNER_RADIUS, OVERLAY_CORNER_RADIUS)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(sp_color)
        painter.drawPath(path_sp)

        sp_icon  = get_icon('pause') if is_active else get_icon('play')
        sp_label = "Pause" if is_active else "Start"
        painter.setPen(self._fg_color(alpha))
        icon_x = sp_rect.x() + 12
        painter.setFont(get_mdi_font(16))
        painter.drawText(QRectF(icon_x, sp_rect.y(), 20, btn_h),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, sp_icon)
        painter.setFont(QFont(SYSTEM_FONT, 11, QFont.Weight.DemiBold))
        painter.drawText(QRectF(icon_x + 22, sp_rect.y(), btn_w - 34, btn_h),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, sp_label)

        dk_rect  = QRectF(padding + btn_w + gap, btn_y, btn_w, btn_h)
        self._btn_dock = dk_rect.toAlignedRect()

        dk_fill  = self._fg_color(int(alpha * 0.20) if self._hover_dock else int(alpha * 0.12))
        path_dk  = QPainterPath()
        path_dk.addRoundedRect(dk_rect, OVERLAY_CORNER_RADIUS, OVERLAY_CORNER_RADIUS)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dk_fill)
        painter.drawPath(path_dk)

        painter.setPen(self._fg_color(alpha))
        icon_x2 = dk_rect.x() + 12
        painter.setFont(get_mdi_font(16))
        painter.drawText(QRectF(icon_x2, dk_rect.y(), 20, btn_h),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, get_icon('home'))
        painter.setFont(QFont(SYSTEM_FONT, 11, QFont.Weight.DemiBold))
        painter.drawText(QRectF(icon_x2 + 22, dk_rect.y(), btn_w - 34, btn_h),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "Dock")

        if self._battery_level >= 0:
            if self._battery_level > 50:
                bar_color = QColor("#34A853")
            elif self._battery_level > 20:
                bar_color = QColor("#FBBC05")
            else:
                bar_color = QColor("#EA4335")
            bar_color.setAlpha(alpha)

            pill_path = QPainterPath()
            pill_path.addRoundedRect(pill_rect, pill_radius, pill_radius)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._fg_color(int(alpha * 0.12)))
            painter.drawPath(pill_path)

            fill_w = avail_w * (self._battery_level / 100.0)
            painter.setClipPath(pill_path)
            painter.setBrush(bar_color)
            painter.drawRect(QRectF(padding, pill_y, fill_w, pill_h))
            painter.setClipping(False)

            painter.setPen(self._fg_color(alpha))
            painter.setFont(QFont(SYSTEM_FONT, 9, QFont.Weight.Bold))
            painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, f"{int(self._battery_level)}%")

        painter.end()


# ─────────────────────────────────────────────────────────────────────────────


class MowerOverlay(RobotOverlay):
    """Lawn mower control overlay."""
    ACTIVE_STATES = ('mowing', 'returning')
    START_ACTION  = 'start_mowing'
    DOCK_ACTION   = 'dock'
    DEFAULT_LABEL = 'Mower'


class VacuumOverlay(RobotOverlay):
    """Vacuum control overlay."""
    ACTIVE_STATES = ('cleaning', 'returning')
    START_ACTION  = 'start'
    DOCK_ACTION   = 'return_to_base'
    DEFAULT_LABEL = 'Vacuum'
