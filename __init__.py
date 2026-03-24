# -*- coding: utf-8 -*-


def classFactory(iface):
    from .transmittance_layer_ctl import TransmittanceLayerCtl
    return TransmittanceLayerCtl(iface)
