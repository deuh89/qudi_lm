# -*- coding: utf-8 -*-

"""
Interface for a generic input stream of data points with fixed sampling rate and data type.

Copyright (c) 2021, the qudi developers. See the AUTHORS.md file at the top-level directory of this
distribution and on <https://github.com/Ulm-IQO/qudi-iqo-modules/>

This file is part of qudi.

Qudi is free software: you can redistribute it and/or modify it under the terms of
the GNU Lesser General Public License as published by the Free Software Foundation,
either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
See the GNU Lesser General Public License for more details.

You should have received a copy of the GNU Lesser General Public License along with qudi.
If not, see <https://www.gnu.org/licenses/>.
"""

import numpy as np
from enum import Enum
from abc import abstractmethod
from qudi.core.module import Base
from qudi.core.interface import ScalarConstraint


class DataInStreamInterface(Base):
    """
    Interface for a generic input stream of data points with fixed sampling rate and data type.

    You can choose if a preset number of samples is recorded and buffered for read or if samples
    are acquired continuously into a (circular) read buffer.
    """
    @property
    @abstractmethod
    def sample_rate(self):
        """
        The currently set sample rate

        @return float: current sample rate in Hz
        """
        pass

    @property
    @abstractmethod
    def data_type(self):
        """
        Read-only property.
        The data type of the stream data. Must be numpy type.

        @return type: stream data type (numpy type)
        """
        pass

    @property
    @abstractmethod
    def buffer_size(self):
        """
        The currently set buffer size.
        Buffer size corresponds to the number of samples per channel that can be buffered. So the
        actual buffer size in bytes can be estimated by:
            buffer_size * number_of_channels * size_in_bytes(data_type)

        @return int: current buffer size in samples per channel
        """
        pass


    @property
    @abstractmethod
    def all_settings(self):
        """
        Read-only property to return a dict containing all current settings and values that can be
        configured using the method "configure". Basically returns the same as "configure".

        @return dict: Dictionary containing all configurable settings
        """
        pass

    @property
    @abstractmethod
    def number_of_channels(self):
        """
        Read-only property to return the currently configured number of active data channels.

        @return int: the currently set number of channels
        """
        pass

    @property
    @abstractmethod
    def active_channels(self):
        """
        The currently configured data channel properties.
        Returns a dict with channel names as keys and corresponding StreamChannel instances as
        values.

        @return dict: currently active data channel properties with keys being the channel names
                      and values being the corresponding StreamChannel instances.
        """
        pass

    @property
    @abstractmethod
    def available_channels(self):
        """
        Read-only property to return the currently used data channel properties.
        Returns a dict with channel names as keys and corresponding StreamChannel instances as
        values.

        @return dict: data channel properties for all available channels with keys being the channel
                      names and values being the corresponding StreamChannel instances.
        """
        pass

    @property
    @abstractmethod
    def available_samples(self):
        """
        Read-only property to return the currently available number of samples per channel ready
        to read from buffer.

        @return int: Number of available samples per channel
        """
        pass

    @property
    @abstractmethod
    def buffer_overflown(self):
        """
        Read-only flag to check if the read buffer has overflown.
        In case of a circular buffer it indicates data loss.
        In case of a non-circular buffer the data acquisition should have stopped if this flag is
        coming up.
        Flag will only be reset after starting a new data acquisition.

        @return bool: Flag indicates if buffer has overflown (True) or not (False)
        """
        pass

    @property
    @abstractmethod
    def is_running(self):
        """
        Read-only flag indicating if the data acquisition is running.

        @return bool: Data acquisition is running (True) or not (False)
        """
        pass

    @abstractmethod
    def configure(self, sample_rate=None, active_channels=None,
                  total_number_of_samples=None, buffer_size=None):
        """
        Method to configure all possible settings of the data input stream.

        @param float sample_rate: The sample rate in Hz at which data points are acquired
        @param iterable active_channels: Iterable of channel names (str) to be read from.
        @param int total_number_of_samples: In case of a finite data stream, the total number of
                                            samples to read per channel
        @param int buffer_size: The size of the data buffer to pre-allocate in samples per channel

        @return dict: All current settings in a dict. Keywords are the same as kwarg names.
        """
        pass

    @abstractmethod
    def get_constraints(self):
        """
        Return the constraints on the settings for this data streamer.

        @return DataInStreamConstraints: Instance of DataInStreamConstraints containing constraints
        """
        pass

    @abstractmethod
    def start_stream(self):
        """
        Start the data acquisition and data stream.

        @return int: error code (0: OK, -1: Error)
        """
        pass

    @abstractmethod
    def stop_stream(self):
        """
        Stop the data acquisition and data stream.

        @return int: error code (0: OK, -1: Error)
        """
        pass

    @abstractmethod
    def read_data_into_buffer(self, buffer, number_of_samples=None):
        """
        Read data from the stream buffer into a 1D/2D numpy array given as parameter.
        In case of a single data channel the numpy array can be either 1D or 2D. In case of more
        channels the array must be 2D with the first index corresponding to the channel number and
        the second index serving as sample index:
            buffer.shape == (self.number_of_channels, number_of_samples)
        The numpy array must have the same data type as self.data_type.
        If number_of_samples is omitted it will be derived from buffer.shape[1]

        This method will not return until all requested samples have been read or a timeout occurs.

        @param numpy.ndarray buffer: The numpy array to write the samples to
        @param int number_of_samples: optional, number of samples to read per channel. If omitted,
                                      this number will be derived from buffer axis 1 size.

        @return int: Number of samples read into buffer; negative value indicates error
                     (e.g. read timeout)
        """
        pass

    @abstractmethod
    def read_available_data_into_buffer(self, buffer):
        """
        Read data from the stream buffer into a 1D/2D numpy array given as parameter.
        In case of a single data channel the numpy array can be either 1D or 2D. In case of more
        channels the array must be 2D with the first index corresponding to the channel number and
        the second index serving as sample index:
            buffer.shape == (self.number_of_channels, number_of_samples)
        The numpy array must have the same data type as self.data_type.

        This method will read all currently available samples into buffer. If number of available
        samples exceed buffer size, read only as many samples as fit into the buffer.

        @param numpy.ndarray buffer: The numpy array to write the samples to

        @return int: Number of samples read into buffer; negative value indicates error
                     (e.g. read timeout)
        """
        pass

    @abstractmethod
    def read_data(self, number_of_samples=None):
        """
        Read data from the stream buffer into a 2D numpy array and return it.
        The arrays first index corresponds to the channel number and the second index serves as
        sample index:
            return_array.shape == (self.number_of_channels, number_of_samples)
        The numpy arrays data type is the one defined in self.data_type.
        If number_of_samples is omitted all currently available samples are read from buffer.

        This method will not return until all requested samples have been read or a timeout occurs.

        If no samples are available, this method will immediately return an empty array.
        You can check for a failed data read if number_of_samples != <return_array>.shape[1].

        @param int number_of_samples: optional, number of samples to read per channel. If omitted,
                                      all available samples are read from buffer.

        @return numpy.ndarray: The read samples in a numpy array
        """
        pass

    @abstractmethod
    def read_single_point(self):
        """
        This method will initiate a single sample read on each configured data channel.
        In general this sample may not be acquired simultaneous for all channels and timing in
        general can not be assured. Us this method if you want to have a non-timing-critical
        snapshot of your current data channel input.
        May not be available for all devices.
        The returned 1D numpy array will contain one sample for each channel.

        @return numpy.ndarray: 1D array containing one sample for each channel. Empty array
                               indicates error.
        """
        pass


class StreamChannelType(Enum):
    DIGITAL = 0
    ANALOG = 1



class StreamChannel:
    def __init__(self, name, type, unit=None):
        self._name = str(name)
        self._type = StreamChannelType(type)
        if unit is None:
            if self._type == StreamChannelType.ANALOG:
                self._unit = 'V'
            elif self._type == StreamChannelType.DIGITAL:
                self._unit = 'counts'
        else:
            self._unit = str(unit)

    @property
    def name(self):
        return self._name

    @property
    def type(self):
        return self._type

    @property
    def unit(self):
        return self._unit

    @unit.setter
    def unit(self, new_unit):
        if isinstance(new_unit, str):
            self._unit = str(new_unit)
        else:
            raise TypeError('StreamChannel unit property must be str.')
        return

    def copy(self):
        return StreamChannel(name=self.name, type=self.type, unit=self.unit)


class DataInStreamConstraints:
    """
    Collection of constraints for hardware modules implementing SimpleDataInterface.
    """
    def __init__(self, digital_channels=None, analog_channels=None, analog_sample_rate=None,
                 digital_sample_rate=None, combined_sample_rate=None, read_block_size=None, 
                 data_type=None, allow_circular_buffer=None):
        if digital_channels is None:
            self.digital_channels = dict()
        else:
            self.digital_channels = tuple(ch.copy() for ch in digital_channels)

        if analog_channels is None:
            self.analog_channels = dict()
        else:
            self.analog_channels = tuple(ch.copy() for ch in analog_channels)

        if isinstance(analog_sample_rate, ScalarConstraint):
            self.analog_sample_rate = ScalarConstraint(**vars(analog_sample_rate))
        elif isinstance(analog_sample_rate, dict):
            self.analog_sample_rate = ScalarConstraint(**analog_sample_rate)
        else:
            self.analog_sample_rate = ScalarConstraint(min=1, max=np.inf, step=1, default=1)

        if isinstance(digital_sample_rate, ScalarConstraint):
            self.digital_sample_rate = ScalarConstraint(**vars(digital_sample_rate))
        elif isinstance(digital_sample_rate, dict):
            self.digital_sample_rate = ScalarConstraint(**digital_sample_rate)
        else:
            self.digital_sample_rate = ScalarConstraint(min=1, max=np.inf, step=1, default=1)

        if isinstance(combined_sample_rate, ScalarConstraint):
            self.combined_sample_rate = ScalarConstraint(**vars(combined_sample_rate))
        elif isinstance(combined_sample_rate, dict):
            self.combined_sample_rate = ScalarConstraint(**combined_sample_rate)
        else:
            self.combined_sample_rate = ScalarConstraint(min=1, max=np.inf, step=1, default=1)

        if isinstance(read_block_size, ScalarConstraint):
            self.read_block_size = ScalarConstraint(**vars(read_block_size))
        elif isinstance(read_block_size, dict):
            self.read_block_size = ScalarConstraint(**read_block_size)
        else:
            self.read_block_size = ScalarConstraint(min=1, max=np.inf, step=1, default=1)

        if data_type is None:
            self.data_type = np.float64
        else:
            self.data_type = np.dtype(data_type)

        self.allow_circular_buffer = bool(allow_circular_buffer)
        return

    def copy(self):
        return DataInStreamConstraints(**vars(self))
