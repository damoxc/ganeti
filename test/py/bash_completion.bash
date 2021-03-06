#!/bin/bash
#

# Copyright (C) 2012 Google Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.

set -e -u -o pipefail

# Disable any locales
export LC_ALL=C

readonly bash_completion=${TOP_BUILDDIR:-.}/doc/examples/bash_completion-debug
readonly default_wordbreaks=$' \t\n"'\''@><=;|&(:'

err() {
  echo "$@"
  echo 'Aborting'
  exit 1
}

contains() {
  local -r needle="$1"; shift

  for value; do
    if [[ "$value" = "$needle" ]]; then
      return 0
    fi
  done

  return 1
}

# Prepares a subshell for testing bash completion functions
setup() {
  local -r unused=UNUSED

  set +e +u -o pipefail

  . $bash_completion

  COMP_KEY=$unused
  COMP_LINE=$unused
  COMP_POINT=$unused
  COMP_TYPE=$unused
  COMP_WORDBREAKS="$default_wordbreaks"

  GANETI_COMPL_LOG=

  unset COMP_CWORD
  unset COMP_WORDS
}

# Check if default wordbreaks are still valid (this detects cases where Bash
# were to change its built-in default value)
# TODO: May need an update for older Bash versions; some didn't include the
# colon character (':') in COMP_WORDBREAKS
(
  bashdef=$(env - bash --noprofile --norc -c 'echo -n "$COMP_WORDBREAKS"')
  case "$bashdef" in
    $default_wordbreaks) ;;
    *)
      err 'Bash uses unknown value for COMP_WORDBREAKS'
      ;;
  esac
)

# Check for --help
for cmd in gnt-{instance,node,group,job}; do
  (
    setup
    COMP_CWORD=2
    COMP_WORDS=( $cmd list - )
    _${cmd/-/_}
    contains --help "${COMPREPLY[@]}" || \
      err "'$cmd list' did not list --help as an option"
  )
done

# Completing a yes/no option
(
  setup
  COMP_CWORD=3
  COMP_WORDS=( gnt-node modify --drained )
  _gnt_node
  if [[ "${COMPREPLY[*]}" != 'no yes' ]]; then
    err "Completing '${COMP_WORDS[@]}' did not give correct result"
  fi
)

# Completing a multiple-choice option
(
  setup
  COMP_CWORD=2
  COMP_WORDS=( gnt-debug allocator --disk-template=sh foo )
  _gnt_debug
  if [[ "${COMPREPLY[*]}" != sharedfile ]]; then
    err "Completing '${COMP_WORDS[*]}' did not give correct result"
  fi
)

# Completing a node name
(
  setup

  # Override built-in function
  _ganeti_nodes() {
    echo aanode1 bbnode2 aanode3
  }

  COMP_CWORD=4
  COMP_WORDS=( gnt-node modify --drained yes aa )
  _gnt_node
  if [[ "${COMPREPLY[*]}" != 'aanode1 aanode3' ]]; then
    err 'Completing node names failed'
  fi
)

# Completing an option when it's not at the end
(
  setup

  # Override built-in function
  _ganeti_instances() {
    echo inst{1..5}
  }

  # Completing word in the middle
  COMP_CWORD=2
  COMP_WORDS=( gnt-instance list --o inst3 inst inst5 )
  _gnt_node
  contains --output "${COMPREPLY[@]}" || err 'Did not complete parameter'
)

# Completing an instance name
(
  setup

  # Override built-in function
  _ganeti_instances() {
    echo inst{1..5}
  }

  # Completing word in the middle
  COMP_CWORD=5
  COMP_WORDS=( gnt-instance list -o foobar inst1 inst inst5 )
  _gnt_instance
  if [[ "${COMPREPLY[*]}" != "$(echo inst{1..5})" ]]; then
    err "Completing '${COMP_WORDS[*]}' did not give correct result"
  fi
)

# Need to test node expansion with different wordbreak settings
[[ "$default_wordbreaks" == *:* ]] || \
  err 'No colon in default wordbreak characters'
for wb in "$default_wordbreaks" "${default_wordbreaks/:/}"; do
  (
    setup

    # Override built-in function
    _ganeti_nodes() {
      echo node{A..C}
    }

    COMP_WORDBREAKS="$wb"

    # Completing nodes
    COMP_CWORD=3
    COMP_WORDS=( gnt-instance add -n )
    _gnt_instance
    if [[ "${COMPREPLY[*]}" != 'nodeA nodeA: nodeB nodeB: nodeC nodeC:' ]]; then
      err 'Got wrong node list'
    fi

    COMP_CWORD=3
    COMP_WORDS=( gnt-instance add -n nodeB )
    _gnt_instance
    if [[ "${COMPREPLY[*]}" != 'nodeB nodeB:' ]]; then
      err 'Got wrong node list'
    fi

    COMP_CWORD=3
    COMP_WORDS=( gnt-instance add -n nodeC: )
    _gnt_instance
    if [[ "$COMP_WORDBREAKS" == *:* ]]; then
      expected='nodeA nodeB'
    else
      expected='nodeC:nodeA nodeC:nodeB'
    fi
    if [[ "${COMPREPLY[*]}" != "$expected" ]]; then
      err 'Got wrong node list'
    fi
  )
done

# Need to test different settings for the extglob shell option
for opt in -u -s; do
  verify_extglob() {
    if [[ "$(shopt -p extglob)" != "shopt $opt extglob" ]]; then
      err 'The "extglob" shell option has an unexpected value'
    fi
  }

  (
    shopt $opt extglob

    verify_extglob
    setup
    verify_extglob

    # Completing nodes
    COMP_CWORD=4
    COMP_WORDS=( gnt-instance add --os-type busybox --no-n )
    _gnt_instance
    if [[ "${COMPREPLY[*]}" != '--no-name-check --no-nics' ]]; then
      err "Completing '${COMP_WORDS[*]}' did not give correct result"
    fi
    verify_extglob
  )
done

exit 0
