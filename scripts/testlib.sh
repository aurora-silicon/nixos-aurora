# Shared checks for the CI test scripts; source it, do not run it.
# Bash ignores the exit status of "! cmd" under set -e, so a line such as
# "! pacman -Q mesa" can never fail a test. Negative checks use these instead.

# refute CMD [ARG...]: CMD must fail; its success ends the test.
refute() {
  if "$@"; then
    printf 'unexpected success: %s\n' "$*" >&2
    exit 1
  fi
}

# nomatch [GREP-OPTION...] PATTERN [FILE...]: no line matches. Unlike
# "refute grep", a missing file or another grep error (status 2) fails too.
nomatch() {
  local status=0
  grep -q "$@" || status=$?
  case $status in
    1) return 0 ;;
    0) printf 'unexpected match: grep %s\n' "$*" >&2 ;;
    *) printf 'grep failed (%s): grep %s\n' "$status" "$*" >&2 ;;
  esac
  exit 1
}
