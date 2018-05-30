#!/bin/bash

#
# Copyright (c) 2017 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

case $# in
    0|1)
        echo "Usage: `basename $0` <yaml> <# of stacks>"
        exit $E_BADARGS  
        ;;
esac

YAML=$1
NUM_STACKS=$2

for i in $(seq 1 $NUM_STACKS)
do
    source $HOME/openrc.tenant1
    heat stack-create -f $YAML stack-$i
done

