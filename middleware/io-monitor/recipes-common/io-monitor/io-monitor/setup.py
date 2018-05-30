#!/usr/bin/env python
#
# Copyright (c) 2016 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#


import setuptools

setuptools.setup(name='io_monitor',
                 version='1.0.0',
                 description='IO Monitor',
                 license='Apache-2.0',
                 packages=['io_monitor', 'io_monitor.monitors',
                           'io_monitor.monitors.cinder', 'io_monitor.utils'],
                 entry_points={
                 })
