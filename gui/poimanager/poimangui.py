# -*- coding: utf-8 -*-
"""
This module contains a GUI through which the POI Manager class can be controlled.

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


import numpy as np
import os
import pyqtgraph as pg
import time

from core.module import Connector
from core.util.units import ScaledFloat
from gui.guibase import GUIBase
from gui.guiutils import ColorBar
from gui.colordefs import ColorScaleInferno
from gui.colordefs import QudiPalettePale as palette
from qtpy import QtCore
from qtpy import QtWidgets
from qtpy import uic


class PoiMarker(pg.EllipseROI):
    """
    Creates a circle as a marker.

    @param float[2] pos: The (x, y) position of the POI.
    @param **args: All extra keyword arguments are passed to ROI()

    Have a look at:
    http://www.pyqtgraph.org/documentation/graphicsItems/roi.html
    """
    default_pen = {'color': 'F0F', 'width': 2}
    select_pen = {'color': 'FFF', 'width': 2}

    sigPoiSelected = QtCore.Signal(str)

    def __init__(self, position, radius, poi_name=None, view_widget=None, **kwargs):
        """

        @param position:
        @param radius:
        @param poi_name:
        @param view_widget:
        @param kwargs:
        """
        self._poi_name = '' if poi_name is None else poi_name
        self._view_widget = view_widget
        self._selected = False
        self._position = np.array(position, dtype=float)

        size = (2 * radius, 2 * radius)
        super().__init__(pos=self._position, size=size, pen=self.default_pen, **kwargs)
        # self.aspectLocked = True
        self.label = pg.TextItem(text=self._poi_name,
                                 anchor=(0, 1),
                                 color=self.default_pen['color'])
        self.setAcceptedMouseButtons(QtCore.Qt.LeftButton)
        self.sigClicked.connect(self._notify_clicked_poi_name)
        self.set_position(self._position)
        return

    def _addHandles(self):
        pass

    @property
    def radius(self):
        return self.size()[0] / 2

    @property
    def selected(self):
        return bool(self._selected)

    @property
    def poi_name(self):
        return str(self._poi_name)

    @property
    def position(self):
        return self._position

    def add_to_view_widget(self, view_widget=None):
        if view_widget is not None:
            self._view_widget = view_widget
        self._view_widget.addItem(self)
        self._view_widget.addItem(self.label)
        return

    def delete_from_view_widget(self, view_widget=None):
        if view_widget is not None:
            self._view_widget = view_widget
        self._view_widget.removeItem(self.label)
        self._view_widget.removeItem(self)
        return

    def set_position(self, position):
        """
        Sets the POI position, so the centre of the marker circle.

        @param float[2] position: The (x,y) center position of the POI marker
        """
        self._position = np.array(position, dtype=float)
        radius = self.radius
        label_offset = radius / np.sqrt(2)
        self.setPos(self._position[0] - radius, self._position[1] - radius)
        self.label.setPos(self._position[0] + label_offset, self._position[1] + label_offset)
        return

    def set_name(self, name):
        """

        @param str name:
        """
        self._poi_name = name
        self.label.setText(self._poi_name)
        return

    def set_radius(self, radius):
        """

        @param float radius:
        """
        label_offset = radius / np.sqrt(2)
        self.setSize((2 * radius, 2 * radius))
        self.setPos(self.position[0] - radius, self.position[1] - radius)
        self.label.setPos(self.position[0] + label_offset, self.position[1] + label_offset)
        return

    @QtCore.Slot()
    def _notify_clicked_poi_name(self):
        self.sigPoiSelected.emit(self._poi_name)

    def select(self):
        self._selected = True
        self.setPen(self.select_pen)
        self.label.setColor(self.select_pen['color'])
        return

    def deselect(self):
        self._selected = False
        self.setPen(self.default_pen)
        self.label.setColor(self.default_pen['color'])
        return


class PoiManagerMainWindow(QtWidgets.QMainWindow):

    def __init__(self):
        # Get the path to the *.ui file
        this_dir = os.path.dirname(__file__)
        ui_file = os.path.join(this_dir, 'ui_poimangui.ui')

        # Load it
        super(PoiManagerMainWindow, self).__init__()
        uic.loadUi(ui_file, self)
        self.show()


class PoiManagerGui(GUIBase):

    """ This is the GUI Class for PoiManager """

    _modclass = 'PoiManagerGui'
    _modtype = 'gui'

    # declare connectors
    poimanagerlogic = Connector(interface='PoiManagerLogic')
    scannerlogic = Connector(interface='ConfocalLogic')

    # declare signals
    sigTrackPeriodChanged = QtCore.Signal(float)
    sigPoiNameChanged = QtCore.Signal(str)
    sigRoiNameChanged = QtCore.Signal(str)

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)

        self._mw = None             # QMainWindow handle
        self.roi_image = None       # pyqtgraph PlotImage for ROI scan image
        self.roi_cb = None          # The qudi colorbar to use with roi_image
        self.x_shift_plot = None    # pyqtgraph PlotDataItem for ROI history plot
        self.y_shift_plot = None    # pyqtgraph PlotDataItem for ROI history plot
        self.z_shift_plot = None    # pyqtgraph PlotDataItem for ROI history plot

        self._markers = dict()      # dict to hold handles for the POI markers

    def on_activate(self):
        """
        Initializes the overall GUI, and establishes the connectors.

        This method executes the init methods for each of the GUIs.
        """
        self._markers = dict()

        self._mw = PoiManagerMainWindow()
        # Configuring the dock widgets.
        # All our gui elements are dockable, so there should be no "central" widget.
        self._mw.centralwidget.hide()
        self._mw.setDockNestingEnabled(True)

        # Initialize plots
        self.__init_roi_scan_image()
        self.__init_roi_history_plot()

        # Initialize refocus timer
        self._update_refocus_timer(self.poimanagerlogic().module_state() == 'locked',
                                   self.poimanagerlogic().refocus_period,
                                   self.poimanagerlogic().refocus_period)
        # Initialize POIs
        self._update_pois(self.poimanagerlogic().poi_positions)
        # Initialize ROI name
        self._update_roi_name(self.poimanagerlogic().roi_name)

        # Distance Measurement:
        # Introducing a SignalProxy will limit the rate of signals that get fired.
        self.mouse_moved_proxy = pg.SignalProxy(signal=self.roi_image.scene().sigMouseMoved,
                                                rateLimit=30,
                                                slot=self.mouse_moved_callback)

        # Connect signals
        self.__connect_internal_signals()
        self.__connect_update_signals_from_logic()
        self.__connect_control_signals_to_logic()

        self._mw.show()
        return

    def on_deactivate(self):
        """
        De-initialisation performed during deactivation of the module.
        """
        self.__disconnect_control_signals_to_logic()
        self.__disconnect_update_signals_from_logic()
        self.__disconnect_internal_signals()
        self._mw.close()

    def __init_roi_scan_image(self):
        # Get the color scheme
        my_colors = ColorScaleInferno()
        # Setting up display of ROI xy scan image
        self.roi_image = pg.ImageItem(axisOrder='row-major', lut=my_colors.lut)
        self._mw.roi_map_ViewWidget.addItem(self.roi_image)
        self._mw.roi_map_ViewWidget.setLabel('bottom', 'X position', units='m')
        self._mw.roi_map_ViewWidget.setLabel('left', 'Y position', units='m')
        self._mw.roi_map_ViewWidget.setAspectLocked(lock=True, ratio=1.0)
        # Set up color bar
        self.roi_cb = ColorBar(my_colors.cmap_normed, 100, 0, 100000)
        self._mw.roi_cb_ViewWidget.addItem(self.roi_cb)
        self._mw.roi_cb_ViewWidget.hideAxis('bottom')
        self._mw.roi_cb_ViewWidget.setLabel('left', 'Fluorescence', units='c/s')
        self._mw.roi_cb_ViewWidget.setMouseEnabled(x=False, y=False)

        # Get scan image from logic and update initialize plot
        self._update_scan_image()
        return

    def __init_roi_history_plot(self):
        history = self.poimanagerlogic().roi_pos_history
        # Setting up display of sample shift plot
        self.x_shift_plot = pg.PlotDataItem(x=history[:, 0],
                                            y=history[:, 1],
                                            pen=pg.mkPen(palette.c1, style=QtCore.Qt.DotLine),
                                            symbol='o',
                                            symbolPen=palette.c1,
                                            symbolBrush=palette.c1,
                                            symbolSize=5,
                                            name='x')
        self.y_shift_plot = pg.PlotDataItem(x=history[:, 0],
                                            y=history[:, 2],
                                            pen=pg.mkPen(palette.c2, style=QtCore.Qt.DotLine),
                                            symbol='s',
                                            symbolPen=palette.c2,
                                            symbolBrush=palette.c2,
                                            symbolSize=5,
                                            name='y')
        self.z_shift_plot = pg.PlotDataItem(x=history[:, 0],
                                            y=history[:, 3],
                                            pen=pg.mkPen(palette.c3, style=QtCore.Qt.DotLine),
                                            symbol='t',
                                            symbolPen=palette.c3,
                                            symbolBrush=palette.c3,
                                            symbolSize=5,
                                            name='z')

        self._mw.sample_shift_ViewWidget.addLegend()

        # Add the plot to the ViewWidget defined in the UI file
        self._mw.sample_shift_ViewWidget.addItem(self.x_shift_plot)
        self._mw.sample_shift_ViewWidget.addItem(self.y_shift_plot)
        self._mw.sample_shift_ViewWidget.addItem(self.z_shift_plot)

        # Label axes
        self._mw.sample_shift_ViewWidget.setLabel('bottom', 'Time', units='s')
        self._mw.sample_shift_ViewWidget.setLabel('left', 'Sample shift', units='m')
        return

    def __connect_update_signals_from_logic(self):
        self.poimanagerlogic().sigRefocusTimerUpdated.connect(
            self._update_refocus_timer, QtCore.Qt.QueuedConnection)
        self.poimanagerlogic().sigPoisUpdated.connect(
            self._update_pois, QtCore.Qt.QueuedConnection)
        self.poimanagerlogic().sigPoiUpdated.connect(
            self._update_poi, QtCore.Qt.QueuedConnection)
        self.poimanagerlogic().sigScanImageUpdated.connect(
            self._update_scan_image, QtCore.Qt.QueuedConnection)
        self.poimanagerlogic().sigActivePoiUpdated.connect(
            self._update_active_poi, QtCore.Qt.QueuedConnection)
        self.poimanagerlogic().sigRoiHistoryUpdated.connect(
            self._update_roi_history, QtCore.Qt.QueuedConnection)
        self.poimanagerlogic().sigRoiNameUpdated.connect(
            self._update_roi_name, QtCore.Qt.QueuedConnection)
        return

    def __disconnect_update_signals_from_logic(self):
        self.poimanagerlogic().sigRefocusTimerUpdated.disconnect()
        self.poimanagerlogic().sigPoisUpdated.disconnect()
        self.poimanagerlogic().sigPoiUpdated.disconnect()
        self.poimanagerlogic().sigScanImageUpdated.disconnect()
        self.poimanagerlogic().sigActivePoiUpdated.disconnect()
        self.poimanagerlogic().sigRoiHistoryUpdated.disconnect()
        self.poimanagerlogic().sigRoiNameUpdated.disconnect()
        return

    def __connect_control_signals_to_logic(self):
        self._mw.new_poi_Action.triggered.connect(
            self.poimanagerlogic().add_poi, QtCore.Qt.QueuedConnection)
        self._mw.goto_poi_Action.triggered.connect(
            self.poimanagerlogic().go_to_poi, QtCore.Qt.QueuedConnection)
        self._mw.new_roi_Action.triggered.connect(
            self.poimanagerlogic().reset_roi, QtCore.Qt.QueuedConnection)
        self._mw.refind_poi_Action.triggered.connect(
            self.poimanagerlogic().optimise_poi_position, QtCore.Qt.QueuedConnection)
        self._mw.get_confocal_image_PushButton.clicked.connect(
            self.poimanagerlogic().set_scan_image, QtCore.Qt.QueuedConnection)
        self._mw.set_poi_PushButton.clicked.connect(
            self.poimanagerlogic().add_poi, QtCore.Qt.QueuedConnection)
        self._mw.delete_last_pos_Button.clicked.connect(
            self.poimanagerlogic().delete_history_entry, QtCore.Qt.QueuedConnection)
        self._mw.manual_update_poi_PushButton.clicked.connect(
            self.poimanagerlogic().move_roi_from_poi_position, QtCore.Qt.QueuedConnection)
        self._mw.move_poi_PushButton.clicked.connect(
            self.poimanagerlogic().set_poi_anchor_from_position, QtCore.Qt.QueuedConnection)
        self._mw.delete_poi_PushButton.clicked.connect(
            self.poimanagerlogic().delete_poi, QtCore.Qt.QueuedConnection)
        self._mw.active_poi_ComboBox.activated[str].connect(
            self.poimanagerlogic().set_active_poi, QtCore.Qt.QueuedConnection)
        self._mw.goto_poi_after_update_checkBox.stateChanged.connect(
            self.poimanagerlogic().set_move_scanner_after_optimise, QtCore.Qt.QueuedConnection)
        self._mw.track_poi_Action.triggered.connect(
            self.poimanagerlogic().toggle_periodic_refocus, QtCore.Qt.QueuedConnection)
        self.sigTrackPeriodChanged.connect(
            self.poimanagerlogic().set_refocus_period, QtCore.Qt.QueuedConnection)
        self.sigRoiNameChanged.connect(
            self.poimanagerlogic().rename_roi, QtCore.Qt.QueuedConnection)
        self.sigPoiNameChanged.connect(
            self.poimanagerlogic().rename_poi, QtCore.Qt.QueuedConnection)
        return

    def __disconnect_control_signals_to_logic(self):
        self._mw.new_poi_Action.triggered.disconnect()
        self._mw.goto_poi_Action.triggered.disconnect()
        self._mw.new_roi_Action.triggered.disconnect()
        self._mw.refind_poi_Action.triggered.disconnect()
        self._mw.get_confocal_image_PushButton.clicked.disconnect()
        self._mw.set_poi_PushButton.clicked.disconnect()
        self._mw.delete_last_pos_Button.clicked.disconnect()
        self._mw.manual_update_poi_PushButton.clicked.disconnect()
        self._mw.move_poi_PushButton.clicked.disconnect()
        self._mw.delete_poi_PushButton.clicked.disconnect()
        self._mw.active_poi_ComboBox.activated[str].disconnect()
        self._mw.goto_poi_after_update_checkBox.stateChanged.disconnect()
        self._mw.track_poi_Action.triggered.disconnect()
        self.sigTrackPeriodChanged.disconnect()
        self.sigRoiNameChanged.disconnect()
        self.sigPoiNameChanged.disconnect()
        for marker in self._markers.values():
            marker.sigPoiSelected.disconnect()
        return

    def __connect_internal_signals(self):
        self._mw.track_period_SpinBox.editingFinished.connect(self.track_period_changed)
        self._mw.roi_name_LineEdit.editingFinished.connect(self.roi_name_changed)
        self._mw.poi_name_LineEdit.returnPressed.connect(self.poi_name_changed)
        self._mw.save_roi_Action.triggered.connect(self.save_roi)
        self._mw.load_roi_Action.triggered.connect(self.load_roi)

        # self._mw.display_shift_vs_duration_RadioButton.toggled.connect(self._redraw_sample_shift)
        # self._mw.display_shift_vs_clocktime_RadioButton.toggled.connect(self._redraw_sample_shift)
        self._mw.roi_cb_centiles_RadioButton.toggled.connect(self._update_scan_image)
        self._mw.roi_cb_manual_RadioButton.toggled.connect(self._update_scan_image)
        self._mw.roi_cb_min_SpinBox.valueChanged.connect(self.shortcut_to_roi_cb_manual)
        self._mw.roi_cb_max_SpinBox.valueChanged.connect(self.shortcut_to_roi_cb_manual)
        self._mw.roi_cb_low_percentile_DoubleSpinBox.valueChanged.connect(
            self.shortcut_to_roi_cb_centiles)
        self._mw.roi_cb_high_percentile_DoubleSpinBox.valueChanged.connect(
            self.shortcut_to_roi_cb_centiles)
        return

    def __disconnect_internal_signals(self):
        self._mw.track_period_SpinBox.editingFinished.disconnect()
        self._mw.roi_name_LineEdit.editingFinished.disconnect()
        self._mw.poi_name_LineEdit.returnPressed.disconnect()
        self._mw.save_roi_Action.triggered.disconnect()
        self._mw.load_roi_Action.triggered.disconnect()

        # self._mw.display_shift_vs_duration_RadioButton.toggled.disconnect()
        # self._mw.display_shift_vs_clocktime_RadioButton.toggled.disconnect()
        self._mw.roi_cb_centiles_RadioButton.toggled.disconnect()
        self._mw.roi_cb_manual_RadioButton.toggled.disconnect()
        self._mw.roi_cb_min_SpinBox.valueChanged.disconnect()
        self._mw.roi_cb_max_SpinBox.valueChanged.disconnect()
        self._mw.roi_cb_low_percentile_DoubleSpinBox.valueChanged.disconnect()
        self._mw.roi_cb_high_percentile_DoubleSpinBox.valueChanged.disconnect()
        return

    def mouse_moved_callback(self, event):
        """ Handles any mouse movements inside the image.

        @param event:   Event that signals the new mouse movement.
                        This should be of type QPointF.

        Gets the mouse position, converts it to a position scaled to the image axis
        and than calculates and updated the position to the current POI.
        """

        # converts the absolute mouse position to a position relative to the axis
        mouse_pos = self._mw.roi_map_ViewWidget.getPlotItem().getViewBox().mapSceneToView(event[0])

        # only calculate distance, if a POI is selected
        active_poi = self.poimanagerlogic().active_poi
        if active_poi:
            poi_pos = self.poimanagerlogic().get_poi_position(active_poi)
            dx = ScaledFloat(mouse_pos.x() - poi_pos[0])
            dy = ScaledFloat(mouse_pos.y() - poi_pos[1])
            d_total = ScaledFloat(
                np.sqrt((mouse_pos.x() - poi_pos[0])**2 + (mouse_pos.y() - poi_pos[1])**2))

            self._mw.poi_distance_label.setText(
                '{0:.2r}m ({1:.2r}m, {2:.2r}m)'.format(d_total, dx, dy))
        else:
            self._mw.poi_distance_label.setText('? (?, ?)')
        pass

    def show(self):
        """Make main window visible and put it above all other windows. """
        QtWidgets.QMainWindow.show(self._mw)
        self._mw.activateWindow()
        self._mw.raise_()

    @QtCore.Slot()
    @QtCore.Slot(np.ndarray, tuple)
    def _update_scan_image(self, scan_image=None, image_extent=None):
        """

        @param scan_image:
        @param image_extent:
        """
        if scan_image is None or image_extent is None:
            scan_image = self.poimanagerlogic().roi_scan_image
            image_extent = self.poimanagerlogic().roi_scan_image_extent

        cb_range = self.get_cb_range(image=scan_image)
        self.roi_image.setImage(image=scan_image, levels=cb_range)

        (x_min, x_max), (y_min, y_max) = image_extent
        self.roi_image.getViewBox().enableAutoRange()
        self.roi_image.setRect(QtCore.QRectF(x_min, y_min, x_max - x_min, y_max - y_min))
        self._mw.roi_map_ViewWidget.update()
        self.roi_cb.refresh_colorbar(*cb_range)
        self._mw.roi_cb_ViewWidget.update()
        return

    @QtCore.Slot(np.ndarray)
    def _update_roi_history(self, history):
        if history.shape[1] != 4:
            self.log.error('ROI history must be an array of type float[][4].')
            return
        self.x_shift_plot.setData(history[:, 0], history[:, 1])
        self.y_shift_plot.setData(history[:, 0], history[:, 2])
        self.z_shift_plot.setData(history[:, 0], history[:, 3])
        return

    @QtCore.Slot(bool, float, float)
    def _update_refocus_timer(self, is_active, period, time_until_refocus):
        if not self._mw.track_period_SpinBox.hasFocus():
            self._mw.track_period_SpinBox.blockSignals(True)
            self._mw.track_period_SpinBox.setValue(period)
            self._mw.track_period_SpinBox.blockSignals(False)

        self._mw.track_poi_Action.blockSignals(True)
        self._mw.time_till_next_update_ProgressBar.blockSignals(True)

        if is_active:
            self._mw.track_poi_Action.setChecked(True)
            self._mw.refind_poi_Action.setEnabled(False)
        else:
            self._mw.track_poi_Action.setChecked(False)
            self._mw.refind_poi_Action.setEnabled(True)
        self._mw.time_till_next_update_ProgressBar.setMaximum(period)
        self._mw.time_till_next_update_ProgressBar.setValue(time_until_refocus)

        self._mw.time_till_next_update_ProgressBar.blockSignals(False)
        self._mw.track_poi_Action.blockSignals(False)
        return

    @QtCore.Slot(dict)
    def _update_pois(self, poi_dict):
        """ Populate the dropdown box for selecting a poi. """
        self._mw.active_poi_ComboBox.blockSignals(True)

        self._mw.active_poi_ComboBox.clear()

        poi_names = sorted(poi_dict)
        self._mw.active_poi_ComboBox.addItems(poi_names)

        # Get two list of POI names. One of those to delete and one of those to add
        old_poi_names = set(self._markers)
        new_poi_names = set(poi_names)
        names_to_delete = list(old_poi_names.difference(new_poi_names))
        names_to_add = list(new_poi_names.difference(old_poi_names))

        # Delete markers accordingly
        for name in names_to_delete:
            self._remove_poi_marker(name)
        # Update positions of all remaining markers
        size = self.poimanagerlogic().optimise_xy_size * np.sqrt(2)
        for name, marker in self._markers.items():
            marker.setSize((size, size))
            marker.set_position(poi_dict[name])
        # Add new markers
        for name in names_to_add:
            self._add_poi_marker(name=name, position=poi_dict[name])

        # If there is no active POI, set the combobox to nothing (-1)
        active_poi = self.poimanagerlogic().active_poi
        if active_poi in poi_names:
            self._mw.active_poi_ComboBox.setCurrentText(active_poi)
            self._markers[active_poi].select()
            active_poi_pos = poi_dict[active_poi]
            self._mw.poi_coords_label.setText(
                '({0:.2r}m, {1:.2r}m, {2:.2r}m)'.format(ScaledFloat(active_poi_pos[0]),
                                                        ScaledFloat(active_poi_pos[1]),
                                                        ScaledFloat(active_poi_pos[2])))
        else:
            self._mw.active_poi_ComboBox.setCurrentIndex(-1)

        self._mw.active_poi_ComboBox.blockSignals(False)
        return

    @QtCore.Slot(str, str, np.ndarray)
    def _update_poi(self, old_name, new_name, position):
        # Handle changed names and deleted/added POIs
        if old_name != new_name:
            self._mw.active_poi_ComboBox.blockSignals(True)
            # Remember current text
            text_active_poi = self._mw.active_poi_ComboBox.currentText()
            # sort POI names and repopulate ComboBoxes
            self._mw.active_poi_ComboBox.clear()
            poi_names = sorted(self.poimanagerlogic().poi_names)
            self._mw.active_poi_ComboBox.addItems(poi_names)
            if text_active_poi == old_name:
                self._mw.active_poi_ComboBox.setCurrentText(new_name)
            else:
                self._mw.active_poi_ComboBox.setCurrentText(text_active_poi)
            self._mw.active_poi_ComboBox.blockSignals(False)

        # Delete/add/update POI marker to image
        if not old_name:
            # POI has been added
            self._add_poi_marker(name=new_name, position=position)
        elif not new_name:
            # POI has been deleted
            self._remove_poi_marker(name=old_name)
        else:
            # POI has been renamed and/or changed position
            size = self.poimanagerlogic().optimise_xy_size * np.sqrt(2)
            self._markers[old_name].set_name(new_name)
            self._markers[new_name] = self._markers.pop(old_name)
            self._markers[new_name].setSize((size, size))
            self._markers[new_name].set_position(position[:2])

        active_poi = self._mw.active_poi_ComboBox.currentText()
        if active_poi:
            self._markers[active_poi].select()
        return

    @QtCore.Slot(str)
    def _update_active_poi(self, name):

        # Deselect current marker
        for marker in self._markers.values():
            if marker.selected:
                marker.deselect()
                break

        # Unselect POI if name is None or empty str
        self._mw.active_poi_ComboBox.blockSignals(True)
        if not name:
            self._mw.active_poi_ComboBox.setCurrentIndex(-1)
        else:
            self._mw.active_poi_ComboBox.setCurrentText(name)
        self._mw.active_poi_ComboBox.blockSignals(False)

        if name:
            active_poi_pos = self.poimanagerlogic().get_poi_position(name)
        else:
            active_poi_pos = np.zeros(3)
        self._mw.poi_coords_label.setText(
            '({0:.2r}m, {1:.2r}m, {2:.2r}m)'.format(ScaledFloat(active_poi_pos[0]),
                                                    ScaledFloat(active_poi_pos[1]),
                                                    ScaledFloat(active_poi_pos[2])))

        if name in self._markers:
            self._markers[name].set_radius(self.poimanagerlogic().optimise_xy_size / np.sqrt(2))
            self._markers[name].select()
        return

    @QtCore.Slot(str)
    def _update_roi_name(self, name):
        self._mw.roi_name_LineEdit.blockSignals(True)
        self._mw.roi_name_LineEdit.setText(name)
        self._mw.roi_name_LineEdit.blockSignals(False)
        return

    @QtCore.Slot()
    def track_period_changed(self):
        self.sigTrackPeriodChanged.emit(self._mw.track_period_SpinBox.value())
        return

    @QtCore.Slot()
    def roi_name_changed(self):
        """ Set the name of the current ROI."""
        self.sigRoiNameChanged.emit(self._mw.roi_name_LineEdit.text())
        return

    @QtCore.Slot()
    def poi_name_changed(self):
        """ Change the name of the active poi."""
        new_name = self._mw.poi_name_LineEdit.text()
        if self._mw.active_poi_ComboBox.currentText() == new_name or not new_name:
            return

        self.sigPoiNameChanged.emit(new_name)

        # After POI name is changed, empty name field
        self._mw.poi_name_LineEdit.blockSignals(True)
        self._mw.poi_name_LineEdit.setText('')
        self._mw.poi_name_LineEdit.blockSignals(False)
        return

    @QtCore.Slot()
    def save_roi(self):
        """ Save ROI to file."""
        roi_name = self._mw.roi_name_LineEdit.text()
        self.poimanagerlogic().rename_roi(roi_name)
        self.poimanagerlogic().save_roi()
        return

    @QtCore.Slot()
    def load_roi(self):
        """ Load a saved ROI from file."""
        this_file = QtWidgets.QFileDialog.getOpenFileName(self._mw,
                                                          'Open ROI',
                                                          self.poimanagerlogic().data_directory,
                                                          'Data files (*.dat)')[0]
        self.poimanagerlogic().load_roi(complete_path=this_file)
        return

    def shortcut_to_roi_cb_manual(self):
        if not self._mw.roi_cb_manual_RadioButton.isChecked():
            self._mw.roi_cb_manual_RadioButton.toggle()
        else:
            self._update_scan_image()
        return

    def shortcut_to_roi_cb_centiles(self):
        if not self._mw.roi_cb_centiles_RadioButton.isChecked():
            self._mw.roi_cb_centiles_RadioButton.toggle()
        else:
            self._update_scan_image()
        return

    def get_cb_range(self, image):
        """ Process UI input to determine color bar range"""
        # If "Centiles" is checked, adjust colour scaling automatically to centiles.
        # Otherwise, take user-defined values.
        if self._mw.roi_cb_centiles_RadioButton.isChecked():
            low_centile = self._mw.roi_cb_low_percentile_DoubleSpinBox.value()
            high_centile = self._mw.roi_cb_high_percentile_DoubleSpinBox.value()

            cb_min = np.percentile(image, low_centile)
            cb_max = np.percentile(image, high_centile)
        else:
            cb_min = self._mw.roi_cb_min_SpinBox.value()
            cb_max = self._mw.roi_cb_max_SpinBox.value()
        return cb_min, cb_max

    def _add_poi_marker(self, name, position):
        """ Add a circular POI marker to the ROI scan image. """
        if name:
            if name in self._markers:
                self.log.error('Unable to add POI marker to ROI image. POI marker already present.')
                return
            marker = PoiMarker(position=position[:2],
                               view_widget=self._mw.roi_map_ViewWidget,
                               poi_name=name,
                               radius=self.poimanagerlogic().optimise_xy_size / np.sqrt(2),
                               movable=False)
            # Add to the scan image widget
            marker.add_to_view_widget()
            marker.sigPoiSelected.connect(
                self.poimanagerlogic().set_active_poi, QtCore.Qt.QueuedConnection)
            self._markers[name] = marker
        return

    def _remove_poi_marker(self, name):
        """ Remove the POI marker for a POI that was deleted. """
        if name in self._markers:
            self._markers[name].delete_from_view_widget()
            self._markers[name].sigPoiSelected.disconnect()
            del self._markers[name]
        return

    def _redraw_clocktime_ticks(self):
        """If duration is displayed, reset ticks to default.
        Otherwise, create and update custom date/time ticks to the new axis range.
        """
        myAxisItem = self._mw.sample_shift_ViewWidget.plotItem.axes['bottom']['item']

        # if duration display, reset to default ticks
        if self._mw.display_shift_vs_duration_RadioButton.isChecked():
            myAxisItem.setTicks(None)

        # otherwise, convert tick strings to clock format
        else:

            # determine size of the sample shift bottom axis item in pixels
            bounds = myAxisItem.mapRectFromParent(myAxisItem.geometry())
            span = (bounds.topLeft(), bounds.topRight())
            lengthInPixels = (span[1] - span[0]).manhattanLength()

            if lengthInPixels == 0:
                return -1
            if myAxisItem.range[0] < 0:
                return -1

            default_ticks = myAxisItem.tickValues(
                myAxisItem.range[0], myAxisItem.range[1], lengthInPixels)

            newticks = []
            for i, tick_level in enumerate(default_ticks):
                newticks_this_level = []
                ticks = tick_level[1]
                for ii, tick in enumerate(ticks):
                    # For major ticks, include date
                    if i == 0:
                        string = time.strftime("%H:%M (%d.%m.)", time.localtime(tick * 3600))
                        # (the axis is plotted in hours to get naturally better placed ticks.)

                    # for middle and minor ticks, just display clock time
                    else:
                        string = time.strftime("%H:%M", time.localtime(tick * 3600))

                    newticks_this_level.append((tick, string))
                newticks.append(newticks_this_level)

            myAxisItem.setTicks(newticks)
            return 0

    def _redraw_sample_shift(self):

        # Get trace data and calculate shifts in x,y,z
        poi_trace = self.poimanagerlogic().poi_list['sample'].get_position_history()

        # If duration display is checked, subtract initial time and convert to
        # mins or hours as appropriate
        if self._mw.display_shift_vs_duration_RadioButton.isChecked():
            time_shift_data = (poi_trace[:, 0] - poi_trace[0, 0])

            if np.max(time_shift_data) < 300:
                self._mw.sample_shift_ViewWidget.setLabel('bottom', 'Time elapsed', units='s')
            elif np.max(time_shift_data) < 7200:
                time_shift_data = time_shift_data / 60.0
                self._mw.sample_shift_ViewWidget.setLabel('bottom', 'Time elapsed', units='min')
            else:
                time_shift_data = time_shift_data / 3600.0
                self._mw.sample_shift_ViewWidget.setLabel('bottom', 'Time elapsed', units='hr')

        # Otherwise, take the actual time but divide by 3600 so that tickmarks
        # automatically fall on whole hours
        else:
            time_shift_data = poi_trace[:, 0] / 3600.0
            self._mw.sample_shift_ViewWidget.setLabel('bottom', 'Time', units='')

        # Subtract initial position to get shifts
        x_shift_data = (poi_trace[:, 1] - poi_trace[0, 1])
        y_shift_data = (poi_trace[:, 2] - poi_trace[0, 2])
        z_shift_data = (poi_trace[:, 3] - poi_trace[0, 3])

        # Plot data
        self.x_shift_plot.setData(time_shift_data, x_shift_data)
        self.y_shift_plot.setData(time_shift_data, y_shift_data)
        self.z_shift_plot.setData(time_shift_data, z_shift_data)

        self._redraw_clocktime_ticks()
