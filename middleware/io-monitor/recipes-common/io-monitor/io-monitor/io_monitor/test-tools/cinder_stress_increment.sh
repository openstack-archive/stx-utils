#!/bin/bash

#
# Copyright (c) 2017 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root" 1>&2
    exit 1
fi

TEST_ROOT=$PWD
HEAT_CHECK=${TEST_ROOT}/heat_check.sh

STRESSOR_CREATE=${TEST_ROOT}/cinder_stress_increment_create.sh
STRESSOR_DELETE=${TEST_ROOT}/cinder_stress_increment_delete.sh

## one volume/VM/stack
#YAML=${TEST_ROOT}/yaml/cinder_v1_bon0.yaml
#YAML=${TEST_ROOT}/yaml/cinder_v1_bon1.yaml
#YAML=${TEST_ROOT}/yaml/cinder_v1_bon1_cpuburn.yaml

## Two volumes/VM/stack
#YAML=${TEST_ROOT}/yaml/cinder_v2_bon0.yaml
#YAML=${TEST_ROOT}/yaml/cinder_v2_bon2.yaml
#YAML=${TEST_ROOT}/yaml/cinder_v2_bon2_cpuburn.yaml

## 4 volumes/VM/stack
#YAML=${TEST_ROOT}/yaml/cinder_v4_bon0.yaml
#YAML=${TEST_ROOT}/yaml/cinder_v4_bon4.yaml
#YAML=${TEST_ROOT}/yaml/cinder_v4_bon4_cpuburn.yaml

##  test
#YAML=${TEST_ROOT}/yaml/cinder_nokia_v5_bon0.yaml
YAML=${TEST_ROOT}/yaml/cinder_nokia_v5_bon1.yaml
#YAML=${TEST_ROOT}/yaml/cinder_nokia_v5_bon2.yaml
#YAML=${TEST_ROOT}/yaml/cinder_nokia_v5_bon3.yaml
#YAML=${TEST_ROOT}/yaml/cinder_nokia_v5_bon4.yaml
#YAML=${TEST_ROOT}/yaml/cinder_nokia_v5_bon4_cpuburn.yaml

for stack_num in 1 2 4 8 14
#for stack_num in $(seq 1 32)
do


    echo "$stack_num: Creating stacks"
    sudo -u wrsroot ${STRESSOR_CREATE} $YAML $stack_num

    source /etc/nova/openrc
    AM_I_CREATING="sudo -u wrsroot $HEAT_CHECK | grep CREATE_IN_PROGRESS"
    while [[ $(eval $AM_I_CREATING) != "" ]]; do
        echo "$stack_num: Creating..."
        sleep 15
    done

    ANY_CREATE_ERRORS="sudo -u wrsroot $HEAT_CHECK | grep CREATE_FAILED"
    if [[ $(eval $ANY_CREATE_ERRORS) != "" ]]; then
        echo "$stack_num: Creating stacks failed"
        exit -1
    else
        # Run at steady state for 60s
        echo "$stack_num: Running at steady state for an additional 10 seconds"
        sleep 10
    fi

    echo "$stack_num: Deleting stacks"
    sudo -u wrsroot ${STRESSOR_DELETE} $stack_num

    AM_I_DELETING="sudo -u wrsroot $HEAT_CHECK | grep DELETE_IN_PROGRESS"
    while [[ $(eval $AM_I_DELETING) != "" ]]; do
        echo "$stack_num: Deleting..."
    done

    ANY_DELETE_ERRORS="sudo -u wrsroot $HEAT_CHECK | grep DELETE_FAILED"
    if [[ $(eval $ANY_DELETE_ERRORS) != "" ]]; then
        echo "$stack_num: Deleting stacks failed"
    else
        echo "$stack_num: Create/Delete successful"
    fi

    sleep 10

done

