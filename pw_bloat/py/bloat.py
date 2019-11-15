# Copyright 2019 The Pigweed Authors
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy of
# the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations under
# the License.

"""
bloat is a script which generates a size report card for binary files.
"""

import argparse
import os
import subprocess
import sys

from typing import Callable, List, Iterable, Optional

from binary_diff import BinaryDiff
import bloat_output


def parse_args() -> argparse.Namespace:
    """Parses the script's arguments."""

    def delimited_list(delimiter: str) -> Callable[[str], List[str]]:
        return lambda s: s.split(delimiter)

    parser = argparse.ArgumentParser(
        'Generate a size report card for binaries')
    parser.add_argument('--base-target', type=str,
                        required=True, help='Base binary for a size diff')
    parser.add_argument('--bloaty-config', type=str, required=True,
                        help='Data source configuration for Bloaty')
    parser.add_argument('--full', action='store_true',
                        help='Display full bloat breakdown by symbol')
    parser.add_argument('--labels', type=delimited_list(';'), default='',
                        help='Labels for output binaries')
    parser.add_argument('--out-dir', type=str, required=True,
                        help='Directory in which to write output files')
    parser.add_argument('--target', type=str, required=True,
                        help='Build target name')
    parser.add_argument('--title', type=str, default='pw_bloat',
                        help='Report title')
    parser.add_argument('--source-filter', type=str,
                        help='Bloaty data source filter')
    parser.add_argument('diff_targets', type=delimited_list(';'), nargs='+',
                        metavar='DIFF_TARGET', help='Binaries to process')

    return parser.parse_args()


def run_bloaty(filename: str,
               config: str,
               base_file: Optional[str] = None,
               data_sources: Iterable[str] = (),
               extra_args: Iterable[str] = ()) -> bytes:
    """Executes a Bloaty size report on some binary file(s).

    Args:
        filename: Path to the binary.
        config: Path to Bloaty config file.
        base_file: Path to a base binary. If provided, a size diff is performed.
        data_sources: List of Bloaty data sources for the report.
        extra_args: Additional command-line arguments to pass to Bloaty.

    Returns:
        Binary output of the Bloaty invocation.

    Raises:
        subprocess.CalledProcessError: The Bloaty invocation failed.
    """

    # TODO(frolv): Point the default bloaty path to a prebuilt in Pigweed.
    default_bloaty = 'bloaty'
    bloaty_path = os.getenv('BLOATY_PATH', default_bloaty)

    cmd = [bloaty_path, '-c', config, '-d',
           ','.join(data_sources), '--domain', 'vm', filename]
    cmd.extend(extra_args)

    if base_file is not None:
        cmd.extend(['--', base_file])

    return subprocess.check_output(cmd)


def main() -> int:
    """Program entry point."""

    args = parse_args()

    base_binaries: List[str] = []
    diff_binaries: List[str] = []

    try:
        for binary in args.diff_targets:
            diff_binaries.append(binary[0])
            base_binaries.append(binary[1] if len(
                binary) > 1 else args.base_target)
    except RuntimeError as err:
        print(f'{sys.argv[0]}: {err}', file=sys.stderr)
        return 1

    data_sources = ['segment_names']
    if args.full:
        data_sources.append('fullsymbols')

    # TODO(frolv): CSV output is disabled for full reports as the default Bloaty
    # breakdown is printed. This script should be modified to print a custom
    # symbol breakdown in full reports.
    extra_args = [] if args.full else ['--csv']
    if args.source_filter:
        extra_args.extend(['--source-filter', args.source_filter])

    diffs: List[BinaryDiff] = []
    report = []

    for i, binary in enumerate(diff_binaries):
        binary_name = args.labels[i] if i < len(
            args.labels) else os.path.basename(binary)
        try:
            output = run_bloaty(binary, args.bloaty_config, base_binaries[i],
                                data_sources, extra_args)
            if not output:
                continue

            # TODO(frolv): Remove when custom output for full mode is added.
            if args.full:
                report.append(binary_name)
                report.append('-' * len(binary_name))
                report.append(output.decode())
                continue

            # Ignore the first row as it displays column names.
            bloaty_csv = output.decode().splitlines()[1:]
            diffs.append(BinaryDiff.from_csv(binary_name, bloaty_csv))
        except subprocess.CalledProcessError:
            print(f'{sys.argv[0]}: failed to run diff on {binary}',
                  file=sys.stderr)

    def write_file(filename: str, contents: str) -> None:
        path = os.path.join(args.out_dir, filename)
        with open(path, 'w') as output_file:
            output_file.write(contents)
        print(f'Output written to {path}')

    # TODO(frolv): Remove when custom output for full mode is added.
    if not args.full:
        out = bloat_output.TableOutput(
            args.title, diffs, charset=bloat_output.LineCharset)
        report.append(out.diff())

        rst = bloat_output.RstOutput(diffs)
        write_file(f'{args.target}.rst', rst.diff())

    complete_output = '\n'.join(report)
    write_file(f'{args.target}.txt', complete_output)
    print(complete_output)

    return 0


if __name__ == '__main__':
    sys.exit(main())
