#!/bin/bash

BASE_DIR="/opt/pve-answer-server"
ENV_DIR="/opt/pve-answer-server"

if [[ -z ${ENV_DIR} ]]
then
    ENV_DIR=${BASE_DIR}
fi


# Initializae environment
cd ${BASE_DIR}
source /etc/profile
source ${ENV_DIR}/bin/activate

# To be implemented: custom config
#${BASE_DIR}/bin/answer-server -f ${BASE_DIR}/conf/answer-server_config.py

# Testing sync version
python3 answer-server-sync.py

