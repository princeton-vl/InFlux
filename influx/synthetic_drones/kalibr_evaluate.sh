#!/bin/bash

EXP_NAME=$1
GUESS=$2
IMAGE_WIDTH=$3
IMAGE_HEIGHT=$4
KALIBR_COMMON_CACHE=$5
DETECTION_COORDS_NAME=$6
DETECTION_SUCCESSES_NAME=$7
TARGET_SPEC_NAME=$8
CALIB_INITIALIZATION_FILE=$9
REPORT_DIR=${10}
PID=${11}

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
    echo "crashed" > "$REPORT_DIR/calib-results-cam.txt"
    exit 0  # Exit gracefully
fi

echo "Running Kalibr evaluation for $EXP_NAME..."
echo "CONTAINER NAME: kalibr-$EXP_NAME-eval-trial-$PID"
docker run --rm \
    --platform linux/amd64 \
    -e "DISPLAY" -e "QT_X11_NO_MITSHM=1" \
    --name kalibr-$EXP_NAME-eval-trial-$PID \
    -v "/tmp/.X11-unix:/tmp/.X11-unix:rw" \
    -v "$KALIBR_COMMON_CACHE:/data" \
    -v "$REPORT_DIR:/report" \
    kalibr \
    "KALIBR_MANUAL_FOCAL_LENGTH_INIT=1 FOCAL_LENGTH_GUESS=$GUESS rosrun kalibr kalibr_calibrate_cameras --dont-show-report \
    --detection-coords /data/$DETECTION_COORDS_NAME \
    --detection-successes /data/$DETECTION_SUCCESSES_NAME \
    --image-width $IMAGE_WIDTH --image-height $IMAGE_HEIGHT \
    --topics /cam0/image_raw --models pinhole-radtan \
    --target /data/$TARGET_SPEC_NAME \
    --init-mode override --init-intrinsics $FX $FY $CX $CY --init-distortion $K1 $K2 $P1 $P2 \
    --report-dir /report \
    --eval;"
