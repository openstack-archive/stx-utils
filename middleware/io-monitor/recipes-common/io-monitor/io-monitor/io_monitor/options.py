# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright (c) 2016 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

from oslo_config import cfg

CONF = cfg.CONF

common_opts = [
    cfg.BoolOpt('daemon_mode', default=True,
                help=('Run as a daemon')),
    cfg.IntOpt('wait_time', default=1, min=1, max=59,
               help=('Sleep interval (in seconds) between iostat executions '
                     '[1..59]')),
    cfg.StrOpt('global_log_level',
               default='DEBUG',
               choices=['DEBUG', 'INFO', 'WARN', 'ERROR'],
               help=('Global debug level. Note: All monitors will be clipped '
                     'at this setting.'))
]


def add_common_opts():
    CONF.register_cli_opts(common_opts)
