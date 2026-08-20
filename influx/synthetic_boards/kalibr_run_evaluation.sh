#!/bin/bash

EXP_NAME=$1
IMAGE_WIDTH=$2
IMAGE_HEIGHT=$3
KALIBR_COMMON_CACHE=$4
COORDS_2D_FILENAME=$5
COORDS_2D_SUCCESSES_FILENAME=$6
CALIB_INITIALIZATION_FILE=$7
OUTPUT_DIR=$8
PID=$9
xhost +SI:localuser:root

# Parse calibration result file
# Extract values from JSON, ensuring they are not null or empty
FX=$(jq -r '.fx // empty' "$CALIB_INITIALIZATION_FILE" | awk '{printf "%.10f\n", $1}')
FY=$(jq -r '.fy // empty' "$CALIB_INITIALIZATION_FILE" | awk '{printf "%.10f\n", $1}')
CX=$(jq -r '.cx // empty' "$CALIB_INITIALIZATION_FILE" | awk '{printf "%.10f\n", $1}')
CY=$(jq -r '.cy // empty' "$CALIB_INITIALIZATION_FILE" | awk '{printf "%.10f\n", $1}')
K1=$(jq -r '.k1 // empty' "$CALIB_INITIALIZATION_FILE" | awk '{printf "%.10f\n", $1}')
K2=$(jq -r '.k2 // empty' "$CALIB_INITIALIZATION_FILE" | awk '{printf "%.10f\n", $1}')
P1=$(jq -r '.p1 // empty' "$CALIB_INITIALIZATION_FILE" | awk '{printf "%.10f\n", $1}')
P2=$(jq -r '.p2 // empty' "$CALIB_INITIALIZATION_FILE" | awk '{printf "%.10f\n", $1}')

# Adjust CX and CY by subtracting 0.5 (convert from normal convention back to Kalibr)
CX=$(echo "$CX - 0.5" | bc)
CY=$(echo "$CY - 0.5" | bc)

# Check if any value (except K1, K2, P1, P2) is empty or zero
if [[ -z "$FX" || "$FX" == "0.0000000000" || -z "$FY" || "$FY" == "0.0000000000" ||
      -z "$CX" || "$CX" == "0.0000000000" || -z "$CY" || "$CY" == "0.0000000000" ]]; then
    echo "Error: One or more calibration values (FX, FY, CX, CY) are missing or zero."
    echo "crashed" > "$OUTPUT_DIR/calib-results-cam.txt"
    exit 0  # Exit gracefully
fi

echo "Running Kalibr evaluation for $EXP_NAME..."
docker stop kalibr-$EXP_NAME-eval-trial-$PID
docker run --rm \
    --platform linux/amd64 \
    -e "DISPLAY" -e "QT_X11_NO_MITSHM=1" \
    --name kalibr-$EXP_NAME-eval-trial-$PID \
    -v "/tmp/.X11-unix:/tmp/.X11-unix:rw" \
    -v "$KALIBR_COMMON_CACHE:/data" \
    -v "$OUTPUT_DIR:/output" \
    kalibr \
    "rosrun kalibr kalibr_calibrate_cameras --dont-show-report \
    --detection-coords /data/$COORDS_2D_FILENAME \
    --detection-successes /data/$COORDS_2D_SUCCESSES_FILENAME \
    --image-width $IMAGE_WIDTH --image-height $IMAGE_HEIGHT \
    --topics /cam0/image_raw --models pinhole-radtan \
    --target /data/target.yaml \
    --report-dir /output \
    --init-mode override --init-intrinsics $FX $FY $CX $CY --init-distortion $K1 $K2 $P1 $P2 \
    --eval;"
