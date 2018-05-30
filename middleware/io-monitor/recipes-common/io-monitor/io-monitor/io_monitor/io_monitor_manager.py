# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright (c) 2016 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#


# IMPORTS
import logging
import time
import math
import os
import sys

from daemon import runner
from io_monitor import __version__
from io_monitor.constants import DOMAIN
from io_monitor.options import CONF
from io_monitor.options import add_common_opts
from io_monitor.monitors.cinder.congestion import CinderCongestionMonitor
import subprocess

# OPTIONS

# CONSTANTS
LOG_FILE = '/var/log/io-monitor.log'
PID_FILE = '/var/run/io-monitor/io-monitor-manager.pid'
CONFIG_COMPLETE = '/etc/platform/.initial_config_complete'

LOG = logging.getLogger(DOMAIN)

LOG_FORMAT_DEBUG = '%(asctime)s.%(msecs)03d: ' \
                   + os.path.basename(sys.argv[0]) + '[%(process)s]: ' \
                   + '%(filename)s(%(lineno)s) - %(funcName)-20s: ' \
                   + '%(levelname)s: %(message)s'

LOG_FORMAT_NORMAL = '%(asctime)s.%(msecs)03d: [%(process)s]: ' \
                    + '%(levelname)s: %(message)s'


# METHODS
def _start_polling(log_handle):
    io_monitor_daemon = IOMonitorDaemon()
    io_monitor_runner = runner.DaemonRunner(io_monitor_daemon)
    io_monitor_runner.daemon_context.umask = 0o022
    io_monitor_runner.daemon_context.files_preserve = [log_handle.stream]
    io_monitor_runner.do_action()


def handle_exception(exc_type, exc_value, exc_traceback):
    """
    Exception handler to log any uncaught exceptions
    """
    LOG.error("Uncaught exception",
              exc_info=(exc_type, exc_value, exc_traceback))
    sys.__excepthook__(exc_type, exc_value, exc_traceback)


def configure_logging():

    level_dict = {'ERROR': logging.ERROR,
                  'WARN': logging.WARN,
                  'INFO': logging.INFO,
                  'DEBUG': logging.DEBUG}

    if CONF.global_log_level in level_dict.keys():
        level = level_dict[CONF.global_log_level]
    else:
        level = logging.INFO

    # When we deamonize the default logging stream handler is closed. We need
    # manually setup logging so that we can pass the file_handler into the
    # monitor classes.
    LOG.setLevel(level)
    h = logging.FileHandler(LOG_FILE)
    h.setLevel(level)
    f = logging.Formatter(LOG_FORMAT_NORMAL, datefmt='%Y-%m-%d %H:%M:%S')
    h.setFormatter(f)
    LOG.addHandler(h)

    # Log uncaught exceptions to file
    sys.excepthook = handle_exception

    return h


def main():
    # Set up configuration options
    add_common_opts()
    CONF(project='io-monitor', version=__version__)

    # Set up logging. Allow all levels. The monitor will restrict the level
    # further as it sees fit
    log_handle = configure_logging()

    # Dump config
    CONF.log_opt_values(LOG, logging.INFO)
    if CONF.daemon_mode:
        sys.argv = [sys.argv[0], 'start']
        _start_polling(log_handle)


# CLASSES

class IOMonitorDaemon():
    """ Daemon process representation of
        the iostat monitoring program
    """
    def __init__(self):
        # Daemon-specific init
        self.stdin_path = '/dev/null'
        self.stdout_path = '/dev/null'
        self.stderr_path = '/dev/null'
        self.pidfile_path = PID_FILE
        self.pidfile_timeout = 5

        # Monitors
        self.ccm = None

    def run(self):

        # We are started by systemd so wait for initial config to be completed
        while not os.path.exists(CONFIG_COMPLETE):
            LOG.info("Waiting: Initial configuration is not complete")
            time.sleep(30)

        LOG.info("Initializing monitors..")
        # Cinder Congestion Monitor
        self.ccm = CinderCongestionMonitor()

        # Ensure system is monitorable
        if not self.ccm.is_system_monitorable():
            LOG.error("This system in not configured for Cinder LVM")

            # Wait for something to kill us. Since we are managed by pmon
            # we don't want to exit at this point
            def sleepy_time(t):
                while True:
                    t = t * 2
                    yield t

            LOG.info("Will standby performing no further actions")
            for s in sleepy_time(1):
                time.sleep(s)

            sys.exit()

        LOG.info("Starting: Running iostat %d times per minute" %
                 math.ceil(60/(CONF.wait_time+1)))

        try:
            command = "iostat -dx -t -p ALL"
            while True:
                process = subprocess.Popen(command.split(),
                                           stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE)
                output, error = process.communicate()
                if output:
                    # Send the iostat input to the monitor
                    self._monitor_ccm_send_inputs(output)

                    # Instruct the monitor to process the data
                    self._monitor_ccm_generate_output()

                time.sleep(CONF.wait_time)
        except KeyboardInterrupt:
            LOG.info('Exiting...')

        return_code = process.poll()
        LOG.error("return code = %s " % return_code)

    def _monitor_ccm_send_inputs(self, inputs):
        # LOG.debug(inputs)

        # Process output from iteration
        lines = inputs.split('\n')
        for pline in lines[2:]:
            self.ccm.parse_iostats(pline.strip())

    def _monitor_ccm_generate_output(self):
        self.ccm.generate_status()

if __name__ == "__main__":

    if not os.geteuid() == 0:
        sys.exit("\nOnly root can run this\n")

    main()
