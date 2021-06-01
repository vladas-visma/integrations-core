# (C) Datadog, Inc. 2018-present
# All rights reserved
# Licensed under Simplified BSD License (see LICENSE)

import os
import shutil
from copy import deepcopy

import pytest
import requests
import yaml

from datadog_checks.dev import TempDir, WaitFor, docker_run, run_command
from datadog_checks.dev.docker import get_container_ip

from .common import (
    AUTODISCOVERY_TYPE,
    COMPOSE_DIR,
    PORT,
    SCALAR_OBJECTS,
    SCALAR_OBJECTS_WITH_TAGS,
    SNMP_CONTAINER_NAME,
    TABULAR_OBJECTS,
    TOX_ENV_NAME,
    generate_container_instance_config,
)

FILES = [
    "https://ddintegrations.blob.core.windows.net/snmp/cisco-3850.snmprec",
]

E2E_METADATA = {
    'start_commands': [
        # Ensure the Agent has access to profile definition files and auto_conf.
        'cp -r /home/snmp/datadog_checks/snmp/data/profiles /etc/datadog-agent/conf.d/snmp.d/',
    ],
}


@pytest.fixture(scope='session')
def dd_environment():
    new_e2e_metadata = deepcopy(E2E_METADATA)
    with TempDir('snmp') as tmp_dir:
        data_dir = os.path.join(tmp_dir, 'data')
        env = {'DATA_DIR': data_dir}
        if not os.path.exists(data_dir):
            shutil.copytree(os.path.join(COMPOSE_DIR, 'data'), data_dir)
            for data_file in FILES:
                response = requests.get(data_file)
                with open(os.path.join(data_dir, data_file.rsplit('/', 1)[1]), 'wb') as output:
                    output.write(response.content)

        with docker_run(os.path.join(COMPOSE_DIR, 'docker-compose.yaml'), env_vars=env, log_patterns="Listening at"):
            if AUTODISCOVERY_TYPE == 'agent':
                instance_config = {}
                new_e2e_metadata['docker_volumes'] = [
                    '{}:/etc/datadog-agent/datadog.yaml'.format(create_datadog_conf_file(tmp_dir))
                ]
            else:
                instance_config = generate_container_instance_config(
                    SCALAR_OBJECTS + SCALAR_OBJECTS_WITH_TAGS + TABULAR_OBJECTS
                )
                new_e2e_metadata['docker_volumes'] = [
                    '{}:/etc/datadog-agent/conf.d/snmp.d'.format(os.path.join(COMPOSE_DIR, 'confd')),
                    '{}:/etc/datadog-agent/datadog.yaml'.format(create_datadog_conf_file(tmp_dir))
                ]
            yield instance_config, new_e2e_metadata


@pytest.fixture
def autodiscovery_ready():
    WaitFor(lambda: _autodiscovery_ready())()


def _autodiscovery_ready():
    result = run_command(
        ['docker', 'exec', 'dd_snmp_{}'.format(TOX_ENV_NAME), 'agent', 'configcheck'], capture=True, check=True
    )

    autodiscovery_checks = []
    for result_line in result.stdout.splitlines():
        if 'autodiscovery_subnet' in result_line:
            autodiscovery_checks.append(result_line)

    # assert subnets discovered by `snmp_listener` config from datadog.yaml
    expected_autodiscovery_checks = 5
    assert len(autodiscovery_checks) == expected_autodiscovery_checks


def create_datadog_conf_file(tmp_dir):
    container_ip = get_container_ip(SNMP_CONTAINER_NAME)
    prefix = ".".join(container_ip.split('.')[:3])
    datadog_conf = {
        'telemetry': {
            'enabled': True,
            'checks': [
                "snmp",
            ],
        },
    }
    datadog_conf_file = os.path.join(tmp_dir, 'datadog.yaml')
    with open(datadog_conf_file, 'w') as file:
        file.write(yaml.dump(datadog_conf))
    return datadog_conf_file


@pytest.fixture
def container_ip():
    return get_container_ip(SNMP_CONTAINER_NAME)
