# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright (c) 2016 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

import logging
import os

from io_monitor.constants import DOMAIN
from io_monitor.utils.data_window import DataCollectionWindow

LOG = logging.getLogger(DOMAIN)


class DeviceDataCollector(object):
    # Moving average windows
    MA_WINDOW_SMA = 0
    MA_WINDOW_MED = 1
    MA_WINDOW_LAR = 2

    # Device status
    STATUS_NORMAL = "N"
    STATUS_BUILDING = "B"
    STATUS_CONGESTED = "L"

    # Data tracked
    DATA_IOPS = "iops"
    DATA_AWAIT = "await"

    def __init__(self, device_node, data_elements,
                 size_sma, size_med, size_lar):

        self.node = device_node

        if os.path.exists('/sys/block/' + self.node + '/dm/name'):
            self.name = open('/sys/block/' + self.node + '/dm/name',
                             'r').read().rstrip()
        else:
            self.name = self.node

        self.data_dict = {}
        self.data_caps = {self.DATA_AWAIT: -1, self.DATA_IOPS: -1}
        self.timestamp = None

        self.congestion_status = self.STATUS_NORMAL
        self.congestion_await_minimal_spike = -1
        self.congestion_await_sustained = -1

        for element in data_elements:
            self.data_dict.update({element: [
                DataCollectionWindow(size_sma, stuck_data_override=True),
                DataCollectionWindow(size_med, stuck_data_override=True),
                DataCollectionWindow(size_lar, stuck_data_override=True)]})

    def update_congestion_status(self):
        # Bail if threshold is not set
        if self.congestion_await_sustained == -1:
            return

        ma_sma = self.get_average(self.DATA_AWAIT, self.MA_WINDOW_SMA)
        ma_med = self.get_average(self.DATA_AWAIT, self.MA_WINDOW_MED)
        ma_lar = self.get_average(self.DATA_AWAIT, self.MA_WINDOW_LAR)

        # Set the congestion status based on await moving average
        if self.congestion_status is self.STATUS_NORMAL:
            if ma_sma > self.congestion_await_sustained:
                self.congestion_status = self.STATUS_BUILDING

        if self.congestion_status is self.STATUS_BUILDING:
            if ma_lar > self.congestion_await_sustained:
                self.congestion_status = self.STATUS_CONGESTED
                LOG.warn("Node %s (%s) is experiencing high await times."
                         % (self.node, self.name))
            elif ma_sma < self.congestion_await_sustained:
                self.congestion_status = self.STATUS_NORMAL

        if self.congestion_status is self.STATUS_CONGESTED:
            if ma_med < self.congestion_await_sustained:
                self.congestion_status = self.STATUS_BUILDING

    def update_data(self, ts, element, value):
        self.timestamp = ts

        # LOG.debug("%s: e = %s, v= %f" % (self.node, element, value))
        for w in [self.MA_WINDOW_SMA,
                  self.MA_WINDOW_MED,
                  self.MA_WINDOW_LAR]:
            self.data_dict[element][w].update(value, self.data_caps[element])

    def get_latest(self, element):
        if element not in self.data_dict:
            LOG.error("Error: invalid element requested = %s" % element)
            return 0

        return self.data_dict[element][self.MA_WINDOW_SMA].get_latest()

    def get_average(self, element, window):
        if window not in [self.MA_WINDOW_SMA,
                          self.MA_WINDOW_MED,
                          self.MA_WINDOW_LAR]:
            LOG.error("WindowError: invalid window requested = %s" % window)
            return 0

        if element not in self.data_dict:
            LOG.error("Error: invalid element requested = %s" % element)
            return 0

        return self.data_dict[element][window].get_average()

    def is_data_stale(self, ts):
        return not (ts == self.timestamp)

    def get_congestion_status(self, debug=False):

        if debug:
            ma_sma = self.get_average(self.DATA_AWAIT, self.MA_WINDOW_SMA)
            ma_med = self.get_average(self.DATA_AWAIT, self.MA_WINDOW_MED)
            ma_lar = self.get_average(self.DATA_AWAIT, self.MA_WINDOW_LAR)

            LOG.debug("%s [ %6.2f %6.2f %6.2f ] %d" %
                      (self.node, ma_sma, ma_med, ma_lar,
                       self.congestion_await_sustained))

        return self.congestion_status

    def set_data_caps(self, element, cap):
        if element in self.data_caps:
            self.data_caps[element] = cap

    def set_congestion_thresholds(self, await_minimal_spike,
                                  await_sustained_congestion):
        self.congestion_await_minimal_spike = await_minimal_spike
        self.congestion_await_sustained = await_sustained_congestion

    def get_element_windows_avg_list(self, element):
        return [self.get_average(element, self.MA_WINDOW_SMA),
                self.get_average(element, self.MA_WINDOW_MED),
                self.get_average(element, self.MA_WINDOW_LAR)]

    def get_element_windows_avg_string(self, element):
        return "%s [ %9.2f, %9.2f, %9.2f ]" % (
            element,
            self.get_average(element, self.MA_WINDOW_SMA),
            self.get_average(element, self.MA_WINDOW_MED),
            self.get_average(element, self.MA_WINDOW_LAR))
