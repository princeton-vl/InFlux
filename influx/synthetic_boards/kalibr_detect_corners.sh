#!/bin/bash

EXP_NAME=$1
IMAGE_INPUT_FOLDER=$2
KALIBR_COMMON_CACHE=$3
COORDS_2D_FILENAME=$4
COORDS_2D_SUCCESSES_FILENAME=$5
xhost +SI:localuser:root

echo "Running corner detection for $EXP_NAME..."
docker stop kalibr-$EXP_NAME-corner-detection
docker run --rm \
    --platform linux/amd64 \
    -e "DISPLAY" -e "QT_X11_NO_MITSHM=1" \
    --name kalibr-$EXP_NAME-corner-detection \
    -v "/tmp/.X11-unix:/tmp/.X11-unix:rw" \
    -v "$IMAGE_INPUT_FOLDER:/input_images" \
    -v "$KALIBR_COMMON_CACHE:/data" \
    kalibr \
    "rosrun kalibr kalibr_detect_corners \
    --target /data/target.yaml \
    --models pinhole-radtan \
    --topics /cam0/image_raw \
    --frames-dir /input_images \
    --output-dir /data \
    --detection-coords /data/$4 \
    --detection-successes /data/$5"