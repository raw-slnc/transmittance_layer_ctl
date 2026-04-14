# -*- coding: utf-8 -*-

import json
import re
import sip
from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QMessageBox, QGroupBox, QApplication,
)
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.core import QgsProject

from .canvas_widget import CanvasWidget, SNAP
from . import group_manager as gm

_PRESET_SECTION = 'transmittance_layer_ctl'
_N_PRESETS      = 4


class PresetButton(QPushButton):
    """長押し=保存, 右クリック=削除, クリック=on/off"""

    LONG_PRESS_MS = 600

    def __init__(self, index, parent=None):
        super().__init__(f'Preset: {index}', parent)
        self._index      = index
        self._long_fired = False
        self._timer      = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self.LONG_PRESS_MS)
        self._timer.timeout.connect(self._on_long_press)
        self.setContextMenuPolicy(Qt.CustomContextMenu)

    def _on_long_press(self):
        self._long_fired = True

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._long_fired = False
            self._timer.start()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._timer.stop()
        super().mouseReleaseEvent(event)

    def enterEvent(self, event):
        from qgis.PyQt.QtWidgets import QToolTip
        if self.toolTip():
            QToolTip.showText(self.mapToGlobal(self.rect().bottomLeft()), self.toolTip(), self)
        super().enterEvent(event)


class TransmittancePanel(QDockWidget):

    def __init__(self, iface, parent=None):
        super().__init__('Transmittance Layer ctl', parent)
        self.iface          = iface
        self.current_group  = None
        self._active_preset = None  # 1〜3 or None
        self._positioned    = False  # 初回表示位置調整フラグ

        # ドラッグによるドッキングを無効化（格納はダブルクリックのみ）
        self.setFeatures(
            QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetClosable
        )
        self._build_ui()

    # ------------------------------------------------------------------ #
    #  UI構築
    # ------------------------------------------------------------------ #

    # ダークテーマ共通スタイルシート
    _DARK_SS = """
        QWidget {
            background: #1A1A2E;
            color: #AAAACC;
        }
        QPushButton {
            background: rgba(255, 255, 255, 18);
            border: 1px solid #2A2A4A;
            border-radius: 3px;
            color: #AAAACC;
            padding: 2px 6px;
        }
        QPushButton:hover  { background: rgba(255, 255, 255, 35); }
        QPushButton:pressed { background: rgba(255, 255, 255, 55); }
        QGroupBox {
            background: rgba(255, 255, 255, 8);
            border: 1px solid #2A2A4A;
            border-radius: 4px;
            margin-top: 6px;
            padding: 4px 4px 4px 4px;
            color: #666688;
            font-size: 9px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 6px;
        }
        QLabel {
            background: transparent;
        }
    """

    def _build_ui(self):
        container = QWidget()
        container.setStyleSheet(self._DARK_SS)
        container.setMaximumHeight(380)
        self.setWidget(container)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # グループ名ヘッダー
        self.group_label = QLabel('— No group selected —')
        self.group_label.setAlignment(Qt.AlignCenter)
        self.group_label.setStyleSheet(
            'font-weight: bold; padding: 3px; color: #AAAACC; background: transparent;'
        )
        layout.addWidget(self.group_label)

        # キャンバス
        self.canvas = CanvasWidget()
        layout.addWidget(self.canvas, stretch=1)

        # 下部ボタン行（QGroupBox）
        group_box = QGroupBox('Presets')
        btn_layout = QHBoxLayout(group_box)
        btn_layout.setSpacing(4)
        btn_layout.setContentsMargins(4, 4, 4, 4)

        self._preset_btns = []
        for i in range(1, _N_PRESETS + 1):
            btn = PresetButton(i)
            btn.setFixedHeight(26)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.clicked.connect(lambda checked, b=btn, n=i: self._on_preset_click(b, n))
            btn._timer.timeout.connect(lambda b=btn, n=i: self._on_preset_long_press(b, n))
            btn.customContextMenuRequested.connect(
                lambda pos, n=i: self._on_preset_right_click(n)
            )
            btn_layout.addWidget(btn)
            self._preset_btns.append(btn)

        btn_layout.addStretch()

        self._label_btn = QPushButton('label')
        self._label_btn.setFixedHeight(26)
        self._label_btn.setFocusPolicy(Qt.NoFocus)
        self._label_btn.clicked.connect(self._on_label_toggle)
        btn_layout.addWidget(self._label_btn)

        self._exclusive_btn = QPushButton('Exclusive Control')
        self._exclusive_btn.setFixedHeight(26)
        self._exclusive_btn.setFocusPolicy(Qt.NoFocus)
        self._exclusive_btn.clicked.connect(self._on_exclusive_toggle)
        btn_layout.addWidget(self._exclusive_btn)

        self._reset_btn = QPushButton('Reset')
        self._reset_btn.setFixedHeight(26)
        self._reset_btn.setFixedWidth(60)
        self._reset_btn.setFocusPolicy(Qt.NoFocus)
        self._reset_btn.clicked.connect(self._on_reset)
        btn_layout.addWidget(self._reset_btn)

        self._filter_btn = QPushButton('filter')
        self._filter_btn.setFixedHeight(26)
        self._filter_btn.setFixedWidth(60)
        self._filter_btn.setFocusPolicy(Qt.NoFocus)
        self._filter_btn.clicked.connect(self._on_filter_toggle)
        btn_layout.addWidget(self._filter_btn)

        layout.addWidget(group_box)

        # デベロッパー表示
        lbl_credit = QLabel('Developed by Avid Tree Work')
        lbl_credit.setStyleSheet('color: #AAAACC; font-size: 10px; background: transparent;')
        lbl_credit.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl_credit)

        # シグナル接続
        self.canvas.opacity_changed.connect(self._on_opacity)
        self.canvas.order_changed.connect(self._on_order)
        self.canvas.label_toggled.connect(self._on_label)
        self.canvas.visibility_toggled.connect(self._on_visibility)
        self.canvas.layer_selected.connect(self._on_layer_selected)
        self.canvas.clamp_changed.connect(self._on_clamp_changed)
        self.canvas.indicators_toggled.connect(self._update_label_btn_style)

        self._update_preset_btn_style()
        self._update_label_btn_style()

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def _move_to_top_right(self):
        if not self.isFloating():
            return
        main_win = self.iface.mainWindow()
        main_center = main_win.geometry().center()
        screen = next(
            (s for s in QApplication.screens() if s.geometry().contains(main_center)),
            QApplication.primaryScreen()
        )
        scr = screen.availableGeometry()
        x = scr.right()  - self.width()  - 40
        y = scr.bottom() - self.height() - 40
        self.move(x, y)

    def closeEvent(self, event):
        """パネルを閉じたときにレイヤーパネルのグループを折りたたむ"""
        group = self._valid_group()
        if group:
            group.setExpanded(False)
        super().closeEvent(event)

    def set_group(self, group_node):
        self.current_group = group_node
        self._active_preset = None
        self.group_label.setText(group_node.name())
        self._reload()
        self.show()
        self.raise_()
        self.activateWindow()
        self.canvas.setFocus()
        if not self._positioned:
            self._positioned = True
            QTimer.singleShot(0, self._move_to_top_right)
        ids = self.canvas._layer_ids
        if self.canvas._exclusive_mode:
            # EXctlがオンの場合、選択中または最初のポイントに排他適用
            sel = self.canvas._sel
            target = sel if (sel and sel in self.canvas._data) else (ids[0] if ids else None)
            if target:
                self.canvas._apply_exclusive(target)
        else:
            # 通常モード: 選択がなければ最初のポイントを選択
            if (not self.canvas._sel or self.canvas._sel not in self.canvas._data) and ids:
                self.canvas._sel      = ids[0]
                self.canvas._sel_type = 'point'
                self.canvas.layer_selected.emit(ids[0])
        self.canvas.setFocus()
        self.canvas.update()

    def _valid_group(self):
        """current_group の C++ オブジェクトが有効な場合のみ返す。削除済みなら None にリセット。"""
        if self.current_group is None:
            return None
        try:
            if sip.isdeleted(self.current_group):
                self.current_group = None
                return None
        except Exception:
            self.current_group = None
            return None
        return self.current_group

    def refresh(self):
        if self._valid_group():
            self._reload()

    # ------------------------------------------------------------------ #
    #  内部
    # ------------------------------------------------------------------ #

    def _reload(self):
        layers = gm.get_layers_in_order(self.current_group)
        self.canvas.set_layers(layers)
        for layer in layers:
            vis = gm.get_layer_visibility(self.current_group, layer.id())
            if layer.id() in self.canvas._data:
                self.canvas._data[layer.id()]['visible'] = vis
        self._apply_all_opacities()
        self.canvas.update()

    def _apply_all_opacities(self):
        """クランプ状態を反映してすべてのレイヤー透過率を再適用"""
        for lid in self.canvas._layer_ids:
            layer = QgsProject.instance().mapLayer(lid)
            if layer and lid in self.canvas._data:
                op = self.canvas._data[lid]['opacity']
                if self.canvas._clamp_enabled:
                    op = max(self.canvas._clamp_min, min(self.canvas._clamp_max, op))
                gm.set_layer_opacity(layer, op)

    # ------------------------------------------------------------------ #
    #  シグナルハンドラ
    # ------------------------------------------------------------------ #

    def _on_opacity(self, layer_id, opacity_percent):
        layer = QgsProject.instance().mapLayer(layer_id)
        if layer:
            op = opacity_percent
            if self.canvas._clamp_enabled:
                op = max(self.canvas._clamp_min, min(self.canvas._clamp_max, op))
            gm.set_layer_opacity(layer, op)

    def _on_order(self, ordered_ids):
        group = self._valid_group()
        if group:
            gm.apply_rendering_order(group, ordered_ids)
            self.canvas._layer_ids = list(ordered_ids)
            self.canvas.update()

    def _on_label(self, layer_id, enabled):
        layer = QgsProject.instance().mapLayer(layer_id)
        if layer:
            gm.set_label_enabled(layer, enabled)

    def _on_visibility(self, layer_id, visible):
        group = self._valid_group()
        if group:
            gm.set_layer_visibility(group, layer_id, visible)

    def _on_layer_selected(self, layer_id):
        layer = QgsProject.instance().mapLayer(layer_id)
        if layer:
            self.iface.setActiveLayer(layer)

    def _on_clamp_changed(self, enabled, clamp_min, clamp_max):
        if enabled:
            self._apply_all_opacities()

    def _on_label_toggle(self):
        was_visible = self.canvas._indicators_visible
        self.canvas._indicators_visible = not was_visible
        # グループ内全レイヤーを制御: ON時はオーナーのみ表示、OFF時は全て非表示
        owner = self.canvas._label_owner
        for lid in self.canvas._layer_ids:
            show = (not was_visible) and (lid == owner)
            self.canvas.label_toggled.emit(lid, show)
        self.canvas.update()
        self._update_label_btn_style()

    def _update_label_btn_style(self):
        if self.canvas._indicators_visible:
            self._label_btn.setStyleSheet('color: #4488FF; font-weight: bold;')
        else:
            self._label_btn.setStyleSheet('')

    def _on_exclusive_toggle(self):
        self.canvas._exclusive_mode = not self.canvas._exclusive_mode
        if self.canvas._exclusive_mode:
            sel = self.canvas._sel
            if sel and sel in self.canvas._data:
                self.canvas._apply_exclusive(sel)
            elif self.canvas._layer_ids:
                self.canvas._apply_exclusive(self.canvas._layer_ids[0])
            self.canvas.setFocus()
        self.canvas.update()
        self._update_exclusive_btn_style()

    def _update_exclusive_btn_style(self):
        if self.canvas._exclusive_mode:
            self._exclusive_btn.setStyleSheet('color: #4488FF; font-weight: bold;')
        else:
            self._exclusive_btn.setStyleSheet('')

    def _on_reset(self):
        ids = list(self.canvas._layer_ids)
        n   = len(ids)
        if n == 0:
            return
        for i, lid in enumerate(ids):
            if lid not in self.canvas._data:
                continue
            t     = i / (n - 1) if n > 1 else 0.5
            inner = self.canvas._n_slots * SNAP - 2 * SNAP
            diag  = SNAP + max(0, min(inner, round(t * inner / SNAP) * SNAP))
            self.canvas._data[lid]['slot']    = diag
            self.canvas._data[lid]['opacity'] = 60
            self.canvas._data[lid]['visible'] = True
            layer = QgsProject.instance().mapLayer(lid)
            if layer:
                gm.set_layer_opacity(layer, 60)
            group = self._valid_group()
            if group:
                gm.set_layer_visibility(group, lid, True)
        self.canvas.update()

    def _on_filter_toggle(self):
        self.canvas._clamp_enabled = not self.canvas._clamp_enabled
        self.canvas.update()
        self._update_filter_btn_style()
        self._apply_all_opacities()

    def _update_filter_btn_style(self):
        if self.canvas._clamp_enabled:
            self._filter_btn.setStyleSheet('color: #4488FF; font-weight: bold;')
        else:
            self._filter_btn.setStyleSheet('')

    # ------------------------------------------------------------------ #
    #  プリセット
    # ------------------------------------------------------------------ #

    def _group_key(self):
        """現在のグループ名をプロジェクトエントリキー用に正規化して返す。グループ未選択時は None。"""
        group = self._valid_group()
        if group is None:
            return None
        return re.sub(r'[^A-Za-z0-9]', '_', group.name())

    def _preset_key(self, n):
        gk = self._group_key()
        if gk is None:
            return None
        return f'preset_{gk}_{n}'

    def _load_preset_data(self, n):
        key = self._preset_key(n)
        if key is None:
            return None
        val, ok = QgsProject.instance().readEntry(_PRESET_SECTION, key)
        if not ok or not val:
            return None
        try:
            return json.loads(val)
        except Exception:
            return None

    def _save_preset_data(self, n, data):
        key = self._preset_key(n)
        if key is None:
            return
        QgsProject.instance().writeEntry(
            _PRESET_SECTION, key, json.dumps(data)
        )

    def _delete_preset_data(self, n):
        key = self._preset_key(n)
        if key is None:
            return
        QgsProject.instance().removeEntry(_PRESET_SECTION, key)

    def _current_state(self):
        layers = {}
        for lid, d in self.canvas._data.items():
            layers[lid] = {
                'opacity': d['opacity'],
                'slot'   : d['slot'],
                'visible': d['visible'],
            }
        return {
            'layers'   : layers,
            'order'    : list(self.canvas._layer_ids),
            'clamp'    : {
                'enabled': self.canvas._clamp_enabled,
                'min'    : self.canvas._clamp_min,
                'max'    : self.canvas._clamp_max,
            },
            'exclusive': self.canvas._exclusive_mode,
        }

    def _apply_state(self, data):
        # レイヤー順序（現グループにある IDのみ）
        saved_order   = data.get('order', [])
        current_ids   = set(self.canvas._data.keys())
        valid_order   = [lid for lid in saved_order if lid in current_ids]
        for lid in self.canvas._layer_ids:
            if lid not in valid_order:
                valid_order.append(lid)
        if valid_order:
            self.canvas._layer_ids = valid_order
            group = self._valid_group()
            if group:
                gm.apply_rendering_order(group, valid_order)

        # 各レイヤーの状態
        for lid, ld in data.get('layers', {}).items():
            if lid not in self.canvas._data:
                continue
            self.canvas._data[lid]['opacity'] = ld.get('opacity', 100)
            self.canvas._data[lid]['slot']    = ld.get('slot', 0)
            self.canvas._data[lid]['visible'] = ld.get('visible', True)
            group = self._valid_group()
            if group:
                gm.set_layer_visibility(
                    group, lid, ld.get('visible', True)
                )

        # クランプ
        clamp = data.get('clamp', {})
        self.canvas._clamp_enabled = clamp.get('enabled', False)
        self.canvas._clamp_min     = clamp.get('min', 0)
        self.canvas._clamp_max     = clamp.get('max', 100)
        self._update_filter_btn_style()

        # Exclusive Control
        self.canvas._exclusive_mode = data.get('exclusive', False)
        self._update_exclusive_btn_style()

        self._apply_all_opacities()
        self.canvas.update()

    def _update_preset_btn_style(self):
        for i, btn in enumerate(self._preset_btns, 1):
            has_data  = self._load_preset_data(i) is not None
            is_active = self._active_preset == i
            if is_active:
                btn.setStyleSheet('color: #4488FF; font-weight: bold;')
            elif has_data:
                btn.setStyleSheet('color: #AAAACC;')
            else:
                btn.setStyleSheet('color: #AAAACC;')
            if has_data:
                tip = 'Click: apply  |  Long-press: overwrite  |  Right-click: delete'
            else:
                tip = 'Empty — long-press to save current state'
            btn.setToolTip(tip)

    def _on_preset_click(self, btn, n):
        if btn._long_fired:
            return  # 長押しで処理済み

        data = self._load_preset_data(n)
        if data is None:
            return  # 未設定

        if self._active_preset == n:
            self._active_preset = None
        else:
            self._active_preset = n
            self._apply_state(data)

        self._update_preset_btn_style()

    def _on_preset_long_press(self, btn, n):
        reply = QMessageBox.question(
            self, 'Save Preset',
            f'Save current state to Preset {n}?',
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._save_preset_data(n, self._current_state())
            self._active_preset = n
            self._update_preset_btn_style()

    def _on_preset_right_click(self, n):
        if self._load_preset_data(n) is None:
            return
        reply = QMessageBox.question(
            self, 'Delete Preset',
            f'Delete Preset {n}?',
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._delete_preset_data(n)
            if self._active_preset == n:
                self._active_preset = None
            self._update_preset_btn_style()
