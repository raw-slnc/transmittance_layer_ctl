# -*- coding: utf-8 -*-

from qgis.PyQt.QtWidgets import QAction, QMenu
from qgis.PyQt.QtGui import QIcon, QPixmap, QPainter, QColor, QBrush, QPen
from qgis.PyQt.QtCore import Qt, QSize
from qgis.core import (
    QgsProject,
    QgsLayerTreeGroup,
    QgsLayerTreeLayer,
)
from qgis.gui import QgsLayerTreeViewIndicator

from .panel import TransmittancePanel
from . import group_manager as gm


def _make_indicator_icon():
    """インジケーター用アイコンをプログラムで生成（小さな◎）"""
    px = QPixmap(16, 16)
    px.fill(Qt.transparent)
    painter = QPainter(px)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor('#2E86AB'), 2))
    painter.setBrush(QBrush(QColor('#A8DADC')))
    painter.drawEllipse(2, 2, 11, 11)
    # 中心に小さい点
    painter.setBrush(QBrush(QColor('#2E86AB')))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(5, 5, 5, 5)
    painter.end()
    return QIcon(px)


class TransmittanceLayerCtl:

    def __init__(self, iface):
        self.iface = iface
        self.panel = None
        self.action_mark = None
        self._indicators = {}   # node -> QgsLayerTreeViewIndicator
        self._indicator_icon = None

    # ------------------------------------------------------------------
    # initGui / unload
    # ------------------------------------------------------------------

    def initGui(self):
        self._indicator_icon = _make_indicator_icon()

        # パネル（DockWidget）
        self.panel = TransmittancePanel(self.iface, self.iface.mainWindow())
        self.iface.addDockWidget(Qt.RightDockWidgetArea, self.panel)
        # 初回起動のみフローティング（以降はQGISが状態を引き継ぐ）
        from qgis.core import QgsSettings
        key = 'transmittance_layer_ctl/initialized'
        settings = QgsSettings()
        if not settings.value(key, False, type=bool):
            self.panel.setFloating(True)
            settings.setValue(key, True)
        self.panel.hide()

        # メニューアクション「選択グループをTransmittanceグループにする」
        self.action_mark = QAction(
            'Mark as Transmittance Group',
            self.iface.mainWindow()
        )
        self.action_mark.triggered.connect(self._mark_selected_group)
        self.iface.addPluginToVectorMenu('Transmittance Layer ctl', self.action_mark)

        # レイヤーツリーのコンテキストメニューに追加
        self.iface.layerTreeView().contextMenuAboutToShow.connect(
            self._on_context_menu
        )

        # プロジェクト読み込み時にインジケーター再構築
        QgsProject.instance().readProject.connect(self._refresh_indicators)
        # ツリー変更時にも再構築
        root = QgsProject.instance().layerTreeRoot()
        root.addedChildren.connect(self._on_tree_changed)
        root.removedChildren.connect(self._on_tree_changed)

        self._refresh_indicators()

    def unload(self):
        try:
            self.iface.removePluginVectorMenu('Transmittance Layer ctl', self.action_mark)
        except Exception:
            pass
        try:
            self.iface.layerTreeView().contextMenuAboutToShow.disconnect(
                self._on_context_menu
            )
        except Exception:
            pass
        try:
            QgsProject.instance().readProject.disconnect(self._refresh_indicators)
        except Exception:
            pass
        try:
            root = QgsProject.instance().layerTreeRoot()
            root.addedChildren.disconnect(self._on_tree_changed)
            root.removedChildren.disconnect(self._on_tree_changed)
        except Exception:
            pass

        self._clear_indicators()

        if self.panel:
            try:
                self.iface.removeDockWidget(self.panel)
                self.panel.deleteLater()
            except Exception:
                pass
            self.panel = None

    # ------------------------------------------------------------------
    # コンテキストメニュー
    # ------------------------------------------------------------------

    def _on_context_menu(self, menu):
        node = self.iface.layerTreeView().currentNode()
        if not isinstance(node, QgsLayerTreeGroup):
            return

        if gm.is_transmittance_group(node):
            action_open = QAction('Open Transmittance Panel', menu)
            action_open.triggered.connect(lambda: self.panel.set_group(node))
            menu.addAction(action_open)

            action_unmark = QAction('Unmark Transmittance Group', menu)
            action_unmark.triggered.connect(lambda: self._unmark_group(node))
            menu.addAction(action_unmark)
        else:
            action_mark = QAction('Mark as Transmittance Group', menu)
            action_mark.triggered.connect(lambda: self._do_mark_group(node))
            menu.addAction(action_mark)

    # ------------------------------------------------------------------
    # グループのタグ付け / 解除
    # ------------------------------------------------------------------

    def _mark_selected_group(self):
        node = self.iface.layerTreeView().currentNode()
        if not isinstance(node, QgsLayerTreeGroup):
            from qgis.PyQt.QtWidgets import QMessageBox
            QMessageBox.information(
                self.iface.mainWindow(),
                'Transmittance Layer ctl',
                'Please select a group in the Layers panel first.'
            )
            return
        self._do_mark_group(node)

    def _do_mark_group(self, node):
        gm.mark_group(node)
        self._refresh_indicators()
        self.panel.set_group(node)

    def _unmark_group(self, node):
        gm.unmark_group(node)
        self._remove_indicator(node)
        if self.panel.current_group is node:
            self.panel.hide()

    # ------------------------------------------------------------------
    # インジケーター管理
    # ------------------------------------------------------------------

    def _refresh_indicators(self):
        self._clear_indicators()
        root = QgsProject.instance().layerTreeRoot()
        for group in gm.scan_transmittance_groups(root):
            self._add_indicator(group)

    def _add_indicator(self, node):
        view = self.iface.layerTreeView()
        indicator = QgsLayerTreeViewIndicator(view)
        indicator.setIcon(self._indicator_icon)
        indicator.setToolTip('Open Transmittance Panel')
        # clicked シグナルは QModelIndex を渡すため無視し、捕捉した node を使う
        indicator.clicked.connect(
            lambda _index, n=node: self.panel.set_group(n)
        )
        view.addIndicator(node, indicator)
        self._indicators[node] = indicator

    def _remove_indicator(self, node):
        indicator = self._indicators.pop(node, None)
        if indicator:
            try:
                self.iface.layerTreeView().removeIndicator(node, indicator)
            except RuntimeError:
                pass

    def _clear_indicators(self):
        view = self.iface.layerTreeView()
        for node, indicator in list(self._indicators.items()):
            try:
                view.removeIndicator(node, indicator)
            except RuntimeError:
                pass  # ノードが既に削除済み
        self._indicators.clear()

    # ------------------------------------------------------------------
    # ツリー変更ハンドラ
    # ------------------------------------------------------------------

    def _on_tree_changed(self, parent, index_from, index_to):
        self._refresh_indicators()
