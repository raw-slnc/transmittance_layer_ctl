# -*- coding: utf-8 -*-

from qgis.PyQt.QtWidgets import QWidget
from qgis.PyQt.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QPainterPath,
    QFontMetricsF, QLinearGradient,
)
from qgis.PyQt.QtCore import Qt, QPointF, QRectF, pyqtSignal, QTimer
from qgis.core import QgsProject

SNAP        = 5
PT_RADIUS   = 7
MARGIN_L    = 56
MARGIN_B    = 38
MARGIN_T    = 16
MARGIN_R    = 46
SYM_SIZE    = 6
SYM_HIT     = 10
CLAMP_GAP   = 5

LAYER_COLORS = [
    '#E63946', '#2A9D8F', '#F4A261', '#A8DADC', '#E9C46A',
    '#6A4C93', '#1982C4', '#8AC926', '#FF595E', '#FFCA3A',
    '#06D6A0', '#EF476F', '#118AB2', '#FFD166', '#83C5BE',
]


class CanvasWidget(QWidget):
    """2Dキャンバス: X=レイヤー順序, Y=不透明度"""

    opacity_changed    = pyqtSignal(str, int)
    order_changed      = pyqtSignal(list)
    label_toggled      = pyqtSignal(str, bool)
    layer_selected     = pyqtSignal(str)
    visibility_toggled = pyqtSignal(str, bool)
    clamp_changed      = pyqtSignal(bool, int, int)  # (enabled, min, max)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(280, 260)
        self.setMouseTracking(True)

        self._layer_ids = []
        self._data      = {}
        self._n_slots   = 20
        self._sel       = None
        self._sel_type  = None
        self._drag      = None
        self._hover     = None

        self._label_pos = SNAP
        self._drag_sym  = None

        self._clamp_max     = 100
        self._clamp_min     = 0
        self._clamp_enabled = False

        self._exclusive_mode = False

        self._label_owner        = None   # △ のオーナー layer_id
        self._indicators_visible = True   # △ の表示/操作を有効化

        self._drag_owns_label = False


        self.setFocusPolicy(Qt.StrongFocus)

    # ------------------------------------------------------------------ #
    #  Internal helpers
    # ------------------------------------------------------------------ #

    def _layer(self, lid):
        return QgsProject.instance().mapLayer(lid)

    def _label_layer(self):
        for lid in self._layer_ids:
            if lid in self._data and self._data[lid]['slot'] == self._label_pos:
                return lid
        return None

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def set_layers(self, layers):
        self._layer_ids = [l.id() for l in layers]

        n = len(layers)
        for i, layer in enumerate(layers):
            lid = layer.id()
            t    = i / (n - 1) if n > 1 else 0.5
            diag = max(0, min(100, round(t * 100 / SNAP) * SNAP))
            old  = self._data.get(lid, {})
            self._data[lid] = {
                'slot'   : old.get('slot',    diag),
                'opacity': old.get('opacity', 60),
                'color'  : QColor(LAYER_COLORS[i % len(LAYER_COLORS)]),
                'visible': old.get('visible', True),
            }

        active = set(self._layer_ids)
        self._data = {k: v for k, v in self._data.items() if k in active}
        if self._sel not in active:
            self._sel = None
        self.update()

    def refresh_opacities(self):
        for lid in self._layer_ids:
            layer = self._layer(lid)
            if layer and lid in self._data:
                op = max(0, round(layer.opacity() * 100 / SNAP) * SNAP)
                self._data[lid]['opacity'] = op
        self.update()

    # ------------------------------------------------------------------ #
    #  座標変換
    # ------------------------------------------------------------------ #

    def _dw(self):
        return self.width()  - MARGIN_L - MARGIN_R

    def _dh(self):
        return self.height() - MARGIN_T - MARGIN_B

    def _to_screen(self, slot, opacity):
        sx = MARGIN_L + slot / (self._n_slots * SNAP) * self._dw()
        sy = MARGIN_T + (100 - opacity) / 100 * self._dh()
        return QPointF(sx, sy)

    def _to_data(self, sx, sy):
        x_raw = (sx - MARGIN_L) / self._dw() * (self._n_slots * SNAP)
        y_raw = 100 - (sy - MARGIN_T) / self._dh() * 100
        slot  = max(0, min(self._n_slots * SNAP, round(x_raw / SNAP) * SNAP))
        op    = max(0, min(100, round(y_raw / SNAP) * SNAP))
        return slot, op

    def _screen_to_label_pos(self, sx):
        x_raw = (sx - MARGIN_L) / self._dw() * (self._n_slots * SNAP)
        return max(0, min(self._n_slots * SNAP, round(x_raw / SNAP) * SNAP))

    def _screen_to_clamp_pos(self, sy):
        y_raw = 100 - (sy - MARGIN_T) / self._dh() * 100
        return max(0, min(100, round(y_raw / SNAP) * SNAP))

    # ------------------------------------------------------------------ #
    #  描画
    # ------------------------------------------------------------------ #

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self._draw_background(p)
        self._draw_grid(p)
        self._draw_axes(p)
        self._draw_axis_numbers(p)
        for lid in self._layer_ids:
            if lid in self._data:
                self._draw_mountain(p, lid)
        for lid in self._layer_ids:
            layer = self._layer(lid)
            if layer is None or lid not in self._data:
                continue
            self._draw_layer(p, lid, layer.name())
        self._draw_selected_symbols(p)
        p.end()

    def _draw_mountain(self, p, lid):
        d = self._data[lid]
        if d['opacity'] == 60:
            return
        apex       = self._to_screen(d['slot'], d['opacity'])
        base_y_val = MARGIN_T + (100 - 60) / 100 * self._dh()
        base_left  = QPointF(MARGIN_L,              base_y_val)
        base_right = QPointF(MARGIN_L + self._dw(), base_y_val)
        # 左辺: 底辺で垂直立ち上がり → 頂点で水平
        # 右辺: 頂点で水平 → 底辺で垂直降下
        path = QPainterPath()
        base_y   = base_left.y()
        left_w   = apex.x() - MARGIN_L
        right_w  = MARGIN_L + self._dw() - apex.x()
        relax    = 0.09   # 頂点の緩み（0=垂直, 1=水平）
        path.moveTo(base_left)
        path.cubicTo(
            QPointF(apex.x(),               base_y),
            QPointF(apex.x() - left_w  * relax, apex.y()),
            apex,
        )
        path.cubicTo(
            QPointF(apex.x() + right_w * relax, apex.y()),
            QPointF(apex.x(),               base_y),
            base_right,
        )
        path.closeSubpath()
        col      = d['color']
        base_y   = base_left.y()
        grad     = QLinearGradient(apex.x(), apex.y(), apex.x(), base_y)
        c_top    = QColor(col)
        c_top.setAlphaF(0.23)
        c_bot    = QColor(col)
        c_bot.setAlphaF(0.0)
        grad.setColorAt(0.0, c_top)
        grad.setColorAt(1.0, c_bot)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad))
        p.drawPath(path)

    def _draw_background(self, p):
        p.fillRect(self.rect(), QColor('#1A1A2E'))

    def _draw_grid(self, p):
        p.setPen(QPen(QColor('#2A2A4A'), 1, Qt.DotLine))
        dw, dh = self._dw(), self._dh()
        for s in range(SNAP, (self._n_slots + 1) * SNAP, SNAP):
            sx = MARGIN_L + s / (self._n_slots * SNAP) * dw
            p.drawLine(QPointF(sx, MARGIN_T), QPointF(sx, MARGIN_T + dh))
        for op in range(SNAP, 105, SNAP):
            sy = MARGIN_T + (100 - op) / 100 * dh
            p.drawLine(QPointF(MARGIN_L, sy), QPointF(MARGIN_L + dw, sy))

    def _draw_axes(self, p):
        p.setPen(QPen(QColor('#6666AA'), 1))
        dw, dh = self._dw(), self._dh()
        p.drawLine(QPointF(MARGIN_L, MARGIN_T),
                   QPointF(MARGIN_L, MARGIN_T + dh))
        p.drawLine(QPointF(MARGIN_L,      MARGIN_T + dh),
                   QPointF(MARGIN_L + dw, MARGIN_T + dh))

    def _draw_axis_numbers(self, p):
        font = QFont()
        font.setPointSize(7)
        p.setFont(font)
        p.setPen(QColor('#666688'))
        dw, dh = self._dw(), self._dh()
        for s in range(10, 101, 10):
            sx = MARGIN_L + s / (self._n_slots * SNAP) * dw
            p.drawText(QRectF(sx - 12, MARGIN_T + dh + 18, 24, 14),
                       Qt.AlignCenter, str(s))
        for op in range(10, 101, 10):
            sy = MARGIN_T + (100 - op) / 100 * dh
            p.drawText(QRectF(0, sy - 7, 30, 14),
                       Qt.AlignRight | Qt.AlignVCenter, str(op))

    def _draw_layer(self, p, lid, name):
        d        = self._data[lid]
        pt       = self._to_screen(d['slot'], d['opacity'])
        col      = d['color']
        dh       = self._dh()
        dw       = self._dw()
        x_axis_y = MARGIN_T + dh

        if lid == self._sel:
            p.setPen(QPen(col.lighter(120), 1, Qt.DashLine))
            p.drawLine(QPointF(pt.x(), MARGIN_T), QPointF(pt.x(), x_axis_y))
            p.drawLine(QPointF(MARGIN_L, pt.y()), QPointF(MARGIN_L + dw, pt.y()))

        r       = PT_RADIUS + (2 if lid == self._sel else 0)
        visible = d.get('visible', True)
        p.setOpacity(1.0 if visible else 0.3)
        if lid == self._sel:
            p.setPen(QPen(QColor('white'), 2))
        elif lid == self._hover:
            p.setPen(QPen(col.lighter(160), 1.5))
        else:
            p.setPen(QPen(col.darker(160), 1))
        p.setBrush(QBrush(col if visible else QColor(80, 80, 80)))
        p.drawEllipse(pt, r, r)
        if not visible:
            p.setPen(QPen(QColor('#AAAAAA'), 1.5))
            p.drawLine(pt + QPointF(-r * 0.6, -r * 0.6), pt + QPointF(r * 0.6,  r * 0.6))
            p.drawLine(pt + QPointF( r * 0.6, -r * 0.6), pt + QPointF(-r * 0.6, r * 0.6))
        p.setOpacity(1.0)
        p.setPen(QPen(QColor('#666688'), 1))

        show_tip = lid == self._sel
        if not self._exclusive_mode:
            show_tip = show_tip or lid == self._hover
        if show_tip:
            self._draw_tooltip(p, name, pt, col)

    def _draw_selected_symbols(self, p):
        dw = self._dw()
        dh = self._dh()

        if self._indicators_visible:
            # △: _label_pos のX位置
            sx  = MARGIN_L + self._label_pos / (self._n_slots * SNAP) * dw
            lid = self._label_layer()
            col = self._data[lid]['color'] if lid else QColor('#888899')
            self._draw_triangle(p, QPointF(sx, MARGIN_T + dh), col, self._sel_type == 'tri')

        # クランプ帯域（有効時）
        if self._clamp_enabled:
            sy_max = MARGIN_T + (100 - self._clamp_max) / 100 * dh
            sy_min = MARGIN_T + (100 - self._clamp_min) / 100 * dh
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(80, 160, 255, 25)))
            p.drawRect(QRectF(MARGIN_L, sy_max, dw, sy_min - sy_max))

        # ◁ clamp_max（右Y軸・上限）
        sy_max  = MARGIN_T + (100 - self._clamp_max) / 100 * dh
        col_max = QColor('#4488FF') if self._clamp_enabled else QColor('#555577')
        self._draw_left_arrow(p, QPointF(MARGIN_L + dw, sy_max), col_max,
                              self._sel_type == 'clamp_max')

        # ◁ clamp_min（右Y軸・下限）
        sy_min  = MARGIN_T + (100 - self._clamp_min) / 100 * dh
        col_min = QColor('#44AAFF') if self._clamp_enabled else QColor('#555577')
        self._draw_left_arrow(p, QPointF(MARGIN_L + dw, sy_min), col_min,
                              self._sel_type == 'clamp_min')

    def _draw_triangle(self, p, pos, col, active):
        """△ X軸下・数値より上に配置（pos.y() = X軸ライン位置）"""
        s = SYM_SIZE
        path = QPainterPath()
        path.moveTo(pos.x(),     pos.y() + 4)
        path.lineTo(pos.x() - s, pos.y() + 4 + s * 1.6)
        path.lineTo(pos.x() + s, pos.y() + 4 + s * 1.6)
        path.closeSubpath()
        p.setPen(QPen(col.darker(140), 1))
        p.setBrush(QBrush(col if active else col.darker(220)))
        p.drawPath(path)

    def _draw_left_arrow(self, p, pos, col, active):
        """◁ 右軸外側・数値なし側（pos.x() = 右Y軸ライン位置）"""
        s = SYM_SIZE
        path = QPainterPath()
        path.moveTo(pos.x() + 6,            pos.y())
        path.lineTo(pos.x() + 6 + s * 1.6,  pos.y() - s)
        path.lineTo(pos.x() + 6 + s * 1.6,  pos.y() + s)
        path.closeSubpath()
        p.setPen(QPen(col.darker(140), 1))
        p.setBrush(QBrush(col if active else col.darker(220)))
        p.drawPath(path)

    def _draw_tooltip(self, p, text, pt, col):
        font = QFont()
        font.setPointSize(8)
        p.setFont(font)
        fm = QFontMetricsF(font)
        tw = fm.horizontalAdvance(text) + 10
        th = fm.height() + 6
        rx = max(MARGIN_L, min(self.width() - MARGIN_R - tw, pt.x() - tw / 2))
        ry = max(MARGIN_T, pt.y() - PT_RADIUS - th - 4)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(0, 0, 0, 200)))
        p.drawRoundedRect(QRectF(rx, ry, tw, th), 3, 3)
        p.setPen(col.lighter(160))
        p.drawText(QRectF(rx, ry, tw, th), Qt.AlignCenter, text)

    # ------------------------------------------------------------------ #
    #  ヒット判定
    # ------------------------------------------------------------------ #

    def _hit_point(self, pos):
        for lid in reversed(self._layer_ids):
            if lid not in self._data:
                continue
            pt = self._to_screen(self._data[lid]['slot'], self._data[lid]['opacity'])
            if (pos - pt).manhattanLength() <= PT_RADIUS + 5:
                return lid
        return None

    def _hit_x_triangle(self, pos):
        if not self._indicators_visible:
            return False
        # 先端が y_axis + 4、底辺中心が y_axis + 4 + SYM_SIZE*0.8
        y_axis = MARGIN_T + self._dh()
        sx     = MARGIN_L + self._label_pos / (self._n_slots * SNAP) * self._dw()
        return abs(pos.x() - sx) <= SYM_HIT and abs(pos.y() - (y_axis + 4 + SYM_SIZE)) <= SYM_HIT

    def _hit_clamp_max(self, pos):
        # 先端が sx+6、底辺が sx+6+SYM_SIZE*1.6、中心 sx+6+SYM_SIZE*0.8
        sx = MARGIN_L + self._dw()
        sy = MARGIN_T + (100 - self._clamp_max) / 100 * self._dh()
        return abs(pos.x() - (sx + 6 + SYM_SIZE)) <= SYM_HIT and abs(pos.y() - sy) <= SYM_HIT

    def _hit_clamp_min(self, pos):
        sx = MARGIN_L + self._dw()
        sy = MARGIN_T + (100 - self._clamp_min) / 100 * self._dh()
        return abs(pos.x() - (sx + 6 + SYM_SIZE)) <= SYM_HIT and abs(pos.y() - sy) <= SYM_HIT

    # ------------------------------------------------------------------ #
    #  label_toggled 発火ヘルパー
    # ------------------------------------------------------------------ #

    def _emit_label_change(self, old_pos, new_pos):
        old_lid = self._label_owner  # 追跡済みオーナーを使用（位置検索より確実）
        new_lid = next(
            (lid for lid in self._layer_ids
             if lid in self._data and self._data[lid]['slot'] == new_pos), None)
        if old_lid and old_lid != new_lid:
            self.label_toggled.emit(old_lid, False)
        if new_lid and new_lid != old_lid:
            self.label_toggled.emit(new_lid, True)
        self._label_owner = new_lid

    # ------------------------------------------------------------------ #
    #  マウスイベント
    # ------------------------------------------------------------------ #

    def mousePressEvent(self, event):
        pos = QPointF(event.pos())

        if event.button() == Qt.LeftButton and self._hit_x_triangle(pos):
            self._sel_type = 'tri'
            self._drag_sym = 'tri'
            self.setFocus()
            self.update()
            return

        if event.button() == Qt.LeftButton and self._hit_clamp_max(pos):
            self._sel_type = 'clamp_max'
            self._drag_sym = 'clamp_max'
            self.setFocus()
            self.update()
            return

        if event.button() == Qt.LeftButton and self._hit_clamp_min(pos):
            self._sel_type = 'clamp_min'
            self._drag_sym = 'clamp_min'
            self.setFocus()
            self.update()
            return

        lid = self._hit_point(pos)
        if lid:
            self._sel      = lid
            self._sel_type = 'point'
            self._drag     = lid
            self._did_drag = False
            self._drag_owns_label = (lid == self._label_owner)
            self.layer_selected.emit(lid)
            self.setFocus()
            self.update()
        elif event.button() == Qt.LeftButton and not self._exclusive_mode:
            self._sel      = None
            self._sel_type = None
            self.update()

    def mouseMoveEvent(self, event):
        pos = QPointF(event.pos())

        if self._drag_sym == 'tri' and (event.buttons() & Qt.LeftButton):
            new_pos = self._screen_to_label_pos(pos.x())
            if new_pos != self._label_pos:
                self._emit_label_change(self._label_pos, new_pos)
                self._label_pos = new_pos
                self.update()
            return

        if self._drag_sym == 'clamp_max' and (event.buttons() & Qt.LeftButton):
            new_val = self._screen_to_clamp_pos(pos.y())
            new_val = max(self._clamp_min + CLAMP_GAP, new_val)
            if new_val != self._clamp_max:
                self._clamp_max = new_val
                self.clamp_changed.emit(self._clamp_enabled, self._clamp_min, self._clamp_max)
                self.update()
            return

        if self._drag_sym == 'clamp_min' and (event.buttons() & Qt.LeftButton):
            new_val = self._screen_to_clamp_pos(pos.y())
            new_val = min(self._clamp_max - CLAMP_GAP, new_val)
            if new_val != self._clamp_min:
                self._clamp_min = new_val
                self.clamp_changed.emit(self._clamp_enabled, self._clamp_min, self._clamp_max)
                self.update()
            return

        new_hover = self._hit_point(pos)
        if new_hover != self._hover:
            self._hover = new_hover
            self.update()

        if self._drag and (event.buttons() & Qt.LeftButton):
            slot, op = self._to_data(pos.x(), pos.y())
            d = self._data[self._drag]
            changed = False
            if d['slot'] != slot:
                if self._drag_owns_label:
                    self._label_pos = slot
                d['slot'] = slot
                changed = True
            if d['opacity'] != op:
                d['opacity'] = op
                self.opacity_changed.emit(self._drag, op)
                changed = True
            if changed:
                self._did_drag = True
                self.update()

    def mouseReleaseEvent(self, event):
        if self._drag_sym:
            self._drag_sym = None
            return
        if self._drag:
            was_lid = self._drag
            self._drag = None
            if not self._did_drag and was_lid in self._data:
                if self._exclusive_mode:
                    self._apply_exclusive(was_lid)
                else:
                    d = self._data[was_lid]
                    d['visible'] = not d['visible']
                    self.visibility_toggled.emit(was_lid, d['visible'])
                self.update()

    # ------------------------------------------------------------------ #
    #  順序コミット
    # ------------------------------------------------------------------ #

    def _commit_order(self):
        panel_order = {lid: i for i, lid in enumerate(self._layer_ids)}
        sorted_ids = sorted(
            self._data.keys(),
            key=lambda lid: (
                self._data[lid]['slot'],
                self._data[lid]['opacity'],
                panel_order.get(lid, 0),
            )
        )
        if sorted_ids != self._layer_ids:
            self.order_changed.emit(sorted_ids)
        self.update()

    def _apply_exclusive(self, target_lid):
        for lid in self._layer_ids:
            if lid not in self._data:
                continue
            vis = (lid == target_lid)
            self._data[lid]['visible'] = vis
            self.visibility_toggled.emit(lid, vis)
        for lid in self._layer_ids:
            if lid in self._data:
                show = self._indicators_visible and (lid == target_lid)
                self.label_toggled.emit(lid, show)
        self._label_pos   = self._data[target_lid]['slot']
        self._label_owner = target_lid
        self._sel      = target_lid
        self._sel_type = 'point'
        self.layer_selected.emit(target_lid)

    # ------------------------------------------------------------------ #
    #  キーボード操作
    # ------------------------------------------------------------------ #

    def keyPressEvent(self, event):
        key = event.key()

        if self._sel_type == 'point':
            if self._sel is None or self._sel not in self._data:
                event.ignore()
                return
            d = self._data[self._sel]
            if key == Qt.Key_Up:
                d['opacity'] = min(100, d['opacity'] + SNAP)
                self.opacity_changed.emit(self._sel, d['opacity'])
                self.update()
            elif key == Qt.Key_Down:
                d['opacity'] = max(0, d['opacity'] - SNAP)
                self.opacity_changed.emit(self._sel, d['opacity'])
                self.update()
            elif key == Qt.Key_Left:
                if self._exclusive_mode:
                    ids = self._layer_ids
                    if ids and self._sel in ids:
                        new_idx = (ids.index(self._sel) - 1) % len(ids)
                        self._apply_exclusive(ids[new_idx])
                        self.update()
                else:
                    self._move_order(self._sel, -1)
            elif key == Qt.Key_Right:
                if self._exclusive_mode:
                    ids = self._layer_ids
                    if ids and self._sel in ids:
                        new_idx = (ids.index(self._sel) + 1) % len(ids)
                        self._apply_exclusive(ids[new_idx])
                        self.update()
                else:
                    self._move_order(self._sel, +1)
            else:
                event.ignore()

        elif self._sel_type == 'tri':
            if key == Qt.Key_Left:
                new_pos = max(0, self._label_pos - SNAP)
                if new_pos != self._label_pos:
                    self._emit_label_change(self._label_pos, new_pos)
                    self._label_pos = new_pos
                    self.update()
            elif key == Qt.Key_Right:
                new_pos = min(self._n_slots * SNAP, self._label_pos + SNAP)
                if new_pos != self._label_pos:
                    self._emit_label_change(self._label_pos, new_pos)
                    self._label_pos = new_pos
                    self.update()
            else:
                event.ignore()

        elif self._sel_type == 'clamp_max':
            if key == Qt.Key_Up:
                new_val = min(100, self._clamp_max + SNAP)
                if new_val != self._clamp_max:
                    self._clamp_max = new_val
                    self.clamp_changed.emit(self._clamp_enabled, self._clamp_min, self._clamp_max)
                    self.update()
            elif key == Qt.Key_Down:
                new_val = max(self._clamp_min + CLAMP_GAP, self._clamp_max - SNAP)
                if new_val != self._clamp_max:
                    self._clamp_max = new_val
                    self.clamp_changed.emit(self._clamp_enabled, self._clamp_min, self._clamp_max)
                    self.update()
            else:
                event.ignore()

        elif self._sel_type == 'clamp_min':
            if key == Qt.Key_Up:
                new_val = min(self._clamp_max - CLAMP_GAP, self._clamp_min + SNAP)
                if new_val != self._clamp_min:
                    self._clamp_min = new_val
                    self.clamp_changed.emit(self._clamp_enabled, self._clamp_min, self._clamp_max)
                    self.update()
            elif key == Qt.Key_Down:
                new_val = max(0, self._clamp_min - SNAP)
                if new_val != self._clamp_min:
                    self._clamp_min = new_val
                    self.clamp_changed.emit(self._clamp_enabled, self._clamp_min, self._clamp_max)
                    self.update()
            else:
                event.ignore()

        else:
            event.ignore()

    def _move_order(self, layer_id, direction):
        if layer_id not in self._data:
            return
        d = self._data[layer_id]
        new_slot = max(0, min(self._n_slots * SNAP, d['slot'] + direction * SNAP))
        if new_slot == d['slot']:
            return

        if d['slot'] == self._label_pos:
            self._label_pos = new_slot

        d['slot'] = new_slot

        new_ids = sorted(
            self._layer_ids,
            key=lambda lid: (self._data[lid]['slot'], self._data[lid]['opacity'])
        )
        self.order_changed.emit(new_ids)
        self.update()
