# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright (c) 2016-2017 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

import collections
import logging
import pyudev
import math
import operator
import os
import platform
import re
import subprocess

from fm_api import fm_api
from fm_api import constants as fm_constants
from io_monitor import constants
from io_monitor.constants import DOMAIN
from io_monitor.utils.data_collector import DeviceDataCollector
from io_monitor.constants import _
from oslo_config import cfg

ccm_opts = [
    cfg.IntOpt('ssd_small_window_size',
               default=30,
               help=('SSD: Small moving average window size (in seconds).')),
    cfg.IntOpt('ssd_medium_window_size',
               default=60,
               help=('SSD: Medium moving average window size (in seconds).')),
    cfg.IntOpt('ssd_large_window_size',
               default=90,
               help=('SSD: Large moving average window size (in seconds).')),
    cfg.IntOpt('ssd_thresh_sustained_await',
               default=1000,
               help=('SSD: Value required in a moving average window to '
                     'trigger next state.')),
    cfg.IntOpt('ssd_thresh_max_await',
               default=5000,
               help=('SSD: Max await time. Anomalous data readings are clipped'
                     ' to this.')),
    cfg.IntOpt('hdd_small_window_size',
               default=120,
               help=('HDD: Small moving average window size (in seconds).')),
    cfg.IntOpt('hdd_medium_window_size',
               default=180,
               help=('HDD: Medium moving average window size (in seconds).')),
    cfg.IntOpt('hdd_large_window_size',
               default=240,
               help=('HDD: Large moving average window size (in seconds).')),
    cfg.IntOpt('hdd_thresh_sustained_await',
               default=1500,
               help=('HDD: Value required in a moving average window to '
                     'trigger next state.')),
    cfg.IntOpt('hdd_thresh_max_await',
               default=5000,
               help=('HDD: Max await time. Anomalous data readings are clipped'
                     ' to this.')),
    cfg.StrOpt('log_level',
               default='INFO',
               choices=('ERROR', 'WARN', 'INFO', 'DEBUG'),
               help=('Monitor debug level. Note: global level must be'
                     ' equialent or lower.')),
    cfg.FloatOpt('status_log_rate_modifier', default=0.2,
                 help=('Modify how often status messages appear in the log.'
                       '0.0 is never, 1.0 is for every iostat execution.')),
    cfg.BoolOpt('generate_fm_alarms', default=True,
                help=('Enable FM Alarm generation')),
    cfg.IntOpt('fm_alarm_debounce', default=5,
               help=('Number of consecutive same congestion states seen '
                     'before raising/clearing alarms.')),
    cfg.BoolOpt('output_write_csv', default=False,
                help=('Write monitor data to a csv for analysis')),
    cfg.StrOpt('output_csv_dir', default='/tmp',
               help=('Directory where monitor output will be located.')),
]

CONF = cfg.CONF
CONF.register_opts(ccm_opts, group="cinder_congestion")

LOG = logging.getLogger(DOMAIN)


class CinderCongestionMonitor(object):
    # Congestion States
    STATUS_NORMAL = "Normal"
    STATUS_BUILDING = "Building"
    STATUS_CONGESTED = "Limiting"

    # disk type
    CINDER_DISK_SSD = 0
    CINDER_DISK_HDD = 1

    def __init__(self):
        # Setup logging
        level_dict = {'ERROR': logging.ERROR,
                      'WARN': logging.WARN,
                      'INFO': logging.INFO,
                      'DEBUG': logging.DEBUG}

        if CONF.cinder_congestion.log_level in level_dict.keys():
            LOG.setLevel(level_dict[CONF.cinder_congestion.log_level])
        else:
            LOG.setLevel(logging.INFO)

        LOG.info("Initializing %s..." % self.__class__.__name__)

        # DRBD file
        self.drbd_file = '/etc/drbd.d/drbd-cinder.res'

        # iostat parsing regex
        self.ts_regex = re.compile(r"(\d{2}/\d{2}/\d{2,4}) "
                                   "(\d{2}:\d{2}:\d{2})")
        self.device_regex = re.compile(
            r"(\w+-?\w+)\s+(\d+.\d+)\s+(\d+.\d+)\s+(\d+.\d+)\s+(\d+.\d+)"
            "\s+(\d+.\d+)\s+(\d+.\d+)\s+(\d+.\d+)\s+(\d+.\d+)\s+(\d+.\d+)\s+"
            "(\d+.\d+)\s+(\d+.\d+)\s+(\d+.\d+)\s+(\d+.\d+)")

        # window sizes
        self.s_window_sec = CONF.cinder_congestion.ssd_small_window_size
        self.m_window_sec = CONF.cinder_congestion.ssd_medium_window_size
        self.l_window_sec = CONF.cinder_congestion.ssd_large_window_size

        # state variables
        self.latest_time = None
        self.congestion_status = self.STATUS_NORMAL

        # init data collector
        self.device_dict = {}

        # devices
        self.phys_cinder_device = None
        self.base_cinder_devs = []
        self.base_cinder_tracking_devs = []
        self.non_cinder_dynamic_devs = ['drbd0', 'drbd1', 'drbd2', 'drbd3',
                                        'drbd5']
        self.non_cinder_phys_devs = []

        # set the default operational scenarios
        self.await_minimal_spike = CONF.cinder_congestion.ssd_thresh_max_await
        self.await_sustained_congestion = (
            CONF.cinder_congestion.ssd_thresh_sustained_await)

        # FM
        self.fm_api = fm_api.FaultAPIs()
        self.fm_state_count = collections.Counter()

        # CSV handle
        self.csv = None

        # status logging
        self.status_skip_count = 0

        # to compare with current g_count
        self.last_g_count = 0

        message_rate = math.ceil(60 / (CONF.wait_time+1))
        self.status_skip_total = math.ceil(
            message_rate/(message_rate *
                          CONF.cinder_congestion.status_log_rate_modifier))
        LOG.info("Display status message at %d per minute..." %
                 (message_rate *
                  CONF.cinder_congestion.status_log_rate_modifier))

        # Clear any exiting alarms
        self._clear_fm()

    def _is_number(self, s):
        try:
            float(s)
            return True
        except ValueError:
            return False

    def command(self, arguments, **kwargs):
        """ Execute e command and capture stdout, stderr & return code """
        process = subprocess.Popen(
            arguments,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **kwargs)
        out, err = process.communicate()
        return out, err, process.returncode

    def device_path_to_device_node(self, device_path):
        try:
            output, _, _ = self.command(["udevadm", "settle", "-E",
                                        device_path])
            out, err, retcode = self. command(["readlink", "-f", device_path])
            out = out.rstrip()
        except Exception as e:
            return None

        return out

    def _get_disk_type(self, device_node):
        if device_node:
            proc_device_file = '/sys/block/' + device_node + \
                               '/queue/rotational'
            if os.path.exists(proc_device_file):
                with open(proc_device_file) as fileobject:
                    for line in fileobject:
                        return int(line.rstrip())

        # If the disk is unknown assume an SSD.
        return self.CINDER_DISK_SSD


    def _is_cinder_related_device(self,device_node):
        name = ""
        if device_node:
            proc_device_file = '/sys/block/' + device_node + \
                               '/dm/name'

            if os.path.exists(proc_device_file):
                with open(proc_device_file) as fileobject:
                    for line in fileobject:
                        name = line.rstrip()

        if constants.CINDER_DM_PREFIX in name:
            return True

        return False

    def _is_cinder_backing_device(self, device_node):
        name = ""
        if device_node:
            proc_device_file = '/sys/block/' + device_node + \
                               '/dm/name'
            if os.path.exists(proc_device_file):
                with open(proc_device_file) as fileobject:
                    for line in fileobject:
                        name = line.rstrip()

        if any(s in name for s in ['pool', 'anchor']):
            if device_node not in self.base_cinder_devs:
                self.base_cinder_devs.append(device_node)
                if any(s in name for s in ['tdata', 'tmeta']):
                    if device_node not in self.base_cinder_tracking_devs:
                        self.base_cinder_tracking_devs.append(device_node)

                LOG.info("Cinder Base Devices = %s; Tracking %s" % (
                    self.base_cinder_devs, self.base_cinder_tracking_devs))
            return True

        return False

    def _determine_cinder_devices(self):
        # Check to see if we have DRBD device we are syncing
        if os.path.exists(self.drbd_file):

            # grab the data
            with open(self.drbd_file) as fileobject:

                drbd_dev_regex = re.compile(r"device\s+/dev/(\w+);")
                drbd_disk_path_regex = re.compile(
                    r"disk\s+\"(/dev/disk/by-path/(.+))\";")
                drbd_disk_node_regex = re.compile(r"/dev/(\w+)")
                partition_regex = re.compile(r"(sd\w+)\d+")

                for line in fileobject:
                    m = drbd_dev_regex.match(line.strip())
                    if m:
                        self.base_cinder_devs.append(m.group(1))

                    m = drbd_disk_path_regex.match(line.strip())
                    if m:
                        drbd_disk = self.device_path_to_device_node(m.group(1))

                        drbd_disk_sd = drbd_disk_node_regex.match(drbd_disk)
                        if drbd_disk_sd:
                            self.base_cinder_devs.append(drbd_disk_sd.group(1))

                            d = partition_regex.match(drbd_disk_sd.group(1))
                            if d:
                                self.phys_cinder_device = d.group(1)
                                self.base_cinder_devs.append(d.group(1))

            # Which host OS?
            if platform.linux_distribution()[0] == constants.WRLINUX:
                dm_major = 252
            else:
                dm_major = 253

            # Grab the device mapper devices and pull out the base cinder
            # devices
            dmsetup_regex = re.compile(r'^([\w-]+)\s+\((\d+):(\d+)\)')

            dmsetup_command = 'dmsetup ls'
            dmsetup_process = subprocess.Popen(dmsetup_command,
                                               stdout=subprocess.PIPE,
                                               shell=True)
            dmsetup_output = dmsetup_process.stdout.read()
            lines = dmsetup_output.split('\n')
            for l in lines:
                m = dmsetup_regex.match(l.strip())
                if m:
                    if m.group(2) == str(dm_major):
                        # LOG.debug("%s %s %s" % (m.group(1),
                        #                         m.group(2),
                        #                         m.group(3)))
                        if constants.CINDER_DM_PREFIX in m.group(1):
                            if 'pool' in m.group(1) or 'anchor' in m.group(1):
                                self.base_cinder_devs.append(
                                    "dm-" + m.group(3))
                            if 'tdata' in m.group(1) or 'tmeta' in m.group(1):
                                self.base_cinder_tracking_devs.append(
                                    "dm-" + m.group(3))
                        else:
                            self.non_cinder_dynamic_devs.append(
                                "dm-" + m.group(3))

            # If the tracking devs are non existant, then we didn't find any
            # thin pool entries. Therefore we are thickly provisioned and need
            # to track the physical device
            if len(self.base_cinder_tracking_devs) == 0:
                self.base_cinder_tracking_devs.append(
                    self.phys_cinder_device)

        # Use UDEV info to grab all phyical disks
        context = pyudev.Context()
        for device in context.list_devices(subsystem='block',
                                           DEVTYPE='disk'):
            if device['MAJOR'] == '8':
                device = str(os.path.basename(device['DEVNAME']))
                if device != self.phys_cinder_device:
                    self.non_cinder_phys_devs.append(device)

    def _update_device_stats(self, ts, device, current_iops, current_await):
        if device not in self.device_dict:
             # For AIO systems nova-local will be provisioned later and
             # differently based on the instance_backing value for the compute
             # functionality. Check for cinder specific dm devices and ignore
             # all others
            if not self._is_cinder_related_device(device):
                return
            self._is_cinder_backing_device(device)
            self.device_dict.update(
                {device: DeviceDataCollector(
                    device,
                    [DeviceDataCollector.DATA_IOPS,
                     DeviceDataCollector.DATA_AWAIT],
                    self.s_window_sec,
                    self.m_window_sec,
                    self.l_window_sec)})
            self.device_dict[device].set_data_caps(
                DeviceDataCollector.DATA_AWAIT,
                self.await_minimal_spike)
            self.device_dict[device].set_congestion_thresholds(
                self.await_minimal_spike,
                self.await_sustained_congestion)

        self.device_dict[device].update_data(ts,
                                             DeviceDataCollector.DATA_IOPS,
                                             current_iops)
        self.device_dict[device].update_data(ts,
                                             DeviceDataCollector.DATA_AWAIT,
                                             current_await)
        self.device_dict[device].update_congestion_status()

    def is_system_monitorable(self):
        if not os.path.exists(self.drbd_file):
            LOG.error("%s does not exist" % self.drbd_file)
            return False

        # Discover devices on this host
        self._determine_cinder_devices()

        # Get the cinder disk type and set the monitor values accordingly
        disk_type = self._get_disk_type(self.phys_cinder_device)
        if disk_type:
            self.s_window_sec = CONF.cinder_congestion.hdd_small_window_size
            self.m_window_sec = CONF.cinder_congestion.hdd_medium_window_size
            self.l_window_sec = CONF.cinder_congestion.hdd_large_window_size
            self.await_minimal_spike = (
                CONF.cinder_congestion.hdd_thresh_max_await)
            self.await_sustained_congestion = (
                CONF.cinder_congestion.hdd_thresh_sustained_await)
        else:
            self.s_window_sec = CONF.cinder_congestion.ssd_small_window_size
            self.m_window_sec = CONF.cinder_congestion.ssd_medium_window_size
            self.l_window_sec = CONF.cinder_congestion.ssd_large_window_size
            self.await_minimal_spike = (
                CONF.cinder_congestion.ssd_thresh_max_await)
            self.await_sustained_congestion = (
                CONF.cinder_congestion.ssd_thresh_sustained_await)

        LOG.info("Physical Cinder Disk = %s - %s" %
                 (self.phys_cinder_device,
                  "HDD" if disk_type else "SSD"))
        LOG.info("Cinder Base Devices = %s; Tracking %s" % (
            self.base_cinder_devs, self.base_cinder_tracking_devs))
        LOG.info("Non-Cinder Devices = %s" % (
            self.non_cinder_dynamic_devs + self.non_cinder_phys_devs))

        return True

    def get_operational_thresholds(self):
        return (self.await_minimal_spike,
                self.await_sustained_congestion)

    def set_operational_thresholds(self,
                                   await_minimal_spike,
                                   await_sustained_congestion):
        if await_minimal_spike:
            self.await_minimal_spike = await_minimal_spike
        if await_sustained_congestion:
            self.await_sustained_congestion = await_sustained_congestion

    def _flush_stale_devices(self):
        for d in self.device_dict.keys():
            if self.device_dict[d].is_data_stale(self.latest_time):
                self.device_dict.pop(d, None)

    def _log_device_data_windows(self, device):
        LOG.debug("%-6s: %s %s" % (
            device,
            self.device_dict[device].get_element_windows_avg_string(
                DeviceDataCollector.DATA_AWAIT),
            self.device_dict[device].get_element_windows_avg_string(
                DeviceDataCollector.DATA_IOPS)))

    def _log_congestion_status(self, congestion_data):
        congestion_data.c_freq_dict.update(
            dict.fromkeys(
                set(['N', 'B', 'L']).difference(
                    congestion_data.c_freq_dict), 0))
        congestion_data.g_freq_dict.update(
            dict.fromkeys(
                set(['N', 'B', 'L']).difference(
                    congestion_data.g_freq_dict), 0))

        LOG.info("Status (%-8s): Cinder Devs IOPS [ %10.2f, %10.2f, %10.2f ] "
                 "Guests Counts %s; Guest Await[ %10.2f, %10.2f, %10.2f ]" % (
                     congestion_data.status,
                     congestion_data.c_iops_avg_list[0],
                     congestion_data.c_iops_avg_list[1],
                     congestion_data.c_iops_avg_list[2],
                     dict(congestion_data.g_freq_dict),
                     congestion_data.g_await_avg_list[0],
                     congestion_data.g_await_avg_list[1],
                     congestion_data.g_await_avg_list[2]))

    def _determine_congestion_state(self):

        # Analyze devices
        cinder_congestion_freq = collections.Counter()
        cinder_iops_avg = [0.0, 0.0, 0.0]
        guest_congestion_freq = collections.Counter()
        guest_await_avg = [0.0, 0.0, 0.0]

        for d, dc in self.device_dict.iteritems():
            if d in self.base_cinder_devs:
                if d in self.base_cinder_tracking_devs:
                    cinder_congestion_freq.update(dc.get_congestion_status())
                    cinder_iops_avg = map(operator.add,
                                          cinder_iops_avg,
                                          dc.get_element_windows_avg_list(
                                              DeviceDataCollector.DATA_IOPS))
                    # LOG.debug("C: %s " % cinder_iops_avg)
                    # self._log_device_data_windows(d)

            elif d not in (self.base_cinder_devs +
                           self.non_cinder_dynamic_devs +
                           self.non_cinder_phys_devs):
                guest_congestion_freq.update(
                    dc.get_congestion_status(debug=True))
                guest_await_avg = map(operator.add,
                                      guest_await_avg,
                                      dc.get_element_windows_avg_list(
                                          DeviceDataCollector.DATA_AWAIT))
                # LOG.debug("G: %s " % guest_await_avg)
                # self._log_device_data_windows(d)

        if list(cinder_congestion_freq.elements()):
            cinder_iops_avg[:] = [i/len(list(
                cinder_congestion_freq.elements())) for i in cinder_iops_avg]

        if list(guest_congestion_freq.elements()):
            guest_await_avg[:] = [i/len(list(
                guest_congestion_freq.elements())) for i in guest_await_avg]

        self.congestion_status = self.STATUS_NORMAL
        if DeviceDataCollector.STATUS_BUILDING in guest_congestion_freq:
            self.congestion_status = self.STATUS_BUILDING
        if DeviceDataCollector.STATUS_CONGESTED in guest_congestion_freq:
            self.congestion_status = self.STATUS_CONGESTED

        congestion_data = collections.namedtuple("congestion_data",
                                                 ["timestamp", "status",
                                                  "c_freq_dict",
                                                  "c_iops_avg_list",
                                                  "g_count",
                                                  "g_freq_dict",
                                                  "g_await_avg_list"])

        return congestion_data(self.latest_time,
                               self.congestion_status,
                               cinder_congestion_freq,
                               cinder_iops_avg,
                               sum(guest_congestion_freq.values()),
                               guest_congestion_freq,
                               guest_await_avg)

    def _clear_fm(self):
        building = fm_constants.FM_ALARM_ID_STORAGE_CINDER_IO_BUILDING
        limiting = fm_constants.FM_ALARM_ID_STORAGE_CINDER_IO_LIMITING

        entity_instance_id = "cinder_io_monitor"
        ccm_alarm_ids = [building, limiting]

        existing_alarms = []
        for alarm_id in ccm_alarm_ids:
            alarm_list = self.fm_api.get_faults_by_id(alarm_id)
            if not alarm_list:
                continue
            for alarm in alarm_list:
                existing_alarms.append(alarm)

        if len(existing_alarms) > 1:
            LOG.warn("WARNING: we have more than one existing alarm")

        for a in existing_alarms:
            self.fm_api.clear_fault(a.alarm_id, entity_instance_id)
            LOG.info(
                _("Clearing congestion alarm {} - severity: {}, "
                  "reason: {}, service_affecting: {}").format(
                      a.uuid, a.severity, a.reason_text, True))

    def _update_fm(self, debounce_count, override=None):

        building = fm_constants.FM_ALARM_ID_STORAGE_CINDER_IO_BUILDING
        limiting = fm_constants.FM_ALARM_ID_STORAGE_CINDER_IO_LIMITING

        if override:
            self.congestion_status = override

        # Update the status count
        self.fm_state_count.update(self.congestion_status[0])

        # Debounce alarms: If I have more than one congestion type then clear
        # the counts as we have crossed a threshold
        if len(self.fm_state_count) > 1:
            self.fm_state_count.clear()
            self.fm_state_count.update(self.congestion_status[0])
            return

        # Debounce alarms: Make sure we have see this alarm state for a specifc
        # number of samples
        count = self.fm_state_count.itervalues().next()
        if count < debounce_count:
            return

        # We are past the debounce state. Now take action.
        entity_instance_id = "cinder_io_monitor"
        ccm_alarm_ids = [building, limiting]

        existing_alarms = []
        for alarm_id in ccm_alarm_ids:
            alarm_list = self.fm_api.get_faults_by_id(alarm_id)
            if not alarm_list:
                continue
            for alarm in alarm_list:
                existing_alarms.append(alarm)

        if len(existing_alarms) > 1:
            LOG.warn("WARNING: we have more than one existing alarm")

        if self.congestion_status is self.STATUS_NORMAL:
            for a in existing_alarms:
                self.fm_api.clear_fault(a.alarm_id, entity_instance_id)
                LOG.info(
                    _("Clearing congestion alarm {} - severity: {}, "
                      "reason: {}, service_affecting: {}").format(
                          a.uuid, a.severity, a.reason_text, True))

        elif self.congestion_status is self.STATUS_BUILDING:
            alarm_is_raised = False
            for a in existing_alarms:
                if a.alarm_id != building:
                    self.fm_api.clear_fault(a.alarm_id, entity_instance_id)
                    LOG.info(
                        _("Clearing congestion alarm {} - severity: {}, "
                          "reason: {}, service_affecting: {}").format(
                              a.uuid, a.severity, a.reason_text, True))
                else:
                    alarm_is_raised = True

            if not alarm_is_raised:
                severity = fm_constants.FM_ALARM_SEVERITY_MAJOR
                reason_text = constants.ALARM_REASON_BUILDING

                fault = fm_api.Fault(
                    alarm_id=building,
                    alarm_type=fm_constants.FM_ALARM_TYPE_2,
                    alarm_state=fm_constants.FM_ALARM_STATE_SET,
                    entity_type_id=fm_constants.FM_ENTITY_TYPE_CLUSTER,
                    entity_instance_id=entity_instance_id,
                    severity=severity,
                    reason_text=reason_text,
                    probable_cause=fm_constants.ALARM_PROBABLE_CAUSE_8,
                    proposed_repair_action=constants.REPAIR_ACTION_MAJOR_ALARM,
                    service_affecting=True)
                alarm_uuid = self.fm_api.set_fault(fault)
                if alarm_uuid:
                    LOG.info(
                        _("Created congestion alarm {} - severity: {}, "
                          "reason: {}, service_affecting: {}").format(
                              alarm_uuid, severity, reason_text, True))
                else:
                    LOG.error(
                        _("Failed to create congestion alarm - severity: {},"
                          "reason: {}, service_affecting: {}").format(
                              severity, reason_text, True))

        elif self.congestion_status is self.STATUS_CONGESTED:
            alarm_is_raised = False
            for a in existing_alarms:
                if a.alarm_id != limiting:
                    self.fm_api.clear_fault(a.alarm_id, entity_instance_id)
                    LOG.info(
                        _("Clearing congestion alarm {} - severity: {}, "
                          "reason: {}, service_affecting: {}").format(
                              a.uuid, a.severity, a.reason_text, True))
                else:
                    alarm_is_raised = True

            if not alarm_is_raised:
                severity = fm_constants.FM_ALARM_SEVERITY_CRITICAL
                reason_text = constants.ALARM_REASON_CONGESTED
                repair = constants.REPAIR_ACTION_CRITICAL_ALARM
                fault = fm_api.Fault(
                    alarm_id=limiting,
                    alarm_type=fm_constants.FM_ALARM_TYPE_2,
                    alarm_state=fm_constants.FM_ALARM_STATE_SET,
                    entity_type_id=fm_constants.FM_ENTITY_TYPE_CLUSTER,
                    entity_instance_id=entity_instance_id,
                    severity=severity,
                    reason_text=reason_text,
                    probable_cause=fm_constants.ALARM_PROBABLE_CAUSE_8,
                    proposed_repair_action=repair,
                    service_affecting=True)
                alarm_uuid = self.fm_api.set_fault(fault)
                if alarm_uuid:
                    LOG.info(
                        _("Created congestion alarm {} - severity: {}, "
                          "reason: {}, service_affecting: {}").format(
                              alarm_uuid, severity, reason_text, True))
                else:
                    LOG.error(
                        _("Failed to congestion storage alarm - severity: {},"
                          "reason: {}, service_affecting: {}").format(
                              severity, reason_text, True))

    def _create_output(self, output_dir, congestion_data):
        if not self.csv:
            LOG.info("Creating output")
            if os.path.exists(output_dir):
                if output_dir.endswith('/'):
                    fn = output_dir + 'ccm.csv'
                else:
                    fn = output_dir + '/ccm.csv'
            else:
                fn = '/tmp/ccm.csv'
            try:
                self.csv = open(fn, 'w')
            except Exception as e:
                raise e

            self.csv.write("Timestamp, Congestion Status, "
                           "Cinder Devs Normal, "
                           "Cinder Devs Building, Cinder Devs Limiting,"
                           "Cinder IOPS Small, "
                           "Cinder IOPS Med, Cinder IOPS Large,"
                           "Guest Vols Normal, "
                           "Guest Vols Building, Guest Vols Limiting,"
                           "Guest Await Small, "
                           "Guest Await Med, Guest Await Large")
            LOG.info("Done writing")

        congestion_data.c_freq_dict.update(
            dict.fromkeys(set(['N', 'B', 'L']).difference(
                congestion_data.c_freq_dict), 0))
        congestion_data.g_freq_dict.update(
            dict.fromkeys(set(['N', 'B', 'L']).difference(
                congestion_data.g_freq_dict), 0))

        self.csv.write(
            ",".join(
                (str(congestion_data.timestamp),
                 str(congestion_data.status[0]),
                 str(congestion_data.c_freq_dict[
                     DeviceDataCollector.STATUS_NORMAL]),
                 str(congestion_data.c_freq_dict[
                     DeviceDataCollector.STATUS_BUILDING]),
                 str(congestion_data.c_freq_dict[
                     DeviceDataCollector.STATUS_CONGESTED]),
                 str(congestion_data.c_iops_avg_list[0]),
                 str(congestion_data.c_iops_avg_list[1]),
                 str(congestion_data.c_iops_avg_list[2]),
                 str(congestion_data.g_freq_dict[
                     DeviceDataCollector.STATUS_NORMAL]),
                 str(congestion_data.g_freq_dict[
                     DeviceDataCollector.STATUS_BUILDING]),
                 str(congestion_data.g_freq_dict[
                     DeviceDataCollector.STATUS_CONGESTED]),
                 str(congestion_data.g_await_avg_list[0]),
                 str(congestion_data.g_await_avg_list[1]),
                 str(congestion_data.g_await_avg_list[2]))
            ) + '\n'
        )

        # flush the python buffer
        self.csv.flush()

        # make sure the os pushes the data to disk
        os.fsync(self.csv.fileno())

    def generate_status(self):
        # Purge stale devices
        self._flush_stale_devices()

        # Get congestion state
        data = self._determine_congestion_state()
        if self.status_skip_count < self.status_skip_total:
            self.status_skip_count += 1
        else:
            self._log_congestion_status(data)
            self.status_skip_count = 0

        # Send alarm updates to FM if configured and there are guest volumes
        # present (won't be on the standby controller)
        if CONF.cinder_congestion.generate_fm_alarms:
            if data.g_count > 0:
                self._update_fm(CONF.cinder_congestion.fm_alarm_debounce)
            elif data.g_count == 0 and self.last_g_count > 0:
                self._clear_fm()

        # Save the current guest count view
        self.last_g_count = data.g_count

        # Save output
        if CONF.cinder_congestion.output_write_csv:
            self._create_output(CONF.cinder_congestion.output_csv_dir,
                                data)

    def parse_iostats(self, line):
        # LOG.debug(line)
        m = self.ts_regex.match(line)
        if m:
            self.latest_time = m.group(0)

        m = self.device_regex.match(line)
        if m:
            # LOG.debug(line)
            # LOG.debug("%s: %f %f" % (m.group(1) ,
            #                          float(m.group(4)) + float(m.group(5)),
            #                          float(m.group(10))))
            if not (self._is_number(m.group(4)) and
                    self._is_number(m.group(5)) and
                    self._is_number(m.group(10))):
                LOG.error("ValueError: invalid input: r/s = %s, w/s = %s "
                          "await = %s" % (m.group(4), m.group(5), m.group(10)))
            else:
                if not any(s in m.group(1) for s in ['loop', 'ram', 'nb',
                                                     'md', 'scd'] +
                           self.non_cinder_phys_devs):
                    self._update_device_stats(self.latest_time,
                                              m.group(1),
                                              (float(m.group(4)) +
                                               float(m.group(5))),
                                              float(m.group(10)))
