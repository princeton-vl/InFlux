#!/usr/bin/env bash
set -Eeuo pipefail

IMAGE="kalibr:latest"
PLATFORM="linux/amd64"
WORKSPACE=""
NAME=""

usage() {
    cat <<'USAGE'
Usage: run_docker.sh --workspace PATH [options] [-- COMMAND [ARG ...]]

Mount one host calibration workspace at /data and run the Kalibr image.
Without COMMAND, opens an interactive shell.

Options:
  --workspace PATH  Host workspace mounted at /data (required)
  --image TAG       Docker image tag (default: kalibr:latest)
  --platform VALUE  Docker platform (default: linux/amd64)
  --name NAME       Optional container name
  -h, --help        Show this help
USAGE
}

while (( $# > 0 )); do
    case "$1" in
        --workspace)
            WORKSPACE="${2:?--workspace requires a value}"
            shift 2
            ;;
        --image)
            IMAGE="${2:?--image requires a value}"
            shift 2
            ;;
        --platform)
            PLATFORM="${2:?--platform requires a value}"
            shift 2
            ;;
        --name)
            NAME="${2:?--name requires a value}"
            shift 2
            ;;
        --)
            shift
            break
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: unknown option before --: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: docker was not found on PATH" >&2
    exit 1
fi
if [[ -z "$WORKSPACE" ]]; then
    echo "ERROR: --workspace is required" >&2
    usage >&2
    exit 2
fi
WORKSPACE="$(cd -- "$WORKSPACE" && pwd)"

cmd=(
    docker run
    --rm
    --platform "$PLATFORM"
    --volume "$WORKSPACE:/data"
    --workdir /data
    --env MPLBACKEND=Agg
)
if [[ -n "$NAME" ]]; then
    cmd+=(--name "$NAME")
fi
if [[ -t 0 && -t 1 ]]; then
    cmd+=(-it)
fi
cmd+=("$IMAGE")
if (( $# > 0 )); then
    cmd+=("$@")
fi

printf 'Running:'
printf ' %q' "${cmd[@]}"
printf '\n'
"${cmd[@]}"
