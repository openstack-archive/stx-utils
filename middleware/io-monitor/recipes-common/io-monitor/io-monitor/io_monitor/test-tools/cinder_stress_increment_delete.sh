#!/bin/bash

#
# Copyright (c) 2017 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

case $# in
    0)
        echo "Usage: `basename $0` <# of stacks>"
        exit $E_BADARGS  
        ;;
esac

NUM_STACKS=$1

for i in $(seq 1 $NUM_STACKS)
do
    source /etc/nova/openrc 
    heat stack-delete stack-$i
done

