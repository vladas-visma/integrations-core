# (C) Datadog, Inc. 2018-present
# All rights reserved
# Licensed under a 3-clause BSD style license (see LICENSE)
import os
from collections import namedtuple
from datetime import datetime

import click
from semver import parse_version_info
from six import StringIO

from ....utils import stream_file_lines, write_file
from ...constants import CHANGELOG_TYPE_NONE, get_root
from ...git import get_commits_since
from ...github import from_contributor, get_changelog_types, get_pr, parse_pr_numbers
from ...release import get_release_tag_string
from ...utils import get_valid_checks, get_version_string
from ..console import CONTEXT_SETTINGS, abort, echo_failure, echo_info, validate_check_arg

ChangelogEntry = namedtuple('ChangelogEntry', 'number, title, url, author, author_url, from_contributor')


@click.command(context_settings=CONTEXT_SETTINGS, short_help='Update the changelog for a check')
@click.argument('check', callback=validate_check_arg)
@click.argument('version')
@click.argument('old_version', required=False)
@click.option('--initial', is_flag=True)
@click.option('--quiet', '-q', is_flag=True)
@click.option('--dry-run', '-n', is_flag=True)
@click.pass_context
def changelog(ctx, check, version, old_version, initial, quiet, dry_run):
    """Perform the operations needed to update the changelog.

    This method is supposed to be used by other tasks and not directly.
    """
    if check and check not in get_valid_checks():
        abort('Check `{}` is not an Agent-based Integration'.format(check))

    # sanity check on the version provided
    cur_version = old_version or get_version_string(check)
    if parse_version_info(version.lstrip('v')) <= parse_version_info(cur_version.lstrip('v')):
        abort('Current version is {}, cannot bump to {}'.format(cur_version, version))

    if not quiet:
        echo_info('Current version of check {}: {}, bumping to: {}'.format(check, cur_version, version))

    # get the name of the current release tag
    target_tag = get_release_tag_string(check, cur_version)

    # get the diff from HEAD
    diff_lines = get_commits_since(check, None if initial else target_tag)

    # for each PR get the title, we'll use it to populate the changelog
    pr_numbers = parse_pr_numbers(diff_lines)
    if not quiet:
        echo_info('Found {} PRs merged since tag: {}'.format(len(pr_numbers), target_tag))

    if initial:
        # Only use the first one
        del pr_numbers[:-1]

    user_config = ctx.obj
    entries = []
    for pr_num in pr_numbers:
        try:
            payload = get_pr(pr_num, user_config)
        except Exception as e:
            echo_failure('Unable to fetch info for PR #{}: {}'.format(pr_num, e))
            continue

        changelog_labels = get_changelog_types(payload)

        if not changelog_labels:
            abort('No valid changelog labels found attached to PR #{}, please add one!'.format(pr_num))
        elif len(changelog_labels) > 1:
            abort('Multiple changelog labels found attached to PR #{}, please only use one!'.format(pr_num))

        changelog_type = changelog_labels[0]
        if changelog_type == CHANGELOG_TYPE_NONE:
            if not quiet:
                # No changelog entry for this PR
                echo_info('Skipping PR #{} from changelog due to label'.format(pr_num))
            continue

        author = payload.get('user', {}).get('login')
        author_url = payload.get('user', {}).get('html_url')
        title = '[{}] {}'.format(changelog_type, payload.get('title'))

        entry = ChangelogEntry(pr_num, title, payload.get('html_url'), author, author_url, from_contributor(payload))

        entries.append(entry)

    # store the new changelog in memory
    new_entry = StringIO()

    # the header contains version and date
    header = '## {} / {}\n'.format(version, datetime.utcnow().strftime('%Y-%m-%d'))
    new_entry.write(header)

    # one bullet point for each PR
    new_entry.write('\n')
    for entry in entries:
        thanks_note = ''
        if entry.from_contributor:
            thanks_note = ' Thanks [{}]({}).'.format(entry.author, entry.author_url)
        new_entry.write('* {}. See [#{}]({}).{}\n'.format(entry.title, entry.number, entry.url, thanks_note))
    new_entry.write('\n')

    # read the old contents
    if check:
        changelog_path = os.path.join(get_root(), check, 'CHANGELOG.md')
    else:
        changelog_path = os.path.join(get_root(), 'CHANGELOG.md')
    old = list(stream_file_lines(changelog_path))

    # write the new changelog in memory
    changelog_buffer = StringIO()

    # preserve the title
    changelog_buffer.write(''.join(old[:2]))

    # prepend the new changelog to the old contents
    # make the command idempotent
    if header not in old:
        changelog_buffer.write(new_entry.getvalue())

    # append the rest of the old changelog
    changelog_buffer.write(''.join(old[2:]))

    # print on the standard out in case of a dry run
    if dry_run:
        echo_info(changelog_buffer.getvalue())
    else:
        # overwrite the old changelog
        write_file(changelog_path, changelog_buffer.getvalue())
