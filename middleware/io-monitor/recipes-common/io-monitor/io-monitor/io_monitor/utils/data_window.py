# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright (c) 2016 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

import collections


class DataCollectionWindow(object):
    # If the same data is seen repeatedly, then override with 0.0 as this
    # device is no longer updating
    CONSECUTIVE_SAME_DATA = 5

    def __init__(self, size, stuck_data_override=False):
        self.window = collections.deque(size*[0.0], size)
        self.timestamp = None
        self.last_value = 0.0
        self.total = 0.0
        self.avg = 0.0

        # iostat will produce a "stuck data" scenario when called with less
        # than two iterations and I/O has stopped on the device
        self.stuck_override = stuck_data_override
        self.stuck_count = 0

    def update(self, value, cap):
        # Handle stuck data and override
        if self.stuck_override and value != 0:
            if value == self.last_value:
                self.stuck_count += 1
            else:
                self.stuck_count = 0

        # Save latest value
        self.last_value = value

        if self.stuck_count > self.CONSECUTIVE_SAME_DATA:
            value = 0.0
        else:
            # Cap the values due to squirly data
            if cap > 0:
                value = min(value, cap)

        expired_value = self.window.pop()

        # Adjust push the new
        self.window.appendleft(value)

        # Adjust the sums
        self.total += (value - expired_value)

        # Adjust the average
        self.avg = max(0.0, self.total/len(self.window))

    def get_latest(self):
        return self.last_value

    def get_average(self):
        return self.avg
