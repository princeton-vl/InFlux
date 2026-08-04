#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
KALIBR_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

IMAGE="kalibr:latest"
PLATFORM="linux/amd64"
JOBS="6"
NO_CACHE=0

usage() {
    cat <<'USAGE'
Usage: build_docker.sh [options]

Build the local Kalibr source into a Docker image.

Options:
  --image TAG       Output image tag (default: kalibr:latest)
  --platform VALUE  Docker platform (default: linux/amd64)
  --jobs N          Parallel catkin build jobs (default: 6)
  --no-cache        Disable Docker build cache
  -h, --help        Show this help
USAGE
}

while (( $# > 0 )); do
    case "$1" in
        --image)
            IMAGE="${2:?--image requires a value}"
            shift 2
            ;;
        --platform)
            PLATFORM="${2:?--platform requires a value}"
            shift 2
            ;;
        --jobs)
            JOBS="${2:?--jobs requires a value}"
            shift 2
            ;;
        --no-cache)
            NO_CACHE=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: docker was not found on PATH" >&2
    exit 1
fi
if [[ ! "$JOBS" =~ ^[1-9][0-9]*$ ]]; then
    echo "ERROR: --jobs must be a positive integer; got $JOBS" >&2
    exit 2
fi

cmd=(
    docker build
    --platform "$PLATFORM"
    --build-arg "KALIBR_BUILD_JOBS=$JOBS"
    --tag "$IMAGE"
    --file "$KALIBR_ROOT/Dockerfile_ros1_20_04"
)
if (( NO_CACHE )); then
    cmd+=(--no-cache)
fi
cmd+=("$KALIBR_ROOT")

printf 'Running:'
printf ' %q' "${cmd[@]}"
printf '\n'
"${cmd[@]}"

echo "Built image: $IMAGE"
