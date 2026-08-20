import numpy as np
from types import SimpleNamespace

class AttributeObj(SimpleNamespace):
    '''
    Mimics an ArgumentParser.parse_args() object.
    Attributes passed as kwargs can be accessed via the dot operator.
    If an attribute does not exist, return None rather than erroring.
    '''
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def __getattribute__(self, value):
        try:
            return super().__getattribute__(value)
        except AttributeError:
            return None

def read_intrinsic_matrix(file_path):
    with open(file_path, 'r') as file:
        lines = file.readlines()

    matrix_lines = [line.strip(" <Matrix>\n") for line in lines if '(' in line]

    matrix = []
    for line in matrix_lines:
        values = line[line.find('(')+1 : line.find(')')].split(',')
        row = [float(value.strip()) for value in values]
        matrix.append(row)

    return np.array(matrix)


### FOLDER NAME / FILENAME CONSTANTS ###

## SUBFOLDERS ##
GROUND_TRUTH = "ground_truth"
KALIBR_COMMON_CACHE = "kalibr_common_cache"
NO_DISTORTION_DATA = "no_distortion_data"
WITH_DISTORTION_DATA = "with_distortion_data"
FLAGS = "flags"
RESULTS = "results"
RUN_METADATA = "run_metadata"

## FLAGS ##
# WRITE_RUN_METADATA_COMPLETE = f"{FLAGS}/step1_write_run_metadata_complete.txt"
FOCAL_LENGTH_GUESS_COMPLETE = f"{FLAGS}/step1_focal_length_guess_complete.txt"
MOVEMENT_GENERATION_COMPLETE = f"{FLAGS}/step2_movement_generation_complete.txt"
RENDERS_COMPLETE = f"{FLAGS}/step3_renders_complete.txt"
DISTORTION_COMPLETE = f"{FLAGS}/step4_distortion_complete.txt"
DETECTION_COMPLETE = f"{FLAGS}/step5_detection_complete.txt"
CALIB_COMPLETE = f"{FLAGS}/step6_calib_complete.txt"
EVAL_COMPLETE = f"{FLAGS}/step7_eval_complete.txt"

## Step-specific filenames ##

# Metadata
TARGET_PARAMETERS = f"{RUN_METADATA}/target_parameters.json" # in case its needs to be read from

# Drone positions
GT_INTRINSICS = f"{GROUND_TRUTH}/gt_intrinsics.json"
GT_3D_CSV = f"{NO_DISTORTION_DATA}/gt_coords_3d.csv"
TARGET_CSV = f"{NO_DISTORTION_DATA}/coords_3d.csv"
TARGET_NORM_CSV = f"{NO_DISTORTION_DATA}/coords_3d_norm.csv"
TARGET_YAML = f"{KALIBR_COMMON_CACHE}/target.yaml"
ANGLES_CSV = f"{NO_DISTORTION_DATA}/angles.csv"
NUM_ACCEPTED = f"{NO_DISTORTION_DATA}/num_accepted.txt"
DETECTION_COORDS = f"{NO_DISTORTION_DATA}/coords_2d.csv"
DETECTION_COORDS_PLOT = f"{NO_DISTORTION_DATA}/coords_plot.png"
DETECTION_SUCCESSES = f"{NO_DISTORTION_DATA}/coords_2d_successes.csv"

# Rendering
CALIBRATION_MATRIX = f"{NO_DISTORTION_DATA}/calibration_matrix.txt"
IMAGE_DIMS = f"{KALIBR_COMMON_CACHE}/image_dims.json"

# Distorting
DETECTION_COORDS_DISTORTED = f"{WITH_DISTORTION_DATA}/coords_2d_gt.csv"

# Detecting
DETECTION_COORDS_DISTORTED_PREDICTED = f"{WITH_DISTORTION_DATA}/coords_2d.csv"
DETECTION_SUCCESSES_DISTORTED_PREDICTED = f"{WITH_DISTORTION_DATA}/coords_2d_successes.csv"
KALIBR_DETECTION_COORDS= f"{KALIBR_COMMON_CACHE}/kalibr_coords_2d.csv"
KALIBR_DETECTION_SUCCESSES= f"{KALIBR_COMMON_CACHE}/kalibr_coords_2d_successes.csv"

# Kalibr
KALIBR_CALIB_LOG = "kalibr_calib_log.txt"
KALIBR_EVAL_LOG = "kalibr_eval_log.txt"
RESULTS_CAM = "calib-results-cam.txt"
REPORT_CAM = "calib-report-cam.pdf"
