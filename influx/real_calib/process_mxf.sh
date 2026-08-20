#!/bin/bash

if [ $# -ne 3 ] && [ $# -ne 4 ] && [ $# -ne 5 ]; then
    echo "Usage: $0 <MXF FILE> <FRAMES DIR> <METADATA PATH> [<START FRAME> [<END FRAME>]]"
    exit 1
fi

MXF=$1
FRAMESDIR=$2
METAPATH=$3

mkdir -p "$FRAMESDIR"


if [ $# -eq 3 ]; then
    echo "NO ARGS GIVEN"
    # extract metadata
    art-cmd export --input "$MXF" --output "$METAPATH" && echo "--> METADATA EXPORTED" &

    # extract frames with Rec.709 colorspace (tiff files)
    art-cmd process --input "$MXF" \
        --target-colorspace Rec.709/D65/BT.1886 \
        --output "$FRAMESDIR/%07d.tiff" && echo "--> TIFF FRAMES EXPORTED" &
elif [ $# -eq 4 ]; then
    # only start given
    echo "ONLY START GIVEN"
    START_IDX=$4

    # if $METAPATH doesn't exist, run this command. else, do nothing.
    if [ ! -f "$METAPATH" ]; then
        art-cmd export --input "$MXF" --output "$METAPATH" && echo "--> METADATA EXPORTED" &
    fi

    art-cmd process --input "$MXF" \
        --target-colorspace Rec.709/D65/BT.1886 \
        --output "$FRAMESDIR/%07d.tiff" \
        --start $START_IDX && echo "--> TIFF FRAMES EXPORTED ($START_IDX onward)" &
else
    echo "START AND END GIVEN"
    START_IDX=$4
    END_IDX=$5
    DURATION=$((END_IDX-START_IDX+1))

    # extract metadata
    art-cmd export --input "$MXF" --output "$METAPATH" --start $START_IDX --duration $DURATION && echo "--> METADATA EXPORTED" &

    art-cmd process --input "$MXF" \
        --target-colorspace Rec.709/D65/BT.1886 \
        --output "$FRAMESDIR/%07d.tiff" \
        --start $START_IDX --duration $DURATION && echo "--> TIFF FRAMES EXPORTED ($START_IDX to $END_IDX)" &
fi

wait # both child processes must finish
