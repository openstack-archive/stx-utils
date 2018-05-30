#
# Copyright (c) 2016 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

import pbr.version

__version__ = pbr.version.VersionInfo('io-monitor').version_string()
__release__ = pbr.version.VersionInfo('io-monitor').release_string()
