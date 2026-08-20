import json
import math
import os
import psutil
import subprocess
import sys

from pathlib import Path

if __name__ == "__main__":
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    sys.path.append(os.path.dirname(SCRIPT_DIR))

from utils import *
from common_utils import get_synth_drone_exp_name, get_camera_info, get_lens_info, compute_k1, ensure_folders_exist, read_kalibr_result_file, flag_missing, create_flag_file

from generate_drone_movements import main as generate_drone_movements
from render_distort_detect import main as render_distort_detect


def run_drone_experiment(*, drone_radius, led_radius, x_density=4, y_density=3, num_planes=2, depth_variation=0.1, gps_noise_m=0, rtk_noise_cm=0, lens_focal_length_in_mm, camera_focal_length_in_mm, pinhole_to_obj_in_m, resolution_percentage, camera_type, lens, root_folder, settings_path=None, distortion=None, focal_length_guess=None, exp_name_override=None, num_trials=1, skip_if_exists=True, verbose=False, pause_each_step=False):
    sensor_width_mm, _, sensor_resolution_x, _, _ = get_camera_info(camera_type)
    min_lens_focal_length, max_lens_focal_length, _, _ = get_lens_info(lens)
    pause = input if pause_each_step else (lambda *args: None)

    # Experiment and output file names
    exp_name = exp_name_override # or get_synth_drone_exp_name(lens_focal_length_in_mm, FOCUS DISTANCE (missing param input), lens, settings_path=settings_path)  # if we want programmatic we need the original focus distance to be passed in as well
    assert exp_name is not None
    exp_root_folder = os.path.join(root_folder, exp_name)
    os.makedirs(exp_root_folder, exist_ok=True)
    print(f"===== {exp_name} =====")

    if not distortion:
        # print("Determining estimated distortion for lens and parameters...")
        # k1_value = compute_k1(camera_focal_length_in_mm, sensor_resolution_x / sensor_width_mm, min_lens_focal_length, max_lens_focal_length, lens)
        # distortion = [k1_value, 0., 0., 0.]
        # print(f"=====> Estimated distortion: {distortion}")
        # pause("Press enter to continue...")
        assert False  # we need minimum / maximum camera focal length for this, not lens
    ### DEFINING PATHS ###

    kalibr_common_cache_dir = os.path.join(exp_root_folder, KALIBR_COMMON_CACHE)
    calib_folders = []
    eval_folders = []

    trial_indices = [x for x in range(num_trials)]

    for trial_index in trial_indices:
        calib_folders.append(f'{exp_root_folder}/trial_{trial_index}_with_guess/calibration')
        eval_folders.append(f'{exp_root_folder}/trial_{trial_index}_with_guess/evaluation')
    ensure_folders_exist([FLAGS, GROUND_TRUTH, KALIBR_COMMON_CACHE, NO_DISTORTION_DATA, WITH_DISTORTION_DATA, RESULTS, RUN_METADATA], root_dir=exp_root_folder)
    ensure_folders_exist([*calib_folders, *eval_folders])

    # TODO: where is gt_intrinsics_filepath?
    calib_result_filepaths = []
    eval_result_filepaths = []
    for trial_index in trial_indices:
        calib_result_filepaths.append(f'{exp_root_folder}/{RESULTS}/trial_{trial_index}_with_guess_calib_result.json')
        eval_result_filepaths.append(f'{exp_root_folder}/{RESULTS}/trial_{trial_index}_with_guess_eval_result.json')

    image_dimensions_filepath = f'{exp_root_folder}/{IMAGE_DIMS}'

    pause("Directories created. Press enter to continue...")

    if flag_missing(MOVEMENT_GENERATION_COMPLETE, exp_root_folder, skip_if_exists):
        ### Generate synthetic images
        generate_drone_movements(AttributeObj(
            root_folder=root_folder,
            exp_name=exp_name,
            camera_type=camera_type,
            drone_radius=drone_radius,
            focal_length_mm=camera_focal_length_in_mm,
            pinhole_to_obj=pinhole_to_obj_in_m,
            x_density=x_density,
            y_density=y_density,
            num_planes=num_planes,
            depth_variation=depth_variation,
            resolution_percentage=resolution_percentage,
            coord_convention="blender", # don't apply -0.5 transformation until after distortion?
            gps_noise_m=gps_noise_m,
            rtk_noise_cm=rtk_noise_cm,
        ))
        create_flag_file(MOVEMENT_GENERATION_COMPLETE, exp_root_folder)
        print("=====> Done generating drone movements.")
        pause("Press enter to continue...")
    else:
        print("=====> Drone movements already exist; reusing...")

    # check render, distort, and detect flasg
    if flag_missing(RENDERS_COMPLETE, exp_root_folder, skip_if_exists) \
        or flag_missing(DISTORTION_COMPLETE, exp_root_folder, skip_if_exists) \
        or flag_missing(DETECTION_COMPLETE, exp_root_folder, skip_if_exists):
        render_distort_detect(AttributeObj(
            root_folder=root_folder,
            exp_name=exp_name,
            camera_type=camera_type,
            drone_radius=drone_radius,
            led_radius=led_radius,
            focal_length_mm=camera_focal_length_in_mm,
            pinhole_to_obj=pinhole_to_obj_in_m,
            resolution_percentage=resolution_percentage,
            distortion=distortion,
            skip_if_exists=skip_if_exists,
        )) # writes its own flag files
        print("=====> Done rendering & distorting & detecting.")
        pause("Press enter to continue...")
    else:
        print("=====> Rendering & distorting & detecting already done; reusing...")

    # get image dims
    with open(image_dimensions_filepath, 'r') as file:
        obj = json.load(file)
        image_width = int(obj['image_width'])
        image_height = int(obj['image_height'])

        # kalibr_initial_result_filepath = f'{calib_folders[trial]}/{RESULTS_CAM}'
        # kalibr_initial_report_pdf_filepath = f'{calib_folders[trial]}/{REPORT_CAM}'
        # kalibr_initial_log_filepath = f'{calib_folders[trial]}/{KALIBR_CALIB_LOG}'

        # kalibr_result_filepath = f'{eval_folders[trial]}/{RESULTS_CAM}'
        # kalibr_report_pdf_filepath = f'{eval_folders[trial]}/{REPORT_CAM}'
        # kalibr_log_filepath = f'{eval_folders[trial]}/{KALIBR_EVAL_LOG}'

        ### Run Kalibr Calibration
        if flag_missing(CALIB_COMPLETE, exp_root_folder, skip_if_exists):
            print(f'Running Kalibr CALIBRATION for {exp_name} (trials = {num_trials})...')

            # Compute focal length guess
            flg = lens_focal_length_in_mm * 3424 / 28.25

            cmds = []
            log_filepaths = []

            for pid, calib_folder_path in enumerate(calib_folders):
                curr_cmd = [
                    './kalibr_calibrate_with_guess.sh',
                    f'{exp_name}',
                    str(image_width),
                    str(image_height),
                    kalibr_common_cache_dir,
                    Path(KALIBR_DETECTION_COORDS).name,
                    Path(KALIBR_DETECTION_SUCCESSES).name,
                    Path(TARGET_YAML).name,
                    str(calib_folder_path),
                    str(pid),
                    str(flg),
                ]

                cmds.append(curr_cmd)
                log_filepaths.append(f'{calib_folder_path}/{KALIBR_CALIB_LOG}')

            # Determine batch size
            avail_ram = psutil.virtual_memory().available / 1024**3 # in GB
            worker_frames = math.floor(avail_ram / 0.01323456) * 0.98 # to give a buffer
            # 1690 / 32 * (num GB RAM)
            print("Workerframes available:", worker_frames)
            # if we allocate abt 70% memory to these processes (so we don't max out memory; seems like the baseline computer memory usage is around 25%)
            # we have ~1690 worker-frames at our disposal. so we can do floor(1690 / num_frames) at a time, (if memory is the constraint)
            cpu_constrained_num_workers = os.cpu_count() - 3
            mem_constrained_num_workers = math.floor(worker_frames / 24)
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
            none_failed = True
            for i, (calib_folder_path, calib_result_filepath) in enumerate(zip(calib_folders, calib_result_filepaths)):
                try:
                    # NOTE: if it's missing, this won't error anymore, we're just writing `null`
                    calib_result_dict = read_kalibr_result_file(f'{calib_folder_path}/{RESULTS_CAM}')
                    with open(calib_result_filepath, 'w') as file:
                        json.dump(calib_result_dict, file, indent=4)
                except FileNotFoundError as e1:
                    print(f"=====> FileNotFoundError: {e1}\n\t(Kalibr calibration likely failed. Check logs for details.)")
                    none_failed = False
                except KeyError as e2:
                    print(f"=====> KeyError: {e2}. Check logs for details.")
                    none_failed = False

            if none_failed:
                create_flag_file(CALIB_COMPLETE, exp_root_folder)
            print("=====> KALIBR IS DONE. Check for result reports etc.")
            pause("Press enter to continue...")
        else:
            print("=====> Calibration results already exist; reusing...")


        if flag_missing(EVAL_COMPLETE, exp_root_folder, skip_if_exists):
            ### Run Kalibr in evaluate mode

            print(f'Running Kalibr EVALUATION for {exp_name} (trials = {num_trials})...')

            # Determine batch size
            avail_ram = psutil.virtual_memory().available / 1024**3 # in GB
            worker_frames = math.floor(avail_ram / 0.01323456) * 0.98 # to give a buffer
            # 1690 / 32 * (num GB RAM)
            print("Workerframes available:", worker_frames)
            # if we allocate abt 70% memory to these processes (so we don't max out memory; seems like the baseline computer memory usage is around 25%)
            # we have ~1690 worker-frames at our disposal. so we can do floor(1690 / num_frames) at a time, (if memory is the constraint)
            cpu_constrained_num_workers = os.cpu_count() - 3
            mem_constrained_num_workers = math.floor(worker_frames / 24)
            if mem_constrained_num_workers < cpu_constrained_num_workers:
                # make smarter batch sizes, spreading out the work
                batches = math.ceil(num_trials / mem_constrained_num_workers)
                num_workers = math.ceil(num_trials / batches)
                print(f"NOTE: Too many frames to use {cpu_constrained_num_workers} parallel processes. Using {num_workers} instead")
            else:
                num_workers = cpu_constrained_num_workers

            run_kalibr_scripts(
                [
                    ['./kalibr_evaluate.sh', f'{exp_name}', str(focal_length_guess),
                     str(image_width), str(image_height), kalibr_common_cache_dir,
                     Path(KALIBR_DETECTION_COORDS).name, Path(KALIBR_DETECTION_SUCCESSES).name, Path(TARGET_YAML).name,
                     calib_results_dict, eval_folder_path, str(pid)]
                    for pid, (calib_results_dict, eval_folder_path) in enumerate(zip(calib_result_filepaths, eval_folders))
                ],
                [f'{eval_folder_path}/{KALIBR_EVAL_LOG}' for eval_folder_path in eval_folders],
                kill_container_pattern=exp_name,
                verbose=verbose,
                num_workers=num_workers
            )

            # Read and record Kalibr eval results
            for eval_folder_path, eval_result_filepath in zip(eval_folders, eval_result_filepaths):
                eval_result_dict = read_kalibr_result_file(f'{eval_folder_path}/{RESULTS_CAM}')

                with open(eval_result_filepath, 'w') as file:
                    json.dump(eval_result_dict, file, indent=4)

            create_flag_file(EVAL_COMPLETE, exp_root_folder)

        else:
            print("=====> Evaluation results already exist; reusing...")


def run_kalibr_scripts(commands, log_filepaths, kill_container_pattern=None, verbose=False, num_workers=None):
    assert isinstance(commands, list) and all(isinstance(cmd, list) for cmd in commands)
    assert isinstance(log_filepaths, list) and all(isinstance(path, str) for path in log_filepaths)
    assert len(commands) == len(log_filepaths)

    # note: this could be simplified using a mp.Pool but that requires more refactoring
    if num_workers is None:
        num_workers = max(1, (os.cpu_count() or 1) - 2)
    batch_size = max(1, int(num_workers))

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
        "This module is a helper and is not a supported standalone entrypoint. Run run_all_drones.py instead."
    )
