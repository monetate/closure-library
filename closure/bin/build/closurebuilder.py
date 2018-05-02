#!/usr/bin/env python
#
# Copyright 2009 The Closure Library Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS-IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Utility for Closure Library dependency calculation.

ClosureBuilder scans source files to build dependency info.  From the
dependencies, the script can produce a deps.js file, a manifest in dependency
order, a concatenated script, or compiled output from the Closure Compiler.

Paths to files can be expressed as individual arguments to the tool (intended
for use with find and xargs).  As a convenience, --root can be used to specify
all JS files below a directory.

usage: %prog [options] [file1.js file2.js ...]
"""




import logging
import optparse
import os
import sys

import depstree
import jscompiler
import source
import treescan

import re

MONETATE_FLAG_PATTERN = r"""

  ^(mc\.          # Must be a property of the monetate common namespace. Capture group 1.
  [a-zA-Z]+\.     # Must have it's own module namespace. Capture group 1.
  [A-Z0-9_]+)     # Must follow the constant format. Capture group 1.
  =(.*)$          # Must assign a value. Capture group 2.

"""

MONETATE_FLAG_RE = re.compile(MONETATE_FLAG_PATTERN, re.X)

def _GetOptionsParser():
  """Get the options parser."""

  parser = optparse.OptionParser(__doc__)
  parser.add_option('-i',
                    '--input',
                    dest='inputs',
                    action='append',
                    default=[],
                    help='One or more input files to calculate dependencies '
                    'for.  The namespaces in this file will be combined with '
                    'those given with the -n flag to form the set of '
                    'namespaces to find dependencies for.')
  parser.add_option('-n',
                    '--namespace',
                    dest='namespaces',
                    action='append',
                    default=[],
                    help='One or more namespaces to calculate dependencies '
                    'for.  These namespaces will be combined with those given '
                    'with the -i flag to form the set of namespaces to find '
                    'dependencies for.  A Closure namespace is a '
                    'dot-delimited path expression declared with a call to '
                    'goog.provide() (e.g. "goog.array" or "foo.bar").')
  parser.add_option('--root',
                    dest='roots',
                    action='append',
                    default=[],
                    help='The paths that should be traversed to build the '
                    'dependencies.')
  parser.add_option('-o',
                    '--output_mode',
                    dest='output_mode',
                    type='choice',
                    action='store',
                    choices=['list', 'script', 'compiled'],
                    default='list',
                    help='The type of output to generate from this script. '
                    'Options are "list" for a list of filenames, "script" '
                    'for a single script containing the contents of all the '
                    'files, or "compiled" to produce compiled output with '
                    'the Closure Compiler.  Default is "list".')
  parser.add_option('-c',
                    '--compiler_jar',
                    dest='compiler_jar',
                    action='store',
                    help='The location of the Closure compiler .jar file.')
  parser.add_option('-f',
                    '--compiler_flags',
                    dest='compiler_flags',
                    default=[],
                    action='append',
                    help='Additional flags to pass to the Closure compiler.')
  parser.add_option('--output_file',
                    dest='output_file',
                    action='store',
                    help=('If specified, write output to this path instead of '
                          'writing to standard output.'))
  parser.add_option('--monetate_logging_level',
                    dest='monetate_logging_level',
                    action='store',
                    help=('If specified, define logging level. Valid options: '
                          'DEBUG, INFO, WARNING, ERROR, CRITICAL'))
  parser.add_option('--monetate-flag',
                    dest='monetate_flags',
                    default=[],
                    action='append',
                    help=('Monetate feature flags. '
                          'If --output_mode=compiled Added as --define= to compiler_flags. '
                          'If --output_mode=script Substitutes source code manually.'
                          '@see Makefile'))

  return parser


def _GetInputByPath(path, sources):
  """Get the source identified by a path.

  Args:
    path: str, A path to a file that identifies a source.
    sources: An iterable collection of source objects.

  Returns:
    The source from sources identified by path, if found.  Converts to
    absolute paths for comparison.
  """
  for js_source in sources:
    # Convert both to absolute paths for comparison.
    if os.path.abspath(path) == os.path.abspath(js_source.GetPath()):
      return js_source


def _GetClosureBaseFile(sources):
  """Given a set of sources, returns the one base.js file.

  Note that if zero or two or more base.js files are found, an error message
  will be written and the program will be exited.

  Args:
    sources: An iterable of _PathSource objects.

  Returns:
    The _PathSource representing the base Closure file.
  """
  filtered_base_files = filter(_IsClosureBaseFile, sources)
  if not filtered_base_files:
    logging.error('No Closure base.js file found.')
    sys.exit(1)
  if len(filtered_base_files) > 1:
    logging.error('More than one Closure base.js files found at these paths:')
    for base_file in filtered_base_files:
      logging.error(base_file.GetPath())
    sys.exit(1)
  return filtered_base_files[0]


def _IsClosureBaseFile(js_source):
  """Returns true if the given _PathSource is the Closure base.js source."""
  if os.path.basename(js_source.GetPath()) == 'base.js':
    # Sanity check that this is the Closure base file.  Check that this
    # is where goog is defined.
    for line in js_source.GetSource().splitlines():
      if line.startswith('var goog = goog || {};'):
        return True
  return False


class _PathSource(source.Source):
  """Source file subclass that remembers its file path."""

  def __init__(self, path):
    """Initialize a source.

    Args:
      path: str, Path to a JavaScript file.  The source string will be read
        from this file.
    """
    super(_PathSource, self).__init__(source.GetFileContents(path))

    self._path = path

  def GetPath(self):
    """Returns the path."""
    return self._path


def main():
  options, args = _GetOptionsParser().parse_args()

  logging.basicConfig(format=(sys.argv[0] + ': %(message)s'),
                      level=options.monetate_logging_level or logging.INFO)

  # Make our output pipe.
  if options.output_file:
    out = open(options.output_file, 'w')
  else:
    out = sys.stdout

  sources = set()

  logging.info('Scanning paths...')
  for path in options.roots:
    for js_path in treescan.ScanTreeForJsFiles(path):
      sources.add(_PathSource(js_path))

  # Add scripts specified on the command line.
  for path in args:
    sources.add(source.Source(_PathSource(path)))

  logging.info('%s sources scanned.', len(sources))

  # Though deps output doesn't need to query the tree, we still build it
  # to validate dependencies.
  logging.info('Building dependency tree..')
  tree = depstree.DepsTree(sources)

  input_namespaces = set()
  inputs = options.inputs or []
  for input_path in inputs:
    js_input = _GetInputByPath(input_path, sources)
    if not js_input:
      logging.error('No source matched input %s', input_path)
      sys.exit(1)
    input_namespaces.update(js_input.provides)

  input_namespaces.update(options.namespaces)

  if not input_namespaces:
    logging.error('No namespaces found. At least one namespace must be '
                  'specified with the --namespace or --input flags.')
    sys.exit(2)

  # The Closure Library base file must go first.
  base = _GetClosureBaseFile(sources)
  deps = [base] + tree.GetDependencies(input_namespaces)

  # Get match groups while validating monetate_flags.
  try:
    monetate_flag_groups = [MONETATE_FLAG_RE.match(flag).groups() for flag in options.monetate_flags]
  except AttributeError:
    logging.error('Invalid --monetate_flag passed must match: %s' % MONETATE_FLAG_PATTERN)
    sys.exit(2)

  # Check for duplicate monetate_flag properties.
  if len(set([flag_group[0] for flag_group in monetate_flag_groups])) != len(monetate_flag_groups):
    logging.error('Duplicate --monetate-flag passed.')
    sys.exit(2)

  output_mode = options.output_mode
  if output_mode == 'list':
    out.writelines([js_source.GetPath() + '\n' for js_source in deps])
  elif output_mode == 'script':

    # Join script source as a string so a re substitution can occur.
    script_source = ''.join([js_source.GetSource() for js_source in deps])

    # Replace source definition with monetate_flag.
    for monetate_flag_group in monetate_flag_groups:

      # Get flag parts from match groups.
      monetate_flag_property = monetate_flag_group[0]
      monetate_flag_value = monetate_flag_group[1]

      # Make sure property is defined in the source.
      monetate_define_re = re.compile('%s\s*=\s*(.*)\s*;' % monetate_flag_property)
      if not monetate_define_re.search(script_source):
        logging.error('--monetate-flag: %s was not found in script source.', monetate_flag_property)
        sys.exit(2)

      # Update definition in source.
      monetate_flag_replacement = '%s = %s;' % (monetate_flag_property, monetate_flag_value)
      script_source = monetate_define_re.sub(monetate_flag_replacement, script_source)

    out.writelines(script_source)
  elif output_mode == 'compiled':

    # Pass monetate_flags into compiler as --define compiler_flags.
    monetate_flags = ['--define=%s' % flag for flag in options.monetate_flags]
    options.compiler_flags = options.compiler_flags + monetate_flags

    # Make sure a .jar is specified.
    if not options.compiler_jar:
      logging.error('--compiler_jar flag must be specified if --output is '
                    '"compiled"')
      sys.exit(2)

    compiled_source = jscompiler.Compile(
        options.compiler_jar,
        [js_source.GetPath() for js_source in deps],
        options.compiler_flags)

    if compiled_source is None:
      logging.error('JavaScript compilation failed.')
      sys.exit(1)
    else:
      logging.info('JavaScript compilation succeeded.')
      out.write(compiled_source)

  else:
    logging.error('Invalid value for --output flag.')
    sys.exit(2)


if __name__ == '__main__':
  main()
