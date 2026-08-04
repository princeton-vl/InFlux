#!/usr/bin/env bash
set -Ee -o pipefail

WORKSPACE="${WORKSPACE:-/catkin_ws}"
ROS_SETUP="/opt/ros/noetic/setup.bash"
WORKSPACE_SETUP="$WORKSPACE/devel/setup.bash"

if [[ ! -f "$ROS_SETUP" ]]; then
    echo "ERROR: ROS setup file not found: $ROS_SETUP" >&2
    exit 127
fi
if [[ ! -f "$WORKSPACE_SETUP" ]]; then
    echo "ERROR: Kalibr workspace setup file not found: $WORKSPACE_SETUP" >&2
    exit 127
fi

# Catkin setup scripts forward their current positional parameters to
# _setup_util.py. Preserve the container command, clear positional parameters
# while sourcing the generated setup files, then restore the command.
entrypoint_args=("$@")
set --

# Keep nounset disabled while sourcing generated ROS/Catkin setup scripts.
# shellcheck disable=SC1091
source "$ROS_SETUP"
# shellcheck disable=SC1091
source "$WORKSPACE_SETUP"

set -- "${entrypoint_args[@]}"
set -u

cd "$WORKSPACE/src/kalibr"

if (( $# == 0 )); then
    exec /bin/bash
elif (( $# == 1 )); then
    # Backward compatibility with the historical InFlux pipeline, which passes
    # one shell command string to `docker run`.
    exec /bin/bash -c "$1"
else
    # Normal Docker/CLI behavior for a command and its argument vector.
    exec "$@"
fi
