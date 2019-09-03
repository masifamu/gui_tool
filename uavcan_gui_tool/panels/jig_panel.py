#
# Copyright (C) 2016  UAVCAN Development Team  <uavcan.org>
#
# This software is distributed under the terms of the MIT License.
#
# Author: Siddharth Bharat Purohit <siddharthbharatpurohit@gmail.com>
#

import uavcan
import time
from functools import partial
from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout, QHeaderView, QWidget, QLabel, QInputDialog, QDialog, \
     QAbstractItemView, QSlider, QSpinBox, QDoubleSpinBox, QPlainTextEdit
from PyQt5.QtCore import QTimer, Qt, QObject
from PyQt5.QtGui import QColor
from logging import getLogger
from ..widgets import BasicTable, make_icon_button, get_icon, get_monospace_font
import random
import colorsys
__all__ = 'PANEL_NAME', 'spawn', 'get_icon'

PANEL_NAME = 'Jig Panel'


logger = getLogger(__name__)

_singleton = None

class JigMonitor(QObject):
    TIMEOUT = 2 #1s timeout
    def __init__(self, parent, node):
        super(JigMonitor, self).__init__(parent)
        self._node = node
        self._status_handle = self._node.add_handler(uavcan.thirdparty.com.hex.equipment.jig.Status, self.jig_status_callback)
        self._modules = {}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.check_for_stale)

    def jig_status_callback(self, event):
        nid = event.message.id
        self._modules[nid] = event
        self._timer.stop()
        self._timer.start(1500)
        self.check_for_stale()

    def find_all(self, predicate):
        """Returns a generator that produces a sequence of Entry objects for which the predicate returned True.
        Args:
            predicate:  A callable that returns a value coercible to bool.
        """
        for _nid, entry in self._modules.items():
            if predicate(entry):
                yield entry

    def check_for_stale(self):
        for nid, e in list(self._modules.items())[:]:
            if (e.transfer.ts_monotonic + self.TIMEOUT) < time.monotonic():
                del self._modules[nid]

    def close(self):
        self._status_handle.remove()

class JigNodeTable(BasicTable):
    COLUMNS = [
        BasicTable.Column('ID',
                          lambda e: e.status.id),
        BasicTable.Column('Heater State',
                          lambda e: uavcan.value_to_constant_name(e.status, 'heater_state'), QHeaderView.Stretch),
        BasicTable.Column('Sensor Health',
                          lambda e: e.status.sensor_health_mask),
        BasicTable.Column('Temperature',
                          lambda e: e.status.temperature),
    ]
    class Row_value:
        """docstring for Row_value"""
        def __init__(self, status, color):
            self.id = status.message.id
            self.status = status.message 
            self.color = color

    def id_to_color(self, id):
        if id not in self.row_color:
            h,s,l = random.random(), 0.5 + random.random()/2.0, 0.4 + random.random()/5.0
            self.row_color[id] = QColor.fromHslF(h,s,l)
        return self.row_color[id]

    def __init__(self, parent, node, monitor):
        super(JigNodeTable, self).__init__(parent, self.COLUMNS, font=get_monospace_font())
        self._monitor = monitor
        self._timer = QTimer(self)
        self._timer.setSingleShot(False)
        self._timer.timeout.connect(self._update)
        self._timer.start(500)
        self.setMinimumWidth(1000) 
        self.progress = {}
        self.row_color = {}

    def selectedBodyID(self):
        if len(self.selectionModel().selectedRows()) == 0:
            return None
        x = self.selectionModel().selectedRows()[0]
        return int(self.item(x.row(), 1).text(), 0)

    def _update(self):
        known_nodes = {e.message.id: e for e in self._monitor.find_all(lambda _: True)}
        displayed_nodes = set()
        rows_to_remove = []
        # Updating existing entries
        for row in range(self.rowCount()):
            nid = int(self.item(row, 0).text(), 0)
            displayed_nodes.add(nid)
            if nid not in known_nodes:
                rows_to_remove.append(row)
                self.progress.pop(nid, None)
            else:
                row_val = JigNodeTable.Row_value(known_nodes[nid], self.id_to_color(known_nodes[nid].message.id))
                self.set_row(row, row_val)

        # Removing nonexistent entries
        for row in rows_to_remove[::-1]:     # It is important to traverse from end
            logger.info('Removing row %d', row)
            self.removeRow(row)

        # Adding new entries
        def find_insertion_pos_for_node_id(target_slot_id):
            for row in range(self.rowCount()):
                slot_id = int(self.item(row, 0).text(), 0)
                if slot_id > target_slot_id:
                    return row
            return self.rowCount()
        for nid in set(known_nodes.keys()) - displayed_nodes:
            row = find_insertion_pos_for_node_id(known_nodes[nid].message.id)
            self.insertRow(row)
            self.progress[nid] = 0
            row_val = JigNodeTable.Row_value(known_nodes[nid], self.id_to_color(known_nodes[nid].message.id))
            self.set_row(row, row_val)

    def set_progress(self, nid, progress):
        try:
            self.progress[nid] = progress
        except KeyError:
            pass

class JigPanel(QDialog):
    def __init__(self, parent, node):
        super(JigPanel, self).__init__(parent)
        self.setWindowTitle('Jig Management Panel')
        self.setAttribute(Qt.WA_DeleteOnClose)              # This is required to stop background timers!
        self._node = node
        self._monitor = JigMonitor(self, node)
        self._table = JigNodeTable(self, node, self._monitor)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)

        layout = QVBoxLayout(self)
        layout.addWidget(self._table)
        self.setLayout(layout)

    def __del__(self):
        global _singleton
        _singleton = None

    def closeEvent(self, event):
        global _singleton
        _singleton = None
        self._monitor.close()
        super(JigPanel, self).closeEvent(event)


def spawn(parent, node):
    global _singleton
    if _singleton is None:
        _singleton = JigPanel(parent, node)

    _singleton.show()
    _singleton.raise_()
    _singleton.activateWindow()

    return _singleton


get_icon = partial(get_icon, 'asterisk')
