import csv
import cv2
import json
import math
import numpy as np
import os
import psutil
import shutil
import subprocess
import sys
import yaml


from board_generation import run_calib_visualization
from distort_utils import get_distorted_images_parallel, get_distorted_coords

if __name__ == "__main__":
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    sys.path.append(os.path.dirname(SCRIPT_DIR))

from common_utils import ensure_folders_exist, read_kalibr_result_file, create_flag_file, get_synth_board_exp_name


def get_board_target_config(board_size):
    """
    Returns Kalibr target metadata for each synthetic board assignment label.

    board_size is the experiment/assignment label, not always the physical
    board width. In particular:
      - 1.6 uses 96 mm tags on the same 0.8 x 0.6 m board.
      - 6.4 uses 384 mm tags on the same 3.2 x 2.4 m projected board/screen.
    """
    spacing_multiplier = 0.3

    if board_size == 0.1:
        tag_cols = 11
        tag_rows = 8
        tag_size = 0.006
    elif board_size == 0.2:
        tag_cols = 11
        tag_rows = 8
        tag_size = 0.012
    elif board_size == 0.4:
        tag_cols = 11
        tag_rows = 8
        tag_size = 0.024
    elif board_size == 0.8:
        tag_cols = 11
        tag_rows = 8
        tag_size = 0.048
    elif board_size == 1.6:
        tag_cols = 5
        tag_rows = 4
        tag_size = 0.096
    elif board_size == 3.2:
        tag_cols = 11
        tag_rows = 8
        tag_size = 0.192
    elif board_size == 6.4:
        tag_cols = 6
        tag_rows = 4
        tag_size = 0.384
    else:
        raise ValueError(
            "Invalid calibration board size. "
            "Pick from {0.1, 0.2, 0.4, 0.8, 1.6, 3.2, 6.4}"
        )

    return {
        "tagCols": tag_cols,
        "tagRows": tag_rows,
        "tagSize": tag_size,
        "tagSpacing": spacing_multiplier,
        "target_type": "aprilgrid",
    }


def run_board_experiment(board_size, noise_level, lens_focal_length_in_mm, camera_focal_length_in_mm, pinhole_to_obj_in_m, resolution_percentage, camera_type, lens_name, root_folder, settings_path, exp_name, distortion=[0, 0, 0, 0], num_trials=1, print_header='', verbose=False):
    # Create folder structure
    folder_paths = []
    calib_folder_paths = []
    calib_result_filepaths = []
    eval_folder_paths = []
    eval_result_filepaths = []

    exp_root_folder = f'{root_folder}/{exp_name}'
    folder_paths.append(exp_root_folder)

    no_distortion_exp_folder_name = f'{exp_name}/no_distortion_data'
    no_distortion_exp_folder = f'{root_folder}/{no_distortion_exp_folder_name}'
    folder_paths.append(no_distortion_exp_folder)

    with_distortion_exp_folder = f'{root_folder}/{exp_name}/with_distortion_data'
    folder_paths.append(with_distortion_exp_folder)

    gt_folder = f'{exp_root_folder}/ground_truth'
    folder_paths.append(gt_folder)

    flags_folder = f'{exp_root_folder}/flags'
    folder_paths.append(flags_folder)

    kalibr_folder = f'{exp_root_folder}/kalibr_common_cache'
    folder_paths.append(kalibr_folder)

    results_folder = f'{exp_root_folder}/results'
    folder_paths.append(results_folder)

    trial_indices = [x for x in range(num_trials)]

    for trial_index in trial_indices:
        calib_folder_paths.append(f'{exp_root_folder}/trial_{trial_index}_with_guess/calibration')

    for trial_index in trial_indices:
        eval_folder_paths.append(f'{exp_root_folder}/trial_{trial_index}_with_guess/evaluation')

    ensure_folders_exist(folder_paths)
    ensure_folders_exist(calib_folder_paths)
    ensure_folders_exist(eval_folder_paths)

    # Define auto-generated result file naming conventions
    gt_intrinsics_filepath = f'{gt_folder}/gt_intrinsics.json'
    image_dimensions_filepath = f'{kalibr_folder}/image_dims.json'
    for trial_index in trial_indices:
        calib_result_filepaths.append(f'{results_folder}/trial_{trial_index}_with_guess_calib_result.json')
        eval_result_filepaths.append(f'{results_folder}/trial_{trial_index}_with_guess_eval_result.json')

    assert len(calib_folder_paths) == len(calib_result_filepaths)
    assert len(eval_folder_paths) == len(eval_result_filepaths)

    # Kalibr output locations
    kalibr_target_yaml_filepath = f'{kalibr_folder}/target.yaml'
    kalibr_coords_2d_filename = 'kalibr_coords_2d.csv'
    # kalibr_coords_2d_filepath = f'{kalibr_folder}/{kalibr_coords_2d_filename}'
    kalibr_coords_2d_successes_filename = 'kalibr_coords_2d_successes.csv'
    # kalibr_coords_2d_successes_filepath = f'{kalibr_folder}/{kalibr_coords_2d_successes_filename}'

    # Flags for pipeline progress tracking
    no_distortion_flag = f'{flags_folder}/step1_no_distortion_completed.txt'
    with_distortion_flag = f'{flags_folder}/step2_with_distortion_complete.txt'
    target_yaml_flag = f'{flags_folder}/step3_target_yaml_complete.txt'
    kalibr_coordinate_detection_flag = f'{flags_folder}/step4_kalibr_coordinate_detection_complete.txt'
    kalibr_calibration_flag = f'{flags_folder}/step5_kalibr_calibration_complete.txt'
    kalibr_evaluation_flag = f'{flags_folder}/step6_kalibr_evaluation_complete.txt'

    ### Generate images with no distortion
    if not os.path.isfile(no_distortion_flag):
        print(f'{print_header} Generating undistorted synthetic images for {exp_name}...')
        run_calib_visualization(board_size, noise_level, camera_focal_length_in_mm, pinhole_to_obj_in_m, resolution_percentage, camera_type, root_folder, no_distortion_exp_folder_name)
        print(camera_focal_length_in_mm, pinhole_to_obj_in_m)
        create_flag_file(no_distortion_flag)

    with open(f'{no_distortion_exp_folder}/calibration_matrix.txt', 'r') as file:
        calib_data = file.read().strip()
        calib_data = calib_data.split(',')
        calib_data = [float(x) for x in calib_data]
        calib_matrix = np.array([
            [calib_data[0], 0, calib_data[2]],
            [0, calib_data[1], calib_data[3]],
            [0, 0, 1],
        ])

    ### Generate images with distortion
    # We do not need to rerun distortion if 1) distortion flag is set AND 2) distortion values match
    # last ran settings
    run_distortion = True
    if os.path.isfile(with_distortion_flag):
        # Read in ground truth intrinsics
        with open(gt_intrinsics_filepath, 'r') as file:
            loaded_gt_intrinsics_dict = json.load(file)

        if loaded_gt_intrinsics_dict['k1'] == distortion[0] and \
            loaded_gt_intrinsics_dict['k2'] == distortion[1] and \
            loaded_gt_intrinsics_dict['p1'] == distortion[2] and \
            loaded_gt_intrinsics_dict['p2'] == distortion[3]:
            run_distortion = False

    if run_distortion:
        print(f'{print_header} Adding distortion to images...')
        # Update coords_2d.csv
        img_indices = []
        coords = []
        with open(f'{no_distortion_exp_folder}/coords_2d.csv', 'r') as file:
            reader = csv.reader(file)
            for row in reader:
                img_indices.append(int(row[0]))
                coords.append([float(row[1]), float(row[2])])

        x_distorted, y_distorted = get_distorted_coords(calib_matrix, distortion, np.array(coords))

        with open(f'{with_distortion_exp_folder}/coords_2d.csv', mode='w', newline='') as file:
            writer = csv.writer(file)

            # Write each point on a new line
            for i, img_index in enumerate(img_indices):
                writer.writerow((img_index, x_distorted[i], y_distorted[i]))

        # Distort each blender image
        image_names = [x for x in os.listdir(f'{no_distortion_exp_folder}') if x.lower().endswith('.png')]
        original_image_paths = [f'{no_distortion_exp_folder}/{img_name}' for img_name in image_names]
        distorted_image_paths = [f'{with_distortion_exp_folder}/{img_name}' for img_name in image_names]

        get_distorted_images_parallel(calib_matrix, distortion, original_image_paths, distorted_image_paths)

        distorted_img = cv2.imread(distorted_image_paths[0])

        # Get image dimensions
        image_height, image_width, _ = distorted_img.shape
        image_dims_dict = {
            'image_height': image_height,
            'image_width': image_width
        }
        with open(image_dimensions_filepath, 'w') as file:
            json.dump(image_dims_dict, file, indent=4)

        # Copy other files over to main folder
        shutil.copy(f'{no_distortion_exp_folder}/coords_3d.csv', f'{with_distortion_exp_folder}/coords_3d.csv')

        # Create intrinsics ground truth file
        gt_intrinsics_dict = {
            'fx': calib_matrix[0][0],
            'fy': calib_matrix[1][1],
            'cx': calib_matrix[0][2],
            'cy': calib_matrix[1][2],
            'k1': distortion[0],
            'k2': distortion[1],
            'p1': distortion[2],
            'p2': distortion[3]
        }

        # Write ground truth intrinisics
        with open(gt_intrinsics_filepath, 'w') as file:
            json.dump(gt_intrinsics_dict, file, indent=4)

        create_flag_file(with_distortion_flag)

    ### Run Kalibr experiments
    # Kalibr setup: create target.yaml file, if needed
    if not os.path.isfile(target_yaml_flag):
        print(f'{print_header} Generating target.yaml...')
        # Generate a target.yaml based on inputs
        target_yaml_config = get_board_target_config(board_size)

        with open(kalibr_target_yaml_filepath, 'w') as file:
            yaml.dump(target_yaml_config, file)
        create_flag_file(target_yaml_flag)

    # Kalibr setup: create 2D coordinate detection files, if needed
    if not os.path.isfile(kalibr_coordinate_detection_flag):
        print(f'{print_header} Generating 2D coordinate detections...')
        # Select which frames to use and create Kalibr bag file
        # No-op: we use all synthetic frames
        selected_image_frames_folder = with_distortion_exp_folder

        # Determine batch size
        avail_ram = psutil.virtual_memory().available / 1024**3 # in GB
        worker_frames = math.floor(avail_ram / 0.01323456) * 0.98 # to give a buffer
        # 1690 / 32 * (num GB RAM)
        print("Workerframes available:", worker_frames)
        # if we allocate abt 70% memory to these processes (so we don't max out memory; seems like the baseline computer memory usage is around 25%)
        # we have ~1690 worker-frames at our disposal. so we can do floor(1690 / num_frames) at a time, (if memory is the constraint)
        cpu_constrained_num_workers = os.cpu_count() - 3
        mem_constrained_num_workers = math.floor(worker_frames / 100)
        if mem_constrained_num_workers < cpu_constrained_num_workers:
            # make smarter batch sizes, spreading out the work
            batches = math.ceil(num_trials / mem_constrained_num_workers)
            num_workers = math.ceil(num_trials / batches)
            print(f"NOTE: Too many frames to use {cpu_constrained_num_workers} parallel processes. Using {num_workers} instead")
        else:
            num_workers = cpu_constrained_num_workers

        run_kalibr_scripts(
            [['./kalibr_detect_corners.sh', f'{exp_name}', selected_image_frames_folder, kalibr_folder, kalibr_coords_2d_filename, kalibr_coords_2d_successes_filename]],
            [f'{kalibr_folder}/coords_2d_detection_log.txt'],
            kill_container_pattern=exp_name,
            verbose=verbose,
            num_workers=num_workers
        )
        create_flag_file(kalibr_coordinate_detection_flag)

    # Run multiple trials of Kalibr calibration
    # if results have not been generated
    if not os.path.isfile(kalibr_calibration_flag):
        with open(image_dimensions_filepath, 'r') as file:
            image_dims_data = json.load(file)

            image_width = image_dims_data['image_width']
            image_height = image_dims_data['image_height']

        print(f'{print_header} Running Kalibr for {exp_name}...')

        # Compute focal length guess
        flg = lens_focal_length_in_mm * 3424 / 28.25

        cmds = []
        log_filepaths = []

        for pid, calib_folder_path in enumerate(calib_folder_paths):
            curr_cmd = [
                './kalibr_run_calibration_with_guess.sh',
                f'{exp_name}',
                str(image_width),
                str(image_height),
                kalibr_folder,
                kalibr_coords_2d_filename,
                kalibr_coords_2d_successes_filename,
                str(calib_folder_path),
                str(pid),
                str(flg),
            ]

            cmds.append(curr_cmd)
            log_filepaths.append(f'{calib_folder_path}/kalibr_calib_log.txt')

        # Determine batch size
        avail_ram = psutil.virtual_memory().available / 1024**3 # in GB
        worker_frames = math.floor(avail_ram / 0.01323456) * 0.98 # to give a buffer
        # 1690 / 32 * (num GB RAM)
        print("Workerframes available:", worker_frames)
        # if we allocate abt 70% memory to these processes (so we don't max out memory; seems like the baseline computer memory usage is around 25%)
        # we have ~1690 worker-frames at our disposal. so we can do floor(1690 / num_frames) at a time, (if memory is the constraint)
        cpu_constrained_num_workers = os.cpu_count() - 3
        mem_constrained_num_workers = math.floor(worker_frames / 100)
        if mem_constrained_num_workers < cpu_constrained_num_workers:
            # make smarter batch sizes, spreading out the work
            batches = math.ceil(num_trials / mem_constrained_num_workers)
            num_workers = math.ceil(num_trials / batches)
            print(f"NOTE: Too many frames to use {cpu_constrained_num_workers} parallel processes. Using {num_workers} instead")
        else:
            num_workers = cpu_constrained_num_workers

        run_kalibr_scripts(
            cmds,
            log_filepaths,
            kill_container_pattern=exp_name,
            verbose=verbose,
            num_workers=num_workers
        )

        # Read and record Kalibr calibration results
        for calib_folder_path, calib_result_filepath in zip(calib_folder_paths, calib_result_filepaths):
            calib_result_dict = read_kalibr_result_file(f'{calib_folder_path}/calib-results-cam.txt')

            with open(calib_result_filepath, 'w') as file:
                json.dump(calib_result_dict, file, indent=4)

        create_flag_file(kalibr_calibration_flag)

    # Run multiple trials of Kalibr evaluation
    # if results have not been generated
    if not os.path.isfile(kalibr_evaluation_flag):
        with open(image_dimensions_filepath, 'r') as file:
            image_dims_data = json.load(file)

            image_width = image_dims_data['image_width']
            image_height = image_dims_data['image_height']

        # Determine batch size
        avail_ram = psutil.virtual_memory().available / 1024**3 # in GB
        worker_frames = math.floor(avail_ram / 0.01323456) * 0.98 # to give a buffer
        # 1690 / 32 * (num GB RAM)
        print("Workerframes available:", worker_frames)
        # if we allocate abt 70% memory to these processes (so we don't max out memory; seems like the baseline computer memory usage is around 25%)
        # we have ~1690 worker-frames at our disposal. so we can do floor(1690 / num_frames) at a time, (if memory is the constraint)
        cpu_constrained_num_workers = os.cpu_count() - 3
        mem_constrained_num_workers = math.floor(worker_frames / 100)
        if mem_constrained_num_workers < cpu_constrained_num_workers:
            # make smarter batch sizes, spreading out the work
            batches = math.ceil(num_trials / mem_constrained_num_workers)
            num_workers = math.ceil(num_trials / batches)
            print(f"NOTE: Too many frames to use {cpu_constrained_num_workers} parallel processes. Using {num_workers} instead")
        else:
            num_workers = cpu_constrained_num_workers

        print(f'{print_header} Running Kalibr evaluation for {exp_name}...')
        run_kalibr_scripts(
            [['./kalibr_run_evaluation.sh', f'{exp_name}', str(image_width), str(image_height), kalibr_folder, kalibr_coords_2d_filename, kalibr_coords_2d_successes_filename, str(paths[0]), str(paths[1]), str(pid)] for pid, paths in enumerate(zip(calib_result_filepaths, eval_folder_paths))],
            [f'{eval_folder_path}/kalibr_eval_log.txt' for eval_folder_path in eval_folder_paths],
            kill_container_pattern=exp_name,
            verbose=verbose,
            num_workers=num_workers
        )

        # Read and record Kalibr evaluation results
        for eval_folder_path, eval_result_filepath in zip(eval_folder_paths, eval_result_filepaths):
            eval_result_dict = read_kalibr_result_file(f'{eval_folder_path}/calib-results-cam.txt')

            with open(eval_result_filepath, 'w') as file:
                json.dump(eval_result_dict, file, indent=4)

        create_flag_file(kalibr_evaluation_flag)


def run_kalibr_scripts(commands, log_filepaths, kill_container_pattern=None, verbose=False, num_workers=None):
    assert isinstance(commands, list) and all(isinstance(cmd, list) for cmd in commands)
    assert isinstance(log_filepaths, list) and all(isinstance(path, str) for path in log_filepaths)
    assert len(commands) == len(log_filepaths)

    batch_size = num_workers

    # Start all processes and store them in a list
    for i in range(0, len(commands), batch_size):
        batch_commands = commands[i:i+batch_size]
        batch_logs = log_filepaths[i:i+batch_size]
        print(f"Starting batch of processes (({i+1} - {i+len(batch_commands)}) / {len(commands)})...")
        processes = []
        for cmd in batch_commands:
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                processes.append(proc)
            except (OSError, subprocess.SubprocessError) as e:
                print(f"Failed to start process {cmd}: {e}")
                with open(log_filepaths[commands.index(cmd)], "w") as file:
                    file.write(f"PROCESS START ERROR:\n{e}\n")
                continue  # Skip to next command

        for proc, log_filepath in zip(processes, batch_logs):
            try:
                stdout, stderr = proc.communicate()  # Wait for process completion
                exit_code = proc.returncode  # Get exit status

                # Write output to log file
                with open(log_filepath, 'w') as file:
                    file.write(stdout.strip())
                    if stderr:
                        file.write("\n\nERROR:\n" + stderr.strip())
                    if exit_code != 0:
                        file.write(f"\n\nPROCESS EXITED WITH CODE {exit_code}")

                if verbose:
                    print(f"Process {proc.pid} finished with exit code {exit_code}")

            except BaseException as e:
                if isinstance(e, Exception):
                    with open(log_filepath, 'a') as file:
                        file.write(f"\n\nLOGGING ERROR:\n{e}\n")
                    print(f"Error logging output for process {proc.pid}: {e}")
                if kill_container_pattern:
                    subprocess.run(f"docker container ls -q --filter name={kill_container_pattern} | xargs docker container rm -f", shell=True)
                    print(f"KILLED DOCKER CONTAINERS MATCHING {kill_container_pattern}", flush=True)
                if isinstance(e, KeyboardInterrupt):
                    print("KeyboardInterrupt received. Exiting...")
                    sys.exit(1)

    print("All processes completed.")


if __name__ == "__main__":
    raise SystemExit(
        "This module is a helper and is not a supported standalone entrypoint. Run run_all_boards.py instead."
    )
