import csv
import cv2
import json
import numpy as np
import os
import pandas as pd
import shutil
import sys

from syn_drone_single import main as render_drone_frames
from utils import read_intrinsic_matrix
from utils import ANGLES_CSV, GT_INTRINSICS, CALIBRATION_MATRIX, DETECTION_COORDS, DETECTION_COORDS_DISTORTED, DETECTION_COORDS_DISTORTED_PREDICTED, KALIBR_DETECTION_COORDS, KALIBR_DETECTION_SUCCESSES, DETECTION_COMPLETE, DETECTION_SUCCESSES_DISTORTED_PREDICTED, WITH_DISTORTION_DATA, NO_DISTORTION_DATA, IMAGE_DIMS, RENDERS_COMPLETE, TARGET_CSV, DISTORTION_COMPLETE, GT_3D_CSV

if __name__ == "__main__":
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    sys.path.append(os.path.dirname(SCRIPT_DIR))
    sys.path.append(os.path.join(os.path.dirname(SCRIPT_DIR), "synthetic_boards"))

from synthetic_boards.distort_utils import get_distorted_coords, get_distorted_images_parallel
from common_utils import create_flag_file, flag_missing

def distort_images(exp_root_folder, distortion):

    nodist_frames_dir = f"{exp_root_folder}/{NO_DISTORTION_DATA}"
    dist_frames_dir = f"{exp_root_folder}/{WITH_DISTORTION_DATA}"
    det_coords_nodist_csv = f"{exp_root_folder}/{DETECTION_COORDS}"
    det_coords_dist_csv = f'{exp_root_folder}/{DETECTION_COORDS_DISTORTED}'
    image_dims_path = f'{exp_root_folder}/{IMAGE_DIMS}'
    file_calib_mx = f"{exp_root_folder}/{CALIBRATION_MATRIX}"

    intrinsics = read_intrinsic_matrix(file_calib_mx)
    # Create intrinsics ground truth file
    gt_intrinsics_dict = {
        'fx': intrinsics[0][0], 'fy': intrinsics[1][1], 'cx': intrinsics[0][2], 'cy': intrinsics[1][2],
        'k1': distortion[0], 'k2': distortion[1], 'p1': distortion[2], 'p2': distortion[3]
    }
    with open(f"{exp_root_folder}/{GT_INTRINSICS}", 'w') as file:
        json.dump(gt_intrinsics_dict, file, indent=4)

    os.makedirs(dist_frames_dir, exist_ok=True)

    # Distort each blender image
    image_names = [x for x in os.listdir(nodist_frames_dir) if x.lower().endswith('.png') or x.lower().endswith('.jpg')]
    image_names = [x for x in image_names if x.startswith('frame')]
    original_image_paths = [f'{nodist_frames_dir}/{img_name}' for img_name in image_names]
    distorted_image_paths = [f'{dist_frames_dir}/{img_name}' for img_name in image_names]

    get_distorted_images_parallel(intrinsics, distortion, original_image_paths, distorted_image_paths)

    # Update coords_2d.csv with distorted coordinates
    csv_data = pd.read_csv(det_coords_nodist_csv, header=None, names=['obs_idx', 'x_coord', 'y_coord'])
    x_distorted, y_distorted = get_distorted_coords(intrinsics, distortion, np.array(csv_data[['x_coord', 'y_coord']]))

    # write x_distorted and y_distorted to csv, but with "0," at start of each line. write to det_coords_dist_csv
    with open(det_coords_dist_csv, mode='w', newline='') as file:
        writer = csv.writer(file)
        for i in range(len(x_distorted)):
            writer.writerow((0, x_distorted[i], y_distorted[i]))

    # Write image dimensions to file
    img = cv2.imread(original_image_paths[0])
    height, width, _ = img.shape
    with open(image_dims_path, 'w') as file:
        json.dump({'image_width': width, 'image_height': height}, file)

    return f'{intrinsics[0][0]},{intrinsics[1][1]},{intrinsics[0][2]},{intrinsics[1][2]},{distortion[0]},{distortion[1]},{distortion[2]},{distortion[3]}'


def color_detect(exp_root_folder):
    # Define red color range (Red appears in two regions in HSV)
    red_lower1 = np.array([0, 120, 50])   # First lower bound
    red_upper1 = np.array([10, 255, 255]) # First upper bound

    red_lower2 = np.array([170, 120, 50])  # Second lower bound
    red_upper2 = np.array([180, 255, 255]) # Second upper bound

    # Input and output folders
    input = f'{exp_root_folder}/{WITH_DISTORTION_DATA}'

    centers_data = []
    successes_data = []

    def extract_frame_number(filename):
        try:
            num = int(filename.split('_')[1].split('.')[0])
            return num
        except:
            return -1

    for filename in sorted(os.listdir(input), key=extract_frame_number):
        if filename.endswith('.png'):

            image_path = os.path.join(input, filename)
            image = cv2.imread(image_path)
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

            # Create two masks and combine them
            mask1 = cv2.inRange(hsv, red_lower1, red_upper1)
            mask2 = cv2.inRange(hsv, red_lower2, red_upper2)
            red_mask = cv2.bitwise_or(mask1, mask2)

            # Find contours in the red mask
            contours, _ = cv2.findContours(red_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            center = None
            success = 0

            # Iterate through contours and check for valid ellipses
            for contour in contours:
                if len(contour) >= 5:  # Need at least 5 points to fit an ellipse
                    ellipse = cv2.fitEllipse(contour)
                    (x, y), (major_axis, minor_axis), angle = ellipse
                    if np.any(np.isnan([x, y, major_axis, minor_axis, angle])):
                        continue
                    center = [x + 0.5, y + 0.5] # fitEllipse returns coordinates shifted by 0.5 to the left, for some reason
                    success = 1

                    cv2.ellipse(image, ellipse, (0, 255, 0), 2)

            # Visualize to check that centers actually match up correctly manually
            if False:
                import matplotlib.pyplot as plt
                plt.imshow(image)
                plt.show()
                breakpoint()

            centers_data.append(center)
            successes_data.append(success)

            if center is None:
                print("none detected")

    # Write centers to csv file
    # also write kalibr version (with kalibr coordinate convention) to the kalibr_common_cache folder
    with open(f'{exp_root_folder}/{DETECTION_COORDS_DISTORTED_PREDICTED}', mode='w', newline='') as file:
        writer = csv.writer(file)
        # Write each point on a new line
        # write observation index 0 for each
        for point in centers_data:
            if point is not None:
                writer.writerow([0, point[0], point[1]])
            else:
                writer.writerow([0, 0, 0])

    with open(f'{exp_root_folder}/{KALIBR_DETECTION_COORDS}', mode='w', newline='') as file:
        writer = csv.writer(file)
        # subtract 0.5 for blender -> kalibr conversion
        for point in centers_data:
            if point is not None:
                writer.writerow([0, point[0] - 0.5, point[1] - 0.5])
            else:
                writer.writerow([0, 0, 0])

    # Write successes to csv file
    with open(f'{exp_root_folder}/{DETECTION_SUCCESSES_DISTORTED_PREDICTED}', mode='w', newline='') as file:
        writer = csv.writer(file)
        # Write each point on a new line
        # write observation index 0 for each
        for success in successes_data:
            writer.writerow([0, success])

    shutil.copyfile(f'{exp_root_folder}/{DETECTION_SUCCESSES_DISTORTED_PREDICTED}', f'{exp_root_folder}/{KALIBR_DETECTION_SUCCESSES}')

def main(args):
    root_folder = args.root_folder
    camera_type = args.camera_type
    distortion = args.distortion
    drone_radius = args.drone_radius
    led_radius = args.led_radius
    focal_length_mm = args.focal_length_mm
    pinhole_to_obj = args.pinhole_to_obj
    resolution_percentage = args.resolution_percentage

    exp_name = args.exp_name
    exp_root_folder = os.path.join(root_folder, exp_name)
    os.makedirs(exp_root_folder, exist_ok=True)

    # Render using ground truth 3d
    # (use noisy 3d coords due to rtk as input to Kalibr)
    # coords_3d = args.coords_3d or os.path.join(exp_root_folder, TARGET_CSV)
    gt_coords_3d = os.path.join(exp_root_folder, GT_3D_CSV)
    angles = args.angles or os.path.join(exp_root_folder, ANGLES_CSV)
    skip_if_exists = args.skip_if_exists

    # Generate renders
    if flag_missing(RENDERS_COMPLETE, exp_root_folder, skip_if_exists):
        n = render_drone_frames(gt_coords_3d, angles, exp_root_folder, led_radius, camera_type, focal_length_mm, pinhole_to_obj, resolution_percentage)
        create_flag_file(RENDERS_COMPLETE, exp_root_folder, str(n))
    else:
        print("=====> Renders exist. Skipping...")

    # Distort
    if flag_missing(DISTORTION_COMPLETE, exp_root_folder, skip_if_exists):
        distortion_data = distort_images(exp_root_folder, distortion)
        create_flag_file(DISTORTION_COMPLETE, exp_root_folder, distortion_data)
    else:
        print("=====> Distorted renders exist. Skipping...")

    # Detect targets
    if flag_missing(DETECTION_COMPLETE, exp_root_folder, skip_if_exists):
        color_detect(exp_root_folder)
        create_flag_file(DETECTION_COMPLETE, exp_root_folder)
    else:
        print("=====> Detection coordinates exist. Skipping...")


if __name__ == "__main__":
    raise SystemExit(
        "This module is a helper and is not a supported standalone entrypoint. Run run_all_drones.py instead."
    )
