#!/bin/bash

EXP_NAME=$1
IMAGE_WIDTH=$2
IMAGE_HEIGHT=$3
KALIBR_COMMON_CACHE=$4
COORDS_2D_FILENAME=$5
COORDS_2D_SUCCESSES_FILENAME=$6
OUTPUT_DIR=$7
PID=$8
FOCAL_LENGTH_GUESS=$9
xhost +SI:localuser:root

echo "Running Kalibr calibraiton for $EXP_NAME..."
docker stop kalibr-$EXP_NAME-calib-trial-$PID
docker run --rm \
    --platform linux/amd64 \
    -e "DISPLAY" -e "QT_X11_NO_MITSHM=1" \
    --name kalibr-$EXP_NAME-calib-trial-$PID \
    -v "/tmp/.X11-unix:/tmp/.X11-unix:rw" \
    -v "$KALIBR_COMMON_CACHE:/data" \
    -v "$OUTPUT_DIR:/output" \
    kalibr \
    "KALIBR_MANUAL_FOCAL_LENGTH_INIT=1 FOCAL_LENGTH_GUESS=$FOCAL_LENGTH_GUESS rosrun kalibr kalibr_calibrate_cameras --dont-show-report \
    --detection-coords /data/$COORDS_2D_FILENAME \
    --detection-successes /data/$COORDS_2D_SUCCESSES_FILENAME \
    --image-width $IMAGE_WIDTH --image-height $IMAGE_HEIGHT \
    --topics /cam0/image_raw --models pinhole-radtan \
    --target /data/target.yaml \
    --report-dir /output \
    --init-mode fixed_point;"
