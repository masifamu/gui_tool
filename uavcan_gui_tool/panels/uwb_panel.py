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

PANEL_NAME = 'UWB Panel'


logger = getLogger(__name__)

_singleton = None

class UWBMonitor(QObject):
    TIMEOUT = 1 #1s timeout
    def __init__(self, parent, node):
        super(UWBMonitor, self).__init__(parent)
        self._node = node
        self._status_handle = self._node.add_handler(uavcan.thirdparty.com.matternet.equipment.uwb.TransceiverStatus, self.uwb_status_callback)
        self._modules = {}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.check_for_stale)

    def uwb_status_callback(self, event):
        nid = event.transfer.source_node_id
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

class UWBNodeTable(BasicTable):
    COLUMNS = [
        BasicTable.Column('NID',
                          lambda e: e.node_id),
        BasicTable.Column('UWB_BID',
                          lambda e: (hex(e.status.body_id), e.color)),
        BasicTable.Column('UWB_SID',
                          lambda e: e.status.data_slot_id),
        BasicTable.Column('Start_Rx',
                          lambda e: e.status.start_rx_rate),
        BasicTable.Column('Start_Tx',
                          lambda e: e.status.start_tx_rate),
        BasicTable.Column('Follow_Rx',
                          lambda e: e.status.follow_rx_rate),
        BasicTable.Column('Follow_Tx',
                          lambda e: e.status.follow_tx_rate),
        BasicTable.Column('DACK_Rx',
                          lambda e: e.status.dack_rx_rate),
        BasicTable.Column('Meas',
                          lambda e: e.status.meas_rate),
        BasicTable.Column('Failed_Tx',
                          lambda e: e.status.tx_failed),
        BasicTable.Column('Backoff',
                          lambda e: e.status.backoff),
        BasicTable.Column('Last_ErrCode',
                          lambda e: e.status.last_errcode),
        BasicTable.Column('P_STATE',
                          lambda e: uavcan.value_to_constant_name(e.status, 'pstate'), QHeaderView.Stretch),
        BasicTable.Column('P_REASON',
                          lambda e: uavcan.value_to_constant_name(e.status, 'preason'), QHeaderView.Stretch),
    ]
    class Row_value:
        """docstring for Row_value"""
        def __init__(self, status, progress, color):
            self.node_id = status.transfer.source_node_id
            self.status = status.message 
            self.progress = progress
            self.color = color

    def body_id_to_color(self, body_id):
        if body_id not in self.row_color:
            h,s,l = random.random(), 0.5 + random.random()/2.0, 0.4 + random.random()/5.0
            self.row_color[body_id] = QColor.fromHslF(h,s,l)
        return self.row_color[body_id]

    def __init__(self, parent, node, monitor):
        super(UWBNodeTable, self).__init__(parent, self.COLUMNS, font=get_monospace_font())
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
        known_nodes = {e.transfer.source_node_id: e for e in self._monitor.find_all(lambda _: True)}
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
                row_val = UWBNodeTable.Row_value(known_nodes[nid], self.progress[nid], self.body_id_to_color(known_nodes[nid].message.body_id))
                self.set_row(row, row_val)

        # Removing nonexistent entries
        for row in rows_to_remove[::-1]:     # It is important to traverse from end
            logger.info('Removing row %d', row)
            self.removeRow(row)

        # Adding new entries
        def find_insertion_pos_for_node_id(target_slot_id):
            for row in range(self.rowCount()):
                slot_id = int(self.item(row, 1).text(), 0) + int(self.item(row, 2).text(), 0)
                if slot_id > target_slot_id:
                    return row
            return self.rowCount()
                
        for nid in set(known_nodes.keys()) - displayed_nodes:
            row = find_insertion_pos_for_node_id(known_nodes[nid].message.body_id+known_nodes[nid].message.data_slot_id)
            self.insertRow(row)
            self.progress[nid] = 0
            row_val = UWBNodeTable.Row_value(known_nodes[nid], self.progress[nid], self.body_id_to_color(known_nodes[nid].message.body_id))
            self.set_row(row, row_val)

    def set_progress(self, nid, progress):
        try:
            self.progress[nid] = progress
        except KeyError:
            pass

class UWBPanel(QDialog):
    def __init__(self, parent, node):
        super(UWBPanel, self).__init__(parent)
        self.setWindowTitle('UWB Management Panel')
        self.setAttribute(Qt.WA_DeleteOnClose)              # This is required to stop background timers!
        self._node = node
        self._monitor = UWBMonitor(self, node)
        self._msg_viewer = QPlainTextEdit(self)
        self._msg_viewer.setReadOnly(True)
        self._msg_viewer.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._msg_viewer.setFont(get_monospace_font())
        self._msg_viewer.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._msg_viewer.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._start_cal = make_icon_button('bullseye', 'Start Antenna Calibration', self, checkable=False, text='Start Ant Cal', on_clicked=self.send_start_cal)
        self._pair = make_icon_button('retweet', 'Start Pair', self, checkable=False, text='Pair', on_clicked=self.start_pairing)
        self._unpair = make_icon_button('retweet', 'Stop Pair', self, checkable=False, text='Unpair', on_clicked=self.stop_pairing)
        self._table = UWBNodeTable(self, node, self._monitor)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._cal_progress_handle = {}

        layout = QVBoxLayout(self)
        layout.addWidget(self._table)
        layout.addWidget(self._start_cal)
        layout.addWidget(self._pair)
        layout.addWidget(self._unpair)
        layout.addWidget(QLabel('UWB Command Status:', self))
        layout.addWidget(self._msg_viewer)
        self.setLayout(layout)

        self.pair = False
        self.pairing_cmd = None
        self._pair_bcast_timer = QTimer(self)
        self._pair_bcast_timer.start(500)
        self._pair_bcast_timer.timeout.connect(self._send_pairing_cmd)


    def start_cal_response_callback(self, event):
        if event is None:
            self._msg_viewer.insertPlainText("Start Calibration Request Timed out\n")
        if event.response.ack:
            self._msg_viewer.insertPlainText("Received Start Calibration ACK from %x\n" % event.transfer.source_node_id)
        else:
            self._msg_viewer.insertPlainText("Received Start Calibration NACK from %x\n" % event.transfer.source_node_id)

    def uwb_cal_status_callback(self, event):
        self._table.set_progress(event.transfer.source_node_id, event.message.progress_pct)
        if event.message.progress_pct == 100:
            self._msg_viewer.insertPlainText("ANTENNA DELAY for Node ID %x is %d\n" % (event.message.node_id, event.message.antenna_delay))
            try:
                self._cal_progress_handle[event.transfer.source_node_id].remove()
                del self._cal_progress_handle[event.transfer.source_node_id]
            except:
                pass

    def send_start_cal(self):
        body_id = None
        self._msg_viewer.setPlainText("Sending Calibration Request\n")
        try:
            body_id = self._table.selectedBodyID()
        except ValueError:
            self._msg_viewer.insertPlainText("Select Node for which you want to start calibration, the cal will be run over the full body\n")
            return
        _golden_trx_node_id, ok = QInputDialog.getText(self, 'Body Name', 'Enter Body Name:')
        if not ok or not _golden_trx_node_id.isdigit():
            return
        if body_id is not None:
            nodes_on_body = {e.transfer.source_node_id: e for e in self._monitor.find_all(lambda x: x.message.body_id == body_id)}
            for nid in nodes_on_body:
                self._node.request(uavcan.thirdparty.com.matternet.equipment.uwb.BeginCalibrationCommand.Request(clock_trim_master_nid = 0x0, golden_trx_node_id = int(_golden_trx_node_id)), \
                    nid, self.start_cal_response_callback, timeout=1.0)
                self._cal_progress_handle[nid] = self._node.add_handler(uavcan.thirdparty.com.matternet.equipment.uwb.TransceiverCalibrationStatus, self.uwb_cal_status_callback)

    def start_pairing(self):
        try:
            body_id = self._table.selectedBodyID()
        except ValueError:
            self._msg_viewer.insertPlainText("Select Node for which you want to start calibration, the cal will be run over the full body\n")
            return
        remote_body_name, ok = QInputDialog.getText(self, 'Body Name', 'Enter Body Name:')
        self._msg_viewer.setPlainText("Trying to Pair with %s\n" % remote_body_name)
        if not ok:
            return
        if body_id is not None:
            msg = uavcan.thirdparty.com.matternet.equipment.uwb.PairingCommand()
            msg.body_id = body_id
            msg.remote_body_id = compute_body_id_from_body_name(remote_body_name)
            self.pairing_cmd = msg
            self.pair = True

    def stop_pairing(self):
        self.pair = False
    
    def _send_pairing_cmd(self):
        if self.pair and self.pairing_cmd is not None:
            self._node.broadcast(self.pairing_cmd)

    def __del__(self):
        global _singleton
        for nid, handle in self._cal_progress_handle.items():
            handle.remove()
        _singleton = None

    def closeEvent(self, event):
        global _singleton
        _singleton = None
        for nid, handle in self._cal_progress_handle.items():
            handle.remove()
        self._monitor.close()
        super(UWBPanel, self).closeEvent(event)


def spawn(parent, node):
    global _singleton
    if _singleton is None:
        _singleton = UWBPanel(parent, node)

    _singleton.show()
    _singleton.raise_()
    _singleton.activateWindow()

    return _singleton

def compute_body_id_from_body_name(string):
    FNV_1_PRIME_64 = 1099511628211
    body_id = 14695981039346656037
    uint64_max = 2 ** 64
    for c in string:
        body_id ^= ord(c)
        body_id = (body_id * FNV_1_PRIME_64) % uint64_max
    body_id = ((body_id>>56) ^ (body_id & ((1<<56)-1)))<<8
    print(body_id)
    return body_id

get_icon = partial(get_icon, 'asterisk')
