import argparse
import numpy as np
import os
import sys

sys.path.append('..')

from common_utils import config, get_thin_lens_conversions, get_camera_info, get_exp_settings_filename, compute_k1, get_synth_board_exp_name, get_exp_settings_by_lens, get_param_string_by_zoom_and_focus

if __name__ == "__main__":
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    sys.path.append(os.path.dirname(SCRIPT_DIR))

from run_board import run_board_experiment


def main(args):
    # Read from argparse
    lenses = args.lenses
    camera = args.camera
    root_folder_base = args.root_folder
    num_trials = args.num_trials
    settings_paths = args.settings_paths or [None] * len(lenses)

    assert lenses is not None
    assert len(settings_paths) == len(lenses), "If settings paths provided, must be same length as lenses"

    # Parse lenses for information
    for lens, settings_path in zip(lenses, settings_paths):
        root_folder = f"{root_folder_base}/{lens}"

        sensor_width_mm, sensor_height_mm, sensor_resolution_x, sensor_resolution_y, resolution_percentage = get_camera_info(camera)
        pixels_per_mm = sensor_resolution_x / sensor_width_mm

        # Get experiment settings: (lens_focal_length, focus_distance), board_sizes
        # from the experiment file instead
        zooms, focus_distances, all_exp_details = get_exp_settings_by_lens(lens, empirical_mode=False, settings_path=settings_path)
        experiment_params = np.array(np.meshgrid(zooms, focus_distances)).T.reshape(-1, 2)
        board_sizes = [all_exp_details[get_param_string_by_zoom_and_focus(zoom, dist, lens, empirical_mode=False, settings_path=settings_path)]["board_size"] for zoom, dist in experiment_params]
        # include all the experiments with board_size != "drone"
        experiment_params = experiment_params[np.array(board_sizes) != "drone"]
        board_sizes = [size for size in board_sizes if size != "drone"]

        # Compute extremal camera focal lengths that are hit
        _, min_camera_focal_length_in_mm, _, _ = get_thin_lens_conversions(float(zooms.min()), float(focus_distances.max()))
        _, max_camera_focal_length_in_mm, _, _ = get_thin_lens_conversions(float(zooms.max()), float(focus_distances.min()))

        count = 0
        for coord, board_size in zip(experiment_params, board_sizes):  # lens focal length, focal distance, board size
            count += 1

            lens_focal_length_in_mm, focus_distance_in_mm = coord  # BTW this will be LENS focal length, and [camera focal length + pinhole_to_object]

            # Compute camera focal length, and pinhole_to_obj_in_m from thin lens
            _, camera_focal_length_in_mm, _, pinhole_to_obj_in_mm = get_thin_lens_conversions(lens_focal_length_in_mm, focus_distance_in_mm)


            k1_value = compute_k1(camera_focal_length_in_mm, pixels_per_mm, min_camera_focal_length_in_mm, max_camera_focal_length_in_mm, lens)
            distortion = [k1_value, 0., 0., 0.]
            focus_distance_in_m = focus_distance_in_mm / 1000
            pinhole_to_obj_in_m = pinhole_to_obj_in_mm / 1000

            noise_levels = [0]

            for noise_level in noise_levels:
                # Experiment naming format
                exp_name = get_synth_board_exp_name(lens_focal_length_in_mm, focus_distance_in_m, lens, settings_path=settings_path)

                # Invoke single board
                print(f"===== RUNNING EXPERIMENT: {exp_name} =====")
                run_board_experiment(
                    board_size,
                    noise_level,
                    lens_focal_length_in_mm,
                    camera_focal_length_in_mm,
                    pinhole_to_obj_in_m,
                    resolution_percentage,
                    camera,
                    lens,
                    root_folder,
                    settings_path,
                    exp_name,
                    distortion,
                    num_trials=num_trials,
                    print_header=f'[{count} / {len(experiment_params)}]',
                    verbose=True
                )
            print(f'{count} / {len(experiment_params)} Kalibr completed')




if __name__ == "__main__":
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--camera", type=str, default='arri', help="Type of camera to model")
    parser.add_argument(
        "--lenses",
        type=str,
        default=["canon17", "premista80", "canon17v2", "premista80v2"],
        nargs="+",
        help="Types of lenses to model",
    )

    parser.add_argument("--root_folder", type=str, default=f'{config["LENS_SETTINGS_DIR_SYNTH"]}/synthetic')
    parser.add_argument(
        "--settings-paths",
        type=str,
        default=[
            get_exp_settings_filename("canon17", empirical_mode=False),
            get_exp_settings_filename("premista80", empirical_mode=False),
            get_exp_settings_filename("canon17v2", empirical_mode=False),
            get_exp_settings_filename("premista80v2", empirical_mode=False),
        ],
        nargs="+",
        help="Settings paths corresponding positionally to --lenses",
    )
    parser.add_argument("--num_trials", type=int, default=100)

    args = parser.parse_args()

    main(args)
