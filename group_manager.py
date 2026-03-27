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
    """グループ内のノード順序を入れ替えて描画順を制御し、順序をグループに保存する。

    setCustomLayerOrder() / setHasCustomLayerOrder(True) を使わないことで
    「Control rendering order」チェックボックスの状態を変化させない。
    ノードはクローンして挿入後に元を削除するため、レイヤーはプロジェクトに残る。
    """
    # 順序をグループのカスタムプロパティに保存（プロジェクト保存時に永続化）
    group.setCustomProperty(PROP_ORDER, json.dumps(ordered_layer_ids))

    root = QgsProject.instance().layerTreeRoot()
    had_custom_order = root.hasCustomLayerOrder()

    # QGISレイヤツリーではインデックス0が最前面（Top）になる。
    # ordered_layer_ids は [背面 -> 前面] の順なので逆順にしてツリー上部から配置する。
    target_order = list(reversed(ordered_layer_ids))

    for i, lid in enumerate(target_order):
        node = group.findLayer(lid)
        if not node or node.parent() != group:
            continue
        if group.children().index(node) != i:
            cloned = node.clone()
            group.insertChildNode(i, cloned)
            group.removeChildNode(node)

    # ノード移動で「Control rendering order」が意図せずONになるのを防ぐ
    if root.hasCustomLayerOrder() != had_custom_order:
        root.setHasCustomLayerOrder(had_custom_order)


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
