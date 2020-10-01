# -*- coding: utf-8 -*-
"""
This module is responsible for controlling any kind of scanning probe imaging for 1D and 2D
scanning.

Qudi is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Qudi is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with Qudi. If not, see <http://www.gnu.org/licenses/>.

Copyright (c) the Qudi Developers. See the COPYRIGHT.txt file at the
top-level directory of this distribution and at <https://github.com/Ulm-IQO/qudi/>
"""


import time
import copy
import datetime
import numpy as np
import matplotlib as mpl
import matplotlib.pyplot as plt
from PySide2 import QtCore

from qudi.core.module import LogicBase
from qudi.core.util.mutex import Mutex
from qudi.core.connector import Connector
from qudi.core.configoption import ConfigOption
from qudi.core.statusvariable import StatusVar
from qudi.core import qudi_slot
from qudi.core.datastorage import ImageFormat, NpyDataStorage, TextDataStorage
from qudi.core.artwork.styles.matplotlib.mpl_style import mpl_qd_style

from qudi.interface.scanning_probe_interface import ScanData


class ScanningProbeLogic(LogicBase):
    """
    This is the Logic class for 1D/2D SPM measurements.
    Scanning in this context means moving something along 1 or 2 dimensions and collecting data from
    possibly multiple sources at each position.
    """

    # declare connectors
    _scanner = Connector(name='scanner', interface='ScanningProbeInterface')

    # status vars
    _scan_ranges = StatusVar(name='scan_ranges', default=None)
    _scan_resolution = StatusVar(name='scan_resolution', default=None)
    _scan_frequency = StatusVar(name='scan_frequency', default=None)
    _scan_history = StatusVar(name='scan_history', default=list())

    # config options
    _max_history_length = ConfigOption(name='max_history_length', default=10)
    _max_scan_update_interval = ConfigOption(name='max_scan_update_interval', default=5)
    _min_scan_update_interval = ConfigOption(name='min_scan_update_interval', default=0.25)
    _position_update_interval = ConfigOption(name='position_update_interval', default=1)

    # signals
    sigScanStateChanged = QtCore.Signal(bool, tuple)
    sigScannerPositionChanged = QtCore.Signal(dict, object)
    sigScannerTargetChanged = QtCore.Signal(dict, object)
    sigScanSettingsChanged = QtCore.Signal(dict)
    sigOptimizerSettingsChanged = QtCore.Signal(dict)
    sigScanDataChanged = QtCore.Signal(object)
    sigSaveDataState = QtCore.Signal(bool)

    __sigStopTimer = QtCore.Signal()
    __sigStartTimer = QtCore.Signal()

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)

        self._thread_lock = Mutex()

        # Optimizer settings
        self._optimizer_settings = dict()
        self._optimizer_settings['settle_time'] = 0.1
        self._optimizer_settings['pixel_clock'] = 50
        self._optimizer_settings['backscan_pts'] = 20
        self._optimizer_settings['sequence'] = ('xy', 'z')
        self._optimizer_settings['axes'] = dict()
        self._optimizer_settings['axes']['x'] = {'resolution': 15, 'range': 1e-6}
        self._optimizer_settings['axes']['y'] = {'resolution': 15, 'range': 1e-6}
        self._optimizer_settings['axes']['z'] = {'resolution': 15, 'range': 1e-6}

        # Scan history
        self._curr_history_index = 0

        # others
        self.__timer = None
        self.__current_scan = None
        self.__scan_update_interval = 0
        self.__scan_stop_requested = True
        return

    def on_activate(self):
        """ Initialisation performed during activation of the module.
        """
        constr = self.scanner_constraints

        # scanner settings
        if not isinstance(self._scan_ranges, dict):
            self._scan_ranges = {ax.name: ax.value_range for ax in constr.axes.values()}
        if not isinstance(self._scan_resolution, dict):
            self._scan_resolution = {ax.name: max(ax.min_resolution, min(128, ax.max_resolution))
                                     for ax in constr.axes.values()}
        if self._scan_frequency is None:
            self._scan_frequency = min(ax.max_frequency for ax in constr.axes.values())

        self.__current_scan = None
        self.__scan_update_interval = 0

        self.__timer = QtCore.QTimer()
        self.__timer.setInterval(int(round(self._position_update_interval * 1000)))
        self.__timer.setSingleShot(True)
        self.__timer.timeout.connect(self._update_scanner_position_loop, QtCore.Qt.QueuedConnection)
        self.__sigStartTimer.connect(self.__timer.start)
        self.__sigStopTimer.connect(self.__timer.stop)
        self.__timer.start()

        self._curr_history_index = len(self._scan_history) - 1 if self._scan_history else 0
        return

    def on_deactivate(self):
        """ Reverse steps of activation
        """
        self.__timer.stop()
        self.__timer.timeout.disconnect()
        self.__sigStartTimer.disconnect()
        self.__sigStopTimer.disconnect()
        return

    @_scan_history.representer
    def __scan_history_to_dicts(self, history):
        return [data.to_dict() for data in history]

    @_scan_history.constructor
    def __scan_history_from_dicts(self, history_dicts):
        return [ScanData.from_dict(hist_dict) for hist_dict in history_dicts]

    @property
    def scan_data(self):
        with self._thread_lock:
            if self.module_state() == 'locked' or not self._scan_history:
                return self._scanner().get_scan_data()
            return self._scan_history[self._curr_history_index]

    @property
    def scanner_position(self):
        with self._thread_lock:
            return self._scanner().get_position()

    @property
    def scanner_target(self):
        with self._thread_lock:
            return self._scanner().get_target()

    @property
    def scanner_axes(self):
        return self.scanner_constraints.axes

    @property
    def scanner_channels(self):
        return self.scanner_constraints.channels

    @property
    def scanner_constraints(self):
        return self._scanner().get_constraints()

    @property
    def scan_ranges(self):
        with self._thread_lock:
            return self._scan_ranges.copy()

    @property
    def scan_resolution(self):
        with self._thread_lock:
            return self._scan_resolution.copy()

    @property
    def scan_frequency(self):
        return self._scan_frequency

    @property
    def scan_settings(self):
        with self._thread_lock:
            settings = {'range': self._scan_ranges.copy(),
                        'resolution': self._scan_resolution.copy(),
                        'frequency': self._scan_frequency}
            return settings

    @property
    def optimizer_settings(self):
        with self._thread_lock:
            return self._optimizer_settings.copy()

    @qudi_slot(dict)
    def set_scan_settings(self, settings):
        if 'range' in settings:
            self.set_scan_range(settings['range'])
        if 'resolution' in settings:
            self.set_scan_resolution(settings['resolution'])
        if 'frequency' in settings:
            self.set_scan_frequency(settings['frequency'])

    @qudi_slot(dict)
    def set_scan_range(self, ranges):
        with self._thread_lock:
            if self.module_state() == 'locked':
                self.log.warning('Scan is running. Unable to change scan ranges.')
                new_ranges = self._scan_ranges.copy()
                self.sigScanSettingsChanged.emit({'range': new_ranges})
                return new_ranges

            ax_constr = self.scanner_constraints.axes
            for ax, ax_range in ranges.items():
                if ax not in self._scan_ranges:
                    self.log.error('Unknown axis "{0}" encountered.'.format(ax))
                    new_ranges = self._scan_ranges.copy()
                    self.sigScanSettingsChanged.emit({'range': new_ranges})
                    return new_ranges

                new_range = (
                    min(ax_constr[ax].max_value, max(ax_constr[ax].min_value, ax_range[0])),
                    min(ax_constr[ax].max_value, max(ax_constr[ax].min_value, ax_range[1]))
                )
                if new_range[0] > new_range[1]:
                    new_range = (new_range[0], new_range[0])
                self._scan_ranges[ax] = new_range

            new_ranges = {ax: r for ax, r in self._scan_ranges.items() if ax in ranges}
            self.sigScanSettingsChanged.emit({'range': new_ranges})
            return new_ranges

    @qudi_slot(dict)
    def set_scan_resolution(self, resolution):
        with self._thread_lock:
            if self.module_state() == 'locked':
                self.log.warning('Scan is running. Unable to change scan resolution.')
                new_res = self._scan_resolution.copy()
                self.sigScanSettingsChanged.emit({'resolution': new_res})
                return new_res

            ax_constr = self.scanner_constraints.axes
            for ax, ax_res in resolution.items():
                if ax not in self._scan_resolution:
                    self.log.error('Unknown axis "{0}" encountered.'.format(ax))
                    new_res = self._scan_resolution.copy()
                    self.sigScanSettingsChanged.emit({'resolution': new_res})
                    return new_res

                self._scan_resolution[ax] = min(ax_constr[ax].max_resolution,
                                                max(ax_constr[ax].min_resolution, ax_res))

            new_resolution = {ax: r for ax, r in self._scan_resolution.items() if ax in resolution}
            self.sigScanSettingsChanged.emit({'resolution': new_resolution})
            return new_resolution

    @qudi_slot(dict)
    def set_scan_frequency(self, frequency):
        with self._thread_lock:
            if self.module_state() == 'locked':
                self.log.warning('Scan is running. Unable to change scan frequency.')
                self.sigScanSettingsChanged.emit({'frequency': self._scan_frequency})
                return self._scan_frequency

            frequency = float(frequency)

            # Check if frequency lies outside of maximum possible bounds
            min_freq, max_freq = np.inf, -np.inf
            for axis in self.scanner_constraints.axes.values():
                if axis.min_frequency < min_freq:
                    min_freq = axis.min_frequency
                if axis.max_frequency > max_freq:
                    max_freq = axis.max_frequency
            if min_freq <= frequency <= max_freq:
                self._scan_frequency = frequency
            else:
                self.log.error('Scan frequency to set outside of maximum allowed bounds [{0}, {1}] '
                               'for all axes'.format(min_freq, max_freq))

            self.sigScanSettingsChanged.emit({'frequency': self._scan_frequency})
            return self._scan_frequency

    @qudi_slot(dict)
    def set_optimizer_settings(self, settings):
        # ToDo: Implement
        # if 'axes' in settings:
        #     for axis, axis_dict in settings['axes'].items():
        #         self._optimizer_settings['axes'][axis].update(axis_dict)
        # if 'settle_time' in settings:
        #     if settings['settle_time'] < 0:
        #         self.log.error('Optimizer settle time must be positive number.')
        #     else:
        #         self._optimizer_settings['settle_time'] = float(settings['settle_time'])
        # if 'pixel_clock' in settings:
        #     if settings['pixel_clock'] < 1:
        #         self.log.error('Optimizer pixel clock must be integer number >= 1.')
        #     else:
        #         self._optimizer_settings['pixel_clock'] = int(settings['pixel_clock'])
        # if 'backscan_pts' in settings:
        #     if settings['backscan_pts'] < 1:
        #         self.log.error('Optimizer backscan points must be integer number >= 1.')
        #     else:
        #         self._optimizer_settings['backscan_pts'] = int(settings['backscan_pts'])
        # if 'sequence' in settings:
        #     self._optimizer_settings['sequence'] = tuple(settings['sequence'])
        self.sigOptimizerSettingsChanged.emit(self.optimizer_settings)
        return

    @qudi_slot(dict)
    @qudi_slot(dict, object)
    def set_scanner_target_position(self, pos_dict, caller_id=None):
        with self._thread_lock:
            if self.module_state() != 'idle':
                self.log.error('Unable to change scanner target position while a scan is running.')
                return self._scanner().get_target()

            ax_constr = self.scanner_constraints.axes
            for ax, pos in pos_dict.items():
                if ax not in ax_constr:
                    self.log.error('Unknown scanner axis: "{0}"'.format(ax))
                    return self._scanner().get_target()
                tmp_val = ax_constr[ax].clip_value(pos)
                if pos != tmp_val:
                    self.log.warning('Scanner position target value out of bounds for axis "{0}". '
                                     'Clipping value.'.format(ax))
                    pos_dict[ax] = tmp_val

            new_pos = self._scanner().move_absolute(pos_dict)
            self.sigScannerTargetChanged.emit(new_pos, id(self) if caller_id is None else caller_id)
            return

    @qudi_slot()
    def _update_scanner_position_loop(self):
        with self._thread_lock:
            if self.module_state() == 'idle':
                self.sigScannerPositionChanged.emit(self._scanner().get_position(), id(self))
                self._start_timer()

    @qudi_slot()
    def update_scanner_position(self):
        with self._thread_lock:
            self.sigScannerPositionChanged.emit(self._scanner().get_position(), id(self))

    @qudi_slot(bool)
    @qudi_slot(bool, tuple)
    def toggle_scan(self, start, scan_axes=None):
        with self._thread_lock:
            if start and self.module_state() != 'idle':
                self.sigScanStateChanged.emit(True, self.__current_scan)
                return 0
            elif not start and self.module_state() == 'idle':
                self.sigScanStateChanged.emit(True, self.__current_scan)
                return 0

            if start:
                if scan_axes is None or not (0 < len(scan_axes) < 3):
                    self.log.error('Unable to start scan. Scan axes must be tuple of len 1 or 2.')
                    return -1

                self.module_state.lock()

                self.__current_scan = tuple(scan_axes)
                settings = {'axes': tuple(scan_axes),
                            'range': tuple(self._scan_ranges[ax] for ax in scan_axes),
                            'resolution': tuple(self._scan_resolution[ax] for ax in scan_axes),
                            'frequency': self._scan_frequency}
                new_settings = self._scanner().configure_scan(settings)
                if new_settings['axes'] != self.__current_scan:
                    self.log.error('Something went wrong while configuring scanner. Axes to scan '
                                   'returned by scanner {0} do not match the intended scan axes '
                                   '{1}.'.format(new_settings['axes'], self.__current_scan))
                    self.module_state.unlock()
                    self.sigScanStateChanged.emit(False, self.__current_scan)
                    return -1
                for ax_index, ax in enumerate(scan_axes):
                    # Update scan ranges if needed
                    old = self._scan_ranges[ax]
                    new = new_settings['range'][ax_index]
                    if old[0] != new[0] or old[1] != new[1]:
                        self._scan_ranges[ax] = tuple(new)
                        self.sigScanSettingsChanged.emit({'range': {ax: self._scan_ranges[ax]}})

                    # Update scan resolution if needed
                    old = self._scan_resolution[ax]
                    new = new_settings['resolution'][ax_index]
                    if old != new:
                        self._scan_resolution[ax] = int(new)
                        self.sigScanSettingsChanged.emit(
                            {'resolution': {ax: self._scan_resolution[ax]}})

                # Update scan frequency if needed
                new = new_settings['frequency']
                if self._scan_frequency != new:
                    self._scan_frequency = float(new)
                    self.sigScanSettingsChanged.emit({'frequency': self._scan_frequency})

                line_points = self._scan_resolution[scan_axes[0]] if len(scan_axes) > 1 else 1
                self.__scan_update_interval = max(
                    self._min_scan_update_interval,
                    min(self._max_scan_update_interval, line_points / self._scan_frequency)
                )

                # Try to start scanner
                if self._scanner().start_scan() < 0:
                    self.log.error('Unable to start scanner.')
                    self.module_state.unlock()
                    self.sigScanStateChanged.emit(False, self.__current_scan)
                    return -1

                self.log.debug('Scanner successfully started')

                self._stop_timer()
                self.log.debug('Timer stopped')
                self.__timer.timeout.disconnect()
                self.__timer.setSingleShot(True)
                self.__timer.setInterval(int(round(self.__scan_update_interval * 1000)))
                self.__timer.timeout.connect(self._scan_loop, QtCore.Qt.QueuedConnection)
                self.log.debug('Timer connected')
                self.sigScanStateChanged.emit(True, self.__current_scan)
                self.log.debug('Starting scan timer')
                self._start_timer()
            else:
                scan_data = self._scanner().get_scan_data()
                while len(self._scan_history) >= self._max_history_length:
                    self._scan_history.pop(0)
                self._scan_history.append(scan_data)
                self._curr_history_index = len(self._scan_history) - 1
                self.sigScanDataChanged.emit(scan_data)
                if self._scanner().stop_scan() < 0:
                    self.log.error(
                        'Unable to stop scan. Waiting for currently running scan to finish.')
                    self.sigScanStateChanged.emit(True, self.__current_scan)
                    return -1
                self._stop_timer()
                self.__timer.timeout.disconnect()
                self.__timer.setSingleShot(True)
                self.__timer.setInterval(int(round(self._position_update_interval * 1000)))
                self.__timer.timeout.connect(
                    self._update_scanner_position_loop, QtCore.Qt.QueuedConnection)
                self.module_state.unlock()
                self.sigScanStateChanged.emit(False, self.__current_scan)
                self._start_timer()
            return 0

    @qudi_slot()
    def _scan_loop(self):
        with self._thread_lock:
            if self.module_state() != 'locked':
                return

            scan_data = self._scanner().get_scan_data()
            # Terminate scan if finished
            if scan_data.is_finished:
                if self._scanner().stop_scan() < 0:
                    self.log.error('Unable to stop scan.')
                self._stop_timer()
                self.__timer.timeout.disconnect()
                self.__timer.setSingleShot(True)
                self.__timer.setInterval(int(round(self._position_update_interval * 1000)))
                self.__timer.timeout.connect(
                    self._update_scanner_position_loop, QtCore.Qt.QueuedConnection)
                self.module_state.unlock()
                self.sigScanStateChanged.emit(False, self.__current_scan)
                while len(self._scan_history) >= self._max_history_length:
                    self._scan_history.pop(0)
                self._scan_history.append(scan_data)
                self._curr_history_index = len(self._scan_history) - 1
                self._start_timer()
            self.sigScanDataChanged.emit(scan_data)
            self._start_timer()
            return

    @qudi_slot()
    def history_previous(self):
        with self._thread_lock:
            if self._curr_history_index < 1:
                self.log.warning('Unable to restore previous state from scan history. '
                                 'Already at earliest history entry.')
                return
        return self.restore_from_history(self._curr_history_index - 1)

    @qudi_slot()
    def history_next(self):
        with self._thread_lock:
            if self._curr_history_index >= len(self._scan_history) - 1:
                self.log.warning('Unable to restore next state from scan history. '
                                 'Already at latest history entry.')
                return
        return self.restore_from_history(self._curr_history_index + 1)

    @qudi_slot(int)
    def restore_from_history(self, index):
        with self._thread_lock:
            if self.module_state() != 'idle':
                self.log.error('Scan is running. Unable to restore history state.')
                return
            if not isinstance(index, int):
                self.log.error('History index to restore must be int type.')
                return

            try:
                data = self._scan_history[index]
            except IndexError:
                self.log.error('History index "{0}" out of range.'.format(index))
                return

            ax_constr = self.scanner_constraints.axes
            for i, ax in enumerate(data.scan_axes):
                constr = ax_constr[ax]
                self._scan_resolution[ax] = int(constr.clip_resolution(data.scan_resolution[i]))
                self._scan_ranges[ax] = tuple(
                    constr.clip_value(val) for val in data.scan_range[i])
            self._scan_frequency = data.scan_frequency
            self._curr_history_index = index
            print({'range': self._scan_ranges.copy(),
                                              'resolution': self._scan_resolution.copy(),
                                              'frequency': self._scan_frequency})
            self.sigScanSettingsChanged.emit({'range': self._scan_ranges.copy(),
                                              'resolution': self._scan_resolution.copy(),
                                              'frequency': self._scan_frequency})
            self.sigScanDataChanged.emit(data)
            return

    @qudi_slot()
    def set_full_scan_ranges(self):
        scan_range = {ax: axis.value_bounds for ax, axis in self.scanner_constraints.axes.items()}
        return self.set_scan_range(scan_range)

    @qudi_slot()
    def _start_timer(self):
        self.__sigStartTimer.emit()

    @qudi_slot()
    def _stop_timer(self):
        self.__sigStopTimer.emit()

    @qudi_slot(str)
    def save_1d_scan(self, axis):
        pass

    @qudi_slot(str, object)
    def save_2d_scan(self, axes, color_range=None):
        axes = tuple(str(ax).lower() for ax in axes)
        with self._thread_lock:
            if self.module_state() != 'idle':
                self.log.error('Unable to save 2D scan. Measurement/Saving already in progress.')
                return

            # Try to find most recent scan data
            scan_data = None
            for history_index, data in reversed(list(enumerate(self._scan_history))):
                if data.scan_axes == axes:
                    scan_data = data
                    break
            if scan_data is None:
                self.log.error(
                    'Unable to save 2D scan. No scan data available for axes {0}.'.format(axes))
                return

            self.sigScanDataChanged.emit(scan_data)
            self.sigSaveDataState.emit(True)
            # ToDo: Update history index to newest relevant entry
            # if self._scan_history[self._curr_history_index] is scan_data:
            #     if self._curr_history_index == history_index:

        ds = TextDataStorage(column_headers='Image (columns is X, rows is Y)',
                             number_format='%.18e',
                             comments='# ',
                             delimiter='\t',
                             sub_directory='Scanning',
                             file_extension='.dat',
                             image_format=ImageFormat.PNG,
                             include_global_parameters=True,
                             use_daily_dir=True)

        # ToDo: Add meaningful metadata if missing
        parameters = {'x-axis name': scan_data.scan_axes[0],
                      'x-axis unit': scan_data.axes_units[scan_data.scan_axes[0]],
                      'x-axis min': scan_data.scan_range[0][0],
                      'x-axis max': scan_data.scan_range[0][1],
                      'x-axis resolution': scan_data.scan_resolution[0],
                      'y-axis name': scan_data.scan_axes[1],
                      'y-axis unit': scan_data.axes_units[scan_data.scan_axes[1]],
                      'y-axis min': scan_data.scan_range[1][0],
                      'y-axis max': scan_data.scan_range[1][1],
                      'y-axis resolution': scan_data.scan_resolution[1],
                      'pixel scan frequency': scan_data.scan_frequency
                      }

        # Save data to file
        timestamp = datetime.datetime.now()
        for channel, data in scan_data.data.items():
            nametag = '{0}_{1}{2}_scan'.format(channel, *scan_data.scan_axes)
            ds.save_data(data, parameters=parameters, nametag=nametag, timestamp=timestamp)

        # Save thumbnails to file
        for channel, data in scan_data.data.items():
            figure = self.draw_2d_scan_figure(scan_data, channel, cbar_range=color_range)
            ds.save_thumbnail(mpl_figure=figure, timestamp=timestamp, nametag=nametag)

        self.log.debug('Scan image saved.')
        return

    def draw_2d_scan_figure(self, scan_data, channel, cbar_range=None):
        """ Create a 2-D color map figure of the scan image.

        @return fig: a matplotlib figure object to be saved to file.
        """
        image_arr = scan_data.data[channel]
        scan_axes = scan_data.scan_axes
        scanner_pos = self._scanner().get_target()

        # If no colorbar range was given, take full range of data
        if cbar_range is None:
            cbar_range = (image_arr.min(), image_arr.max())

        # ToDo: Scale data and axes in a suitable and general way (with utils)

        # Use qudi style
        plt.style.use(mpl_qd_style)

        # Create figure
        fig, ax = plt.subplots()

        # Create image plot
        cfimage = ax.imshow(image_arr.transpose(),
                            cmap='inferno',  # FIXME: reference the right place in qudi
                            origin='lower',
                            vmin=cbar_range[0],
                            vmax=cbar_range[1],
                            interpolation='none',
                            extent=(*scan_data.scan_range[0], *scan_data.scan_range[1]))

        ax.set_aspect(1)
        ax.set_xlabel(scan_axes[0] + ' position ({0})'.format(scan_data.axes_units[scan_axes[0]]))
        ax.set_ylabel(scan_axes[1] + ' position ({0})'.format(scan_data.axes_units[scan_axes[1]]))
        ax.spines['bottom'].set_position(('outward', 10))
        ax.spines['left'].set_position(('outward', 10))
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.get_xaxis().tick_bottom()
        ax.get_yaxis().tick_left()

        # draw the scanner position if defined
        # ToDo: Check if scanner position is within image boundaries. Don't draw if not the case.
        trans_xmark = mpl.transforms.blended_transform_factory(ax.transData, ax.transAxes)
        trans_ymark = mpl.transforms.blended_transform_factory(ax.transAxes, ax.transData)
        ax.annotate('',
                    xy=(scanner_pos[scan_axes[0]], 0),
                    xytext=(scanner_pos[scan_axes[0]], -0.01),
                    xycoords=trans_xmark,
                    arrowprops={'facecolor': '#17becf', 'shrink': 0.05})
        ax.annotate('',
                    xy=(0, scanner_pos[scan_axes[1]]),
                    xytext=(-0.01, scanner_pos[scan_axes[1]]),
                    xycoords=trans_ymark,
                    arrowprops={'facecolor': '#17becf', 'shrink': 0.05})

        # Draw the colorbar
        cbar = plt.colorbar(cfimage, shrink=0.8)  #, fraction=0.046, pad=0.08, shrink=0.75)
        if scan_data.channel_units[channel]:
            cbar.set_label('{0} ({1})'.format(channel, scan_data.channel_units[channel]))
        else:
            cbar.set_label('{0}'.format(channel))

        # remove ticks from colorbar for cleaner image
        cbar.ax.tick_params(which=u'both', length=0)
        return fig