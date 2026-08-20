#!/bin/bash

EXP_NAME=$1
IMAGE_WIDTH=$2
IMAGE_HEIGHT=$3
KALIBR_COMMON_CACHE=$4
DETECTION_COORDS_NAME=$5
DETECTION_SUCCESSES_NAME=$6
TARGET_SPEC_NAME=$7
REPORT_DIR=$8
PID=$9
FOCAL_LENGTH_GUESS=${10}

echo "Running Kalibr calibration for $EXP_NAME..."
echo "CONTAINER NAME: kalibr-$EXP_NAME-calib-trial-$PID"
docker run --rm \
    --platform linux/amd64 \
    -e "DISPLAY" -e "QT_X11_NO_MITSHM=1" \
    --name kalibr-$EXP_NAME-calib-trial-$PID \
    -v "/tmp/.X11-unix:/tmp/.X11-unix:rw" \
    -v "$KALIBR_COMMON_CACHE:/data" \
    -v "$REPORT_DIR:/report" \
    kalibr \
    "KALIBR_MANUAL_FOCAL_LENGTH_INIT=1 FOCAL_LENGTH_GUESS=$FOCAL_LENGTH_GUESS rosrun kalibr kalibr_calibrate_cameras --dont-show-report \
    --detection-coords /data/$DETECTION_COORDS_NAME \
    --detection-successes /data/$DETECTION_SUCCESSES_NAME \
    --image-width $IMAGE_WIDTH --image-height $IMAGE_HEIGHT \
    --topics /cam0/image_raw --models pinhole-radtan \
    --target /data/$TARGET_SPEC_NAME \
    --init-mode fixed_point \
    --report-dir /report && chgrp -R sudo /report && chmod -R g+w /report;"
