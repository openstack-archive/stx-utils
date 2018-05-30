#
# Copyright (c) 2016 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

import oslo_i18n as i18n

DOMAIN = 'io_monitor'
_translators = i18n.TranslatorFactory(domain=DOMAIN)

# The primary translation function using the well-known name "_"
_ = _translators.primary

# HOST OS

WRLINUX = 'wrlinux'
CENTOS = 'CentOS Linux'

# ALARMS

# Reasons for alarm
ALARM_REASON_BUILDING = _('Cinder I/O Congestion is above normal range and '
                          'is building')
ALARM_REASON_CONGESTED = _('Cinder I/O Congestion is high and impacting '
                           'guest performance')

# Repair actions for alarm
REPAIR_ACTION_MAJOR_ALARM = _('Reduce the I/O load on the Cinder LVM '
                              'backend. Use Cinder QoS mechanisms on high '
                              'usage volumes.')
REPAIR_ACTION_CRITICAL_ALARM = _('Reduce the I/O load on the Cinder LVM '
                                 'backend. Cinder actions may fail until '
                                 'congestion is reduced. Use Cinder QoS '
                                 'mechanisms on high usage volumes.')

# All cinder volume group device mapper names begin with this
CINDER_DM_PREFIX = 'cinder--volumes'
