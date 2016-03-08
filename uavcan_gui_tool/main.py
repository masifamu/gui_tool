#!/usr/bin/env python3
#
# Copyright (C) 2016  UAVCAN Development Team  <uavcan.org>
#
# This software is distributed under the terms of the MIT License.
#
# Author: Pavel Kirienko <pavel.kirienko@zubax.com>
#

# Initializing logging first
import logging
import sys
import os
import time

assert sys.version[0] == '3'

logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                    format='%(asctime)s %(levelname)-8s %(name)-25s %(message)s')

logger = logging.getLogger(__name__.replace('__', ''))

for path in ('pyqtgraph', 'pyuavcan'):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), path))

# Importing other stuff once the logging has been configured
import uavcan

from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QSplitter, QAction
from PyQt5.QtGui import QIcon, QKeySequence
from PyQt5.QtCore import QTimer, Qt

from iface_configurator import run_iface_config_window
from widgets import show_error, get_icon
from widgets.node_monitor import NodeMonitorWidget
from widgets.local_node import LocalNodeWidget
from widgets.log_message_display import LogMessageDisplayWidget
from widgets.bus_monitor import BusMonitorWidget
from widgets.dynamic_node_id_allocator import DynamicNodeIDAllocatorWidget
from widgets.file_server import FileServerWidget
from widgets.node_properties import NodePropertiesWindow
from widgets.console import ConsoleManager, InternalObjectDescriptor
from widgets.subscriber import SubscriberWindow


NODE_NAME = 'org.uavcan.gui_tool'


class MainWindow(QMainWindow):
    def __init__(self, icon, node, iface_name):
        # Parent
        super(MainWindow, self).__init__()
        self.setWindowTitle('UAVCAN GUI Tool')
        self.setWindowIcon(icon)

        self._icon = icon
        self._node = node
        self._iface_name = iface_name

        self._console_manager = ConsoleManager(self._make_console_context)

        self._node_spin_timer = QTimer(self)
        self._node_spin_timer.timeout.connect(self._spin_node)
        self._node_spin_timer.setSingleShot(False)
        self._node_spin_timer.start(10)

        self._node_windows = {}  # node ID : window object

        self._node_monitor_widget = NodeMonitorWidget(self, node)
        self._node_monitor_widget.on_info_window_requested = self._show_node_window

        self._local_node_widget = LocalNodeWidget(self, node)
        self._log_message_widget = LogMessageDisplayWidget(self, node)
        self._bus_monitor_widget = BusMonitorWidget(self, node, iface_name)
        self._dynamic_node_id_allocation_widget = DynamicNodeIDAllocatorWidget(self, node,
                                                                               self._node_monitor_widget.monitor)
        self._file_server_widget = FileServerWidget(self, node)

        show_console_action = QAction(get_icon('terminal'), 'Interactive &console', self)
        show_console_action.setShortcut(QKeySequence('Ctrl+T'))
        show_console_action.setStatusTip('Open interactive console window')
        show_console_action.triggered.connect(self._show_console_window)

        new_subscriber_action = QAction(get_icon('newspaper-o'), '&Subscriber', self)
        new_subscriber_action.setShortcut(QKeySequence('Ctrl+Shift+S'))
        new_subscriber_action.setStatusTip('Open subscription tool')
        new_subscriber_action.triggered.connect(lambda: SubscriberWindow.spawn(self, self._node))

        tools_menu = self.menuBar().addMenu('&Tools')
        tools_menu.addAction(show_console_action)
        tools_menu.addAction(new_subscriber_action)

        self.statusBar().show()

        def make_vbox(*widgets, stretch_index=None):
            box = QVBoxLayout(self)
            for idx, w in enumerate(widgets):
                box.addWidget(w, 1 if idx == stretch_index else 0)
            container = QWidget(self)
            container.setLayout(box)
            container.setContentsMargins(0, 0, 0, 0)
            return container

        def make_splitter(orientation, *widgets):
            spl = QSplitter(orientation, self)
            for w in widgets:
                spl.addWidget(w)
            return spl

        self.setCentralWidget(make_splitter(Qt.Horizontal,
                                            make_splitter(Qt.Vertical,
                                                          make_vbox(self._local_node_widget,
                                                                    self._node_monitor_widget,
                                                                    stretch_index=1),
                                                          make_vbox(self._log_message_widget,
                                                                    self._file_server_widget,
                                                                    stretch_index=0)),
                                            make_splitter(Qt.Vertical,
                                                          make_vbox(self._bus_monitor_widget),
                                                          make_vbox(self._dynamic_node_id_allocation_widget))))

    def _make_console_context(self):
        default_transfer_priority = 30

        def print_yaml(obj):
            """
            Formats the argument as YAML structure using uavcan.to_yaml(), and prints the result into stdout.
            Use this function to print received UAVCAN structures.
            """
            print(uavcan.to_yaml(obj))

        def throw_if_anonymous():
            if self._node.is_anonymous:
                raise RuntimeError('Local node is configured in anonymous mode. '
                                   'You need to set the local node ID (see the main window) in order to be able '
                                   'to send transfers.')

        def request(payload, server_node_id, callback=None, priority=None, timeout=None):
            """
            Sends a service request to the specified node. This is a convenient wrapper over node.request().
            Args:
                payload:        Request payload of type CompoundValue, e.g. uavcan.protocol.GetNodeInfo.Request()
                server_node_id: Node ID of the node that will receive the request.
                callback:       Response callback. Default handler will print the response to stdout in YAML format.
                priority:       Transfer priority; defaults to a very low priority.
                timeout:        Response timeout, default is set according to the UAVCAN specification.
            """
            if isinstance(payload, uavcan.dsdl.CompoundType):
                print('Interpreting the first argument as:', payload.full_name + '.Request()')
                payload = uavcan.TYPENAMES[payload.full_name].Request()
            throw_if_anonymous()
            priority = priority or default_transfer_priority
            callback = callback or print_yaml
            return self._node.request(payload, server_node_id, callback, priority=priority, timeout=timeout)

        def broadcast(payload, priority=None, interval=None, count=None, duration=None):
            """
            Broadcasts messages, either once or periodically in the background.
            Periodic broadcasting can be configured with one or multiple termination conditions; see the arguments for
            more info. Multiple termination conditions will be joined with logical OR operation.
            Example:
                # Send one message:
                >>> broadcast(uavcan.protocol.debug.KeyValue(key='key', value=123))
                # Repeat message every 100 milliseconds for 10 seconds:
                >>> broadcast(uavcan.protocol.NodeStatus(), interval=0.1, duration=10)
                # Send 100 messages with 10 millisecond interval:
                >>> broadcast(uavcan.protocol.Panic(reason_text='42!'), interval=0.01, count=100)
            Args:
                payload:    UAVCAN message structure, e.g. uavcan.protocol.debug.KeyValue(key='key', value=123)
                priority:   Transfer priority; defaults to a very low priority.
                interval:   Broadcasting interval in seconds.
                            If specified, the message will be re-published in the background with this interval.
                            If not specified (which is default), the message will be published only once.
                count:      Stop background broadcasting when this number of messages has been broadcasted.
                            By default it is not set, meaning that the periodic broadcasting will continue indefinitely,
                            unless other termination conditions are configured.
                            Setting this value without interval is not allowed.
                duration:   Stop background broadcasting after this amount of time, in seconds.
                            By default it is not set, meaning that the periodic broadcasting will continue indefinitely,
                            unless other termination conditions are configured.
                            Setting this value without interval is not allowed.
            Returns:    If periodic broadcasting is configured, this function returns a handle that implements a method
                        'remove()', which can be called to stop the background job.
                        If no periodic broadcasting is configured, this function returns nothing.
            """
            # Validating inputs
            if isinstance(payload, uavcan.dsdl.CompoundType):
                print('Interpreting the first argument as:', payload.full_name + '()')
                payload = uavcan.TYPENAMES[payload.full_name]()

            if (interval is None) and (duration is not None or count is not None):
                raise RuntimeError('Cannot setup background broadcaster: interval is not set')

            throw_if_anonymous()

            # Business end is here
            def do_broadcast():
                self._node.broadcast(payload, priority or default_transfer_priority)

            do_broadcast()

            if interval is not None:
                num_broadcasted = 1         # The first was broadcasted before the job was launched
                if duration is None:
                    duration = 3600 * 24 * 365 * 1000       # See you in 1000 years
                deadline = time.monotonic() + duration

                def process_next():
                    nonlocal num_broadcasted
                    try:
                        do_broadcast()
                    except Exception:
                        logger.error('Automatic broadcast failed, job cancelled', exc_info=True)
                        timer_handle.remove()
                    else:
                        num_broadcasted += 1
                        if (count is not None and num_broadcasted >= count) or (time.monotonic() >= deadline):
                            logger.info('Background publisher for %r has stopped',
                                        uavcan.get_uavcan_data_type(payload).full_name)
                            timer_handle.remove()

                timer_handle = self._node.periodic(interval, process_next)
                return timer_handle

        def subscribe(uavcan_type, callback=None, count=None, duration=None, on_end=None):
            """
            Receives specified UAVCAN messages from the bus and delivers them to the callback.
            Args:
                uavcan_type:    UAVCAN message type to listen for.
                callback:       Callback will be invoked for every received message.
                                Default callback will print the response to stdout in YAML format.
                count:          Number of messages to receive before terminating the subscription.
                                Unlimited by default.
                duration:       Amount of time, in seconds, to listen for messages before terminating the subscription.
                                Unlimited by default.
                on_end:         Callable that will be invoked when the subscription is terminated.
            Returns:    Handler with method .remove(). Calling this method will terminate the subscription.
            """
            if (count is None and duration is None) and on_end is not None:
                raise RuntimeError('on_end is set, but it will never be called because the subscription has '
                                   'no termination condition')

            callback = callback or print_yaml

            def process_callback(e):
                nonlocal count
                stop_now = False
                try:
                    callback(e)
                except Exception:
                    logger.error('Unhandled exception in subscription callback for %r, subscription terminated',
                                 uavcan_type, exc_info=True)
                    stop_now = True
                else:
                    if count is not None:
                        count -= 1
                        if count <= 0:
                            stop_now = True
                if stop_now:
                    sub_handle.remove()
                    try:
                        timer_handle.remove()
                    except Exception:
                        pass
                    if on_end is not None:
                        on_end()

            def cancel_callback():
                try:
                    sub_handle.remove()
                except Exception:
                    pass
                else:
                    if on_end is not None:
                        on_end()

            sub_handle = self._node.add_handler(uavcan_type, process_callback)
            timer_handle = None
            if duration is not None:
                timer_handle = self._node.defer(duration, cancel_callback)
            return sub_handle

        return [
            InternalObjectDescriptor('can_iface_name', self._iface_name,
                                     'Name of the CAN bus interface'),
            InternalObjectDescriptor('node', self._node,
                                     'UAVCAN node instance'),
            InternalObjectDescriptor('node_monitor', self._node_monitor_widget.monitor,
                                     'Object that stores information about nodes currently available on the bus'),
            InternalObjectDescriptor('request', request,
                                     'Sends UAVCAN request transfers to other nodes'),
            InternalObjectDescriptor('broadcast', broadcast,
                                     'Broadcasts UAVCAN messages, once or periodically'),
            InternalObjectDescriptor('subscribe', subscribe,
                                     'Receives UAVCAN messages'),
            InternalObjectDescriptor('print_yaml', print_yaml,
                                     'Prints UAVCAN entities in YAML format'),
            InternalObjectDescriptor('uavcan', uavcan,
                                     'The main Pyuavcan module'),
            InternalObjectDescriptor('main_window', self,
                                     'Main window object, holds references to all business logic objects')
        ]

    def _show_console_window(self):
        try:
            self._console_manager.show_console_window(self)
        except Exception as ex:
            logger.error('Could not spawn console', exc_info=True)
            show_error('Console error', 'Could not spawn console window', ex, self)
            return

    def _show_node_window(self, node_id):
        if node_id in self._node_windows:
            self._node_windows[node_id].close()
            self._node_windows[node_id].setParent(None)
            self._node_windows[node_id].deleteLater()
            del self._node_windows[node_id]

        w = NodePropertiesWindow(self, self._node, node_id, self._file_server_widget,
                                 self._node_monitor_widget.monitor, self._dynamic_node_id_allocation_widget)
        w.show()
        self._node_windows[node_id] = w

    def _spin_node(self):
        # We're running the node in the GUI thread.
        # This is not great, but at the moment seems like other options are even worse.
        try:
            self._node.spin(0)
        except Exception as ex:
            logger.error('Node spin error: %r', ex, exc_info=True)

    def closeEvent(self, qcloseevent):
        self._console_manager.close()
        super(MainWindow, self).closeEvent(qcloseevent)


def main():
    app = QApplication(sys.argv)

    # noinspection PyBroadException
    try:
        app_icon = QIcon(os.path.join(os.path.dirname(__file__), 'icon.png'))
    except Exception:
        logger.error('Could not load icon', exc_info=True)
        app_icon = QIcon()

    while True:
        # Asking the user to specify which interface to work with
        try:
            iface, iface_kwargs = run_iface_config_window(app_icon)
            if not iface:
                exit(0)
        except Exception as ex:
            show_error('Fatal error', 'Could not list available interfaces', ex)
            exit(1)

        # Trying to start the node on the specified interface
        try:
            node_info = uavcan.protocol.GetNodeInfo.Response()
            node_info.name = NODE_NAME
            node_info.software_version.major = 1   # TODO: share with setup.py
            node_info.software_version.minor = 0

            node = uavcan.make_node(iface,
                                    node_info=node_info,
                                    mode=uavcan.protocol.NodeStatus().MODE_OPERATIONAL,
                                    **iface_kwargs)

            # Making sure the interface is alright
            node.spin(0.1)
        except Exception as ex:
            show_error('Fatal error', 'Could not initialize UAVCAN node', ex)
        else:
            break

    window = MainWindow(app_icon, node, iface)
    window.show()

    exit_code = app.exec_()

    node.close()

    exit(exit_code)


if __name__ == '__main__':
    main()
