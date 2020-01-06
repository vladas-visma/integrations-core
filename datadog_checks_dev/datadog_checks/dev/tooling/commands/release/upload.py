# (C) Datadog, Inc. 2018-present
# All rights reserved
# Licensed under a 3-clause BSD style license (see LICENSE)
import os

import click

from ....subprocess import run_command
from ....utils import basepath, chdir, dir_exists, resolve_path
from ...constants import get_root
from ...release import build_package
from ...utils import get_valid_checks
from ..console import CONTEXT_SETTINGS, abort, echo_success, echo_waiting


@click.command(context_settings=CONTEXT_SETTINGS, short_help='Build and upload a check to PyPI')
@click.argument('check')
@click.option('--sdist', '-s', is_flag=True)
@click.option('--dry-run', '-n', is_flag=True)
@click.pass_context
def upload(ctx, check, sdist, dry_run):
    """Release a specific check to PyPI as it is on the repo HEAD."""
    if check in get_valid_checks():
        check_dir = os.path.join(get_root(), check)
    else:
        check_dir = resolve_path(check)
        if not dir_exists(check_dir):
            abort('`{}` is not an Agent-based Integration or Python package'.format(check))

        check = basepath(check_dir)

    # retrieve credentials
    pypi_config = ctx.obj.get('pypi', {})
    username = pypi_config.get('user') or os.getenv('TWINE_USERNAME')
    password = pypi_config.get('pass') or os.getenv('TWINE_PASSWORD')
    if not (username and password):
        abort('This requires pypi.user and pypi.pass configuration. Please see `ddev config -h`.')

    auth_env_vars = {'TWINE_USERNAME': username, 'TWINE_PASSWORD': password}
    echo_waiting('Building and publishing `{}` to PyPI...'.format(check))

    with chdir(check_dir, env_vars=auth_env_vars):
        result = build_package(check_dir, sdist)
        if result.code != 0:
            abort(result.stdout, result.code)
        echo_waiting('Uploading the package...')
        if not dry_run:
            result = run_command('twine upload --skip-existing dist{}*'.format(os.path.sep))
            if result.code != 0:
                abort(code=result.code)

    echo_success('Success!')
