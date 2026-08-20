#!/bin/bash

if [[ $# -ne 0 ]]; then
    echo "Usage: $0"
    exit 1
fi

eval "$(conda shell.bash hook)"
source "$CONDA_PREFIX/etc/profile.d/conda.sh"
conda activate influx
# !!! Ensure correct environment is actually activated !!! #
echo "$CONDA_DEFAULT_ENV"

QUEUE_FILE=$(python3 -c "import yaml; print(yaml.safe_load(open('$(dirname "$0")/../config.yaml'))['real_calib']['QUEUE_FILE'])")
COMPLETED_FILE=$(python3 -c "import yaml; print(yaml.safe_load(open('$(dirname "$0")/../config.yaml'))['real_calib']['COMPLETED_FILE'])")
ONHOLD_FILE=$(python3 -c "import yaml; print(yaml.safe_load(open('$(dirname "$0")/../config.yaml'))['real_calib']['ONHOLD_FILE'])")
SKIP_IF_FAIL_FLAG=$(python3 -c "import yaml; print(yaml.safe_load(open('$(dirname "$0")/../config.yaml'))['real_calib']['SKIP_IF_FAIL_FLAG'])")

echo "QUEUE_FILE from config.yaml: $QUEUE_FILE"
echo "COMPLETED_FILE from config.yaml: $COMPLETED_FILE"
echo "ONHOLD_FILE from config.yaml: $ONHOLD_FILE"
echo "SKIP_IF_FAIL_FLAG from config.yaml: $SKIP_IF_FAIL_FLAG"

echo "SKIP FILE PRESENT?"
[[ -f "$SKIP_IF_FAIL_FLAG" ]] && echo yes || echo no

# if queue file doesn't exist, error
if [[ ! -f "$QUEUE_FILE" ]]; then
    echo "Queue file $QUEUE_FILE does not exist, creating"
    touch "$QUEUE_FILE"
fi

while true; do
    if [[ -s "$QUEUE_FILE" ]]; then
        # Read and execute the first command, then remove it
        printf "\n"
        CMD=$(head -n 1 "$QUEUE_FILE")
        echo "=== $CMD ==="
	# read -p "Enter to continue..."
	eval $CMD
    if [[ $? -eq 0 ]]; then
        echo "$CMD" >> "$COMPLETED_FILE"
        sed -i '1d' "$QUEUE_FILE"
    else
	# handle error differently if this flag exists
	if [[ ! -f "$SKIP_IF_FAIL_FLAG" ]]; then
		echo "Command failed/killed; not moving to completed file"
		read -p "Restart queue by hitting enter, or Ctrl+C again to exit"
	else
		echo "Command failed/killed; not moving to completed file"
		echo "Skip if fail is set; putting command in onhold and continuing"
		echo "$CMD" >> "$ONHOLD_FILE"
		sed -i '1d' "$QUEUE_FILE"
	fi
    fi

	printf "\nWaiting for next command...\n"
    else
        sleep 1  # Wait before checking again
    fi
done
