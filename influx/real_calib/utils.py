import cv2
import json
import os
import subprocess
import sys
import threading
import time


### FOLDERS ###
FLAGS = "flags"
KALIBR_COMMON_CACHE = "kalibr_common_cache"
RAW_DATA = "raw_data"
DETECTION_FRAMES = "detection_frames"
SELECTED_FRAMES = "selected_frames"
RESULTS = "results"
RUN_METADATA = "run_metadata"
RTK_DATA = "drone_rtk"

### FILES ###
TARGET_YAML = f"{KALIBR_COMMON_CACHE}/target.yaml"
COORDS_2D = f"{KALIBR_COMMON_CACHE}/coords_2d.csv"
COORDS_2D_SUCCESSES = f"{KALIBR_COMMON_CACHE}/coords_2d_successes.csv"
COORDS_2D_FULL = f"{RAW_DATA}/coords_2d_full.csv"
COORDS_2D_SUCCESSES_FULL = f"{RAW_DATA}/coords_2d_successes_full.csv"
DETECTIONS_PER_FRAME = f"{RAW_DATA}/detections_per_frame.json"
METADATA_EXPORT = f"{RAW_DATA}/metadata_export.json"
PER_FRAME_METADATA = f"{RAW_DATA}/per_frame_metadata.json"
TARGET_PARAMETERS = f"{RUN_METADATA}/target_parameters.json"
ACTUAL_PARAMETERS = f"{RUN_METADATA}/actual_parameters.json"

RTK_POSITIONS = f"{RTK_DATA}/flash_rtk.json" # 3D positions

TEMP_METADATA = "temp_metadata.json"

# Kalibr filenames
KALIBR_CALIB_LOG = "kalibr_calib_log.txt"
RESULTS_CAM = "calib-results-cam.txt"
REPORT_CAM = "calib-report-cam.pdf"

### FLAGS ###
EXTRACT_META_AND_FRAMES_COMPLETE = f"{FLAGS}/step1_extract_meta_and_frames_complete.txt"
WRITE_PER_FRAME_AND_RUN_METADATA_COMPLETE = f"{FLAGS}/step2_write_per_frame_and_run_metadata_complete.txt"
WRITE_TARGET_COMPLETE = f"{FLAGS}/step3_write_target_complete.txt"
DETECT_CORNERS_COMPLETE = f"{FLAGS}/step4_detect_corners_complete.txt"
SELECT_FRAMES_COMPLETE = f"{FLAGS}/step5_select_frames_complete.txt"
CALIB_COMPLETE = f"{FLAGS}/step6_calib_complete.txt"

### UTIL FUNCTIONS ###

def get_image_size(EXP_FOLDER):
    try:
        with open(f"{EXP_FOLDER}/{METADATA_EXPORT}", "r") as f:
            meta = json.load(f)
        try:
            clipSets = meta["clipBasedMetadataSets"]
            sensorSet = next(filter(lambda s: s["metadataSetName"] == "Sensor State", clipSets))
            rect = sensorSet["metadataSetPayload"]["acquisitionRect"]
            return rect["width"], rect["height"]
        except:
            raise Exception("Unable to find Sensor State metadata")
    except:
        # failed to open metadata export; just get the width of one of the images
        files = os.listdir(f"{EXP_FOLDER}/{RAW_DATA}")
        for f in files:
            path = f"{EXP_FOLDER}/{RAW_DATA}/{f}"
            if os.path.isfile(path) and os.path.splitext(path)[1].lower() in [".tiff", ".png", ".jpg", ".jpeg"]:
                img = cv2.imread(path)
                return img.shape[1], img.shape[0]
        raise Exception("Unable to get size of images")

def rewrite_coords_files(exp_folder, idx_set):
    # remove lines from coords_2d and re-index
    with open(f"{exp_folder}/{COORDS_2D_FULL}", "r") as f:
        coords_2d_lines = f.readlines()
    with open(f"{exp_folder}/{COORDS_2D_SUCCESSES_FULL}", "r") as f:
        coords_2d_successes_lines = f.readlines()

    mask = [False] * len(coords_2d_lines)
    for i, line in enumerate(coords_2d_lines):
        should_include = int(line.split(",")[0]) in idx_set
        mask[i] = should_include

    coords_2d_lines = [l for i, l in enumerate(coords_2d_lines) if mask[i]]
    coords_2d_successes_lines = [l for i, l in enumerate(coords_2d_successes_lines) if mask[i]]

    with open(f"{exp_folder}/{COORDS_2D}", "w") as f:
        f.writelines(coords_2d_lines)
    with open(f"{exp_folder}/{COORDS_2D_SUCCESSES}", "w") as f:
        f.writelines(coords_2d_successes_lines)

def reader_thread(pipe, lines, lock):
    for line in iter(pipe.readline, ''):
        with lock:
            lines.append(line)
    pipe.close()

def kill_containers_matching_pattern(exp_name):
    def cleanup_fn():
        subprocess.run(f"docker container ls -q --filter name={exp_name} | xargs docker container rm -f", shell=True)
        print(f"KILLED DOCKER CONTAINERS MATCHING {exp_name}", flush=True)
    return cleanup_fn

def run_bash_commands(commands, log_filepaths, verbose=False, batch_size=os.cpu_count() - 3, cleanup_on_error_fn=None):
    assert len(commands) == len(log_filepaths)

    # Start all processes and store them in a list
    all_succeeded = True
    for i in range(0, len(commands), batch_size):
        batch_commands = commands[i:i+batch_size]
        batch_log_filepaths = log_filepaths[i:i+batch_size]
        print(f"Starting batch of processes (({i+1} - {i+len(batch_commands)}) / {len(commands)})...")
        processes = []

        for cmd in batch_commands:
            try:
                proc = run_bash_command(cmd, verbose=verbose, blocking=False, print_command=False)
                processes.append(proc)
            except (OSError, subprocess.SubprocessError) as e:
                print(f"Failed to start process {cmd}: {e}")
                with open(batch_log_filepaths[commands.index(cmd)], "w") as file:
                    file.write(f"PROCESS START ERROR:\n{e}\n")
                return False
                # continue  # Skip to next command

        for proc, log_filepath in zip(processes, batch_log_filepaths):
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
                if cleanup_on_error_fn:
                    cleanup_on_error_fn()
                if isinstance(e, KeyboardInterrupt):
                    print("KeyboardInterrupt received. Exiting...")
                    sys.exit(1)
                all_succeeded = False

    print("All processes completed. All succeeded =", all_succeeded)
    return all_succeeded

def run_bash_command(command, verbose=False, blocking=True, cleanup_on_error_fn=None, print_command=True):
    '''
    Creates a Popen object. Pipes both stdout and stderr to PIPE for streaming/reading.
    If `blocking` is True (default), which means this function will block until the subprocess is complete.
    Returns the success of the process

    If `blocking` is False, this function will return after starting the process. Returns the popen object.

    If `cleanup_on_error_fn` is provided, will run after exception occurs (no arguments, so construct it as a closure if it needs context)
    '''
    if print_command:
        print("COMMAND:", command)
    # Run the Bash command
    try:
        popen = subprocess.Popen(
            command,
            text=True,                  # Return output as a string (not bytes)
            stdout=subprocess.PIPE,     # Capture stdout and stderr
            stderr=subprocess.PIPE,     # Capture stdout and stderr
            shell=True,                 # Execute through the shell
            universal_newlines=True
        )

        if not blocking:
            assert cleanup_on_error_fn is None, "cleanup_on_error_fn is not supported when blocking is False"
            # let user handle the object
            return popen

        if verbose:
            list_lock = threading.Lock()
            lines = []
            t = threading.Thread(target=reader_thread, args=(popen.stdout, lines, list_lock))
            t.start() # thread handles closing the pipe at end

            while True:
                with list_lock:
                    if len(lines):
                        print("".join(lines), end="")
                        lines.clear()
                if popen.poll() is not None and len(lines) == 0:
                    break
                time.sleep(1)

        return_code = popen.wait()
        # write any remaining output
        if verbose and len(lines):
            print("".join(lines), end="")
            lines.clear()

        if verbose:
            print("STDERR:")
            print(popen.stderr.read())
            popen.stderr.close()
        if return_code:
            return False
        return True
    except:
        if cleanup_on_error_fn:
            cleanup_on_error_fn()
        return False
