# -*- coding: utf-8 -*-

from qgis.core import (
    QgsProject,
    QgsLayerTreeGroup,
    QgsLayerTreeLayer,
    QgsLayerTreeNode,
)
from qgis.PyQt.QtWidgets import QInputDialog

import json

PROP_KEY   = 'transmittance_ctl'
PROP_ORDER = 'transmittance_order'   # 順序保存用カスタムプロパティ


def is_transmittance_group(node):
    return (
        isinstance(node, QgsLayerTreeGroup)
        and node.customProperty(PROP_KEY) == '1'
    )


def mark_group(node):
    """グループをTransmittanceグループとしてタグ付けする"""
    node.setCustomProperty(PROP_KEY, '1')


def unmark_group(node):
    node.removeCustomProperty(PROP_KEY)


def get_layer_nodes(group):
    """グループ直下のレイヤーノード一覧（描画順: 上が先）を返す"""
    return [c for c in group.children() if isinstance(c, QgsLayerTreeLayer)]


def get_layers(group):
    """グループ直下のQgsMapLayer一覧を返す"""
    result = []
    for node in get_layer_nodes(group):
        layer = node.layer()
        if layer:
            result.append(layer)
    return result


def set_layer_opacity(layer, opacity_percent):
    """不透明度を0-100%で設定"""
    layer.setOpacity(opacity_percent / 100.0)
    layer.triggerRepaint()


def set_layer_visibility(group, layer_id, visible):
    """レイヤーツリーノードの表示/非表示を切り替える"""
    for node in get_layer_nodes(group):
        if node.layer() and node.layer().id() == layer_id:
            node.setItemVisibilityChecked(visible)
            return


def get_layer_visibility(group, layer_id):
    for node in get_layer_nodes(group):
        if node.layer() and node.layer().id() == layer_id:
            return node.isVisible()
    return True


def set_label_enabled(layer, enabled):
    """ラベル表示のon/off"""
    if hasattr(layer, 'setLabelsEnabled'):
        layer.setLabelsEnabled(enabled)
        layer.triggerRepaint()


def apply_rendering_order(group, ordered_layer_ids):
    """ノードを削除せずレンダリング順序を変更し、順序をグループに保存する。

    removeChildNode はレイヤーをプロジェクトから削除してしまうため使用しない。
    代わりに QgsLayerTreeRoot.setCustomLayerOrder() でレンダリング順を制御する。
    """
    # 順序をグループのカスタムプロパティに保存（プロジェクト保存時に永続化）
    group.setCustomProperty(PROP_ORDER, json.dumps(ordered_layer_ids))

    root = QgsProject.instance().layerTreeRoot()
    group_lids = set(ordered_layer_ids)

    ordered_layers = [QgsProject.instance().mapLayer(lid)
                      for lid in ordered_layer_ids
                      if QgsProject.instance().mapLayer(lid)]

    # 現在のカスタム順序、またはデフォルト順序を取得
    current = (list(root.customLayerOrder())
               if root.hasCustomLayerOrder()
               else list(root.layerOrder()))

    # グループレイヤーの最初の出現位置にまとめて配置
    result = []
    inserted = False
    for l in current:
        if l is None:
            continue
        if l.id() in group_lids:
            if not inserted:
                result.extend(ordered_layers)
                inserted = True
        else:
            result.append(l)
    if not inserted:
        result.extend(ordered_layers)

    root.setHasCustomLayerOrder(True)
    root.setCustomLayerOrder(result)


def get_layers_in_order(group):
    """保存された順序でグループのレイヤーを返す（未保存ならツリー順）"""
    tree_layers = get_layers(group)
    saved = group.customProperty(PROP_ORDER)
    if not saved:
        return tree_layers
    try:
        saved_ids = json.loads(saved)
    except Exception:
        return tree_layers
    layer_map = {l.id(): l for l in tree_layers}
    ordered = [layer_map[lid] for lid in saved_ids if lid in layer_map]
    # 保存済みリストにない新規レイヤーを末尾に追加
    seen = set(saved_ids)
    ordered += [l for l in tree_layers if l.id() not in seen]
    return ordered


def scan_transmittance_groups(root):
    """レイヤーツリー全体からTransmittanceグループを収集"""
    result = []

    def _walk(node):
        if isinstance(node, QgsLayerTreeGroup):
            if is_transmittance_group(node):
                result.append(node)
            for child in node.children():
                _walk(child)

    for child in root.children():
        _walk(child)
    return result
