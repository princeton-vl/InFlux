import argparse
import numpy as np
import os
import sys
import traceback

sys.path.append('..')

if __name__ == "__main__":
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    sys.path.append(os.path.dirname(SCRIPT_DIR))

from run_drone_pipeline import run_drone_experiment

from common_utils import config, get_exp_settings_filename, compute_k1, get_thin_lens_conversions, get_camera_info, get_synth_drone_exp_name, get_exp_settings_by_lens, get_param_string_by_zoom_and_focus


def main(args):
    # Read from argparse
    lenses = args.lenses
    hardcoded_settings = args.hardcoded_settings
    camera = args.camera
    drone_radius = args.drone_radius
    led_radius = args.led_radius


    gps_noise_m = args.gps_noise_m
    rtk_noise_cm = args.rtk_noise_cm

    # angle = args.angle
    root_folder_base = args.root_folder
    num_trials = args.num_trials
    settings_paths = args.settings_paths or [None] * len(lenses)

    assert lenses is not None
    assert len(settings_paths) == len(lenses), "If settings paths provided, must be same length as lenses"

    failures = []

    # Parse lenses for information
    for lens, settings_path in zip(lenses, settings_paths):
        root_folder = f"{root_folder_base}/{lens}"
        # Compute extremal camera focal lengths that are hit
        zooms, distances, all_exp_details = get_exp_settings_by_lens(lens, empirical_mode=False, settings_path=settings_path)
        _, min_camera_focal_length_in_mm, _, _ = get_thin_lens_conversions(float(zooms.min()), float(distances.max()))
        _, max_camera_focal_length_in_mm, _, _ = get_thin_lens_conversions(float(zooms.max()), float(distances.min()))

        # Get experiment settings: (lens_focal_length, focus_distance)
        print("===== EXPERIMENT SETTINGS =====")
        if not hardcoded_settings:
            # get this from the experiment file instead
            experiment_params = np.array(np.meshgrid(zooms, distances)).T.reshape(-1, 2)
            print("Settings from experiment file: ", experiment_params)
            # include all the experiments with board_size == "drone"
            board_sizes = [all_exp_details[get_param_string_by_zoom_and_focus(zoom, dist, lens, empirical_mode=False, settings_path=settings_path)]["board_size"] for zoom, dist in experiment_params]
            experiment_params = experiment_params[np.array(board_sizes) == "drone"]
        else:
            experiment_params = np.array(hardcoded_settings).reshape(-1, 2)
            print("Hardcoded settings: ", experiment_params)

        # Get camera sensor info
        sensor_width_mm, _, sensor_resolution_x, _, resolution_percentage = get_camera_info(camera)
        pixels_per_mm = sensor_resolution_x / sensor_width_mm

        count = 0
        for coord in experiment_params:  # lens focal length, focal distance
            count += 1

            # This will be LENS focal length, and [camera focal length + pinhole_to_object]
            lens_focal_length_in_mm, focus_distance_in_mm = coord

            # Compute camera focal length, and pinhole_to_obj_in_m from thin lens
            _, camera_focal_length_in_mm, _, pinhole_to_obj_in_mm = get_thin_lens_conversions(lens_focal_length_in_mm, focus_distance_in_mm)

            k1_value = compute_k1(camera_focal_length_in_mm, pixels_per_mm, min_camera_focal_length_in_mm, max_camera_focal_length_in_mm, lens)
            distortion = [k1_value, 0., 0., 0.]
            focus_distance_in_m = focus_distance_in_mm / 1000
            pinhole_to_obj_in_m = pinhole_to_obj_in_mm / 1000

            noise_levels = [0]

            for noise_level in noise_levels:
                # Invoke single board
                try:
                    exp_name = get_synth_drone_exp_name(lens_focal_length_in_mm, focus_distance_in_m, lens, settings_path=settings_path)
                    print(f"===== RUNNING EXPERIMENT: {exp_name} =====")
                    run_drone_experiment(
                        drone_radius=drone_radius,
                        led_radius=led_radius,
                        lens_focal_length_in_mm=lens_focal_length_in_mm,
                        camera_focal_length_in_mm=camera_focal_length_in_mm,
                        pinhole_to_obj_in_m=pinhole_to_obj_in_m,
                        resolution_percentage=resolution_percentage,
                        camera_type=camera,
                        lens=lens,
                        root_folder=root_folder,
                        settings_path=settings_path,
                        distortion=distortion,
                        exp_name_override=exp_name,
                        num_trials=num_trials,
                        skip_if_exists=True,
                        verbose=True,
                        gps_noise_m=gps_noise_m,
                        rtk_noise_cm=rtk_noise_cm,
                    )

                except Exception as e:
                    exp_name = get_synth_drone_exp_name(lens_focal_length_in_mm, focus_distance_in_m, lens, settings_path=settings_path)
                    print(f"===== EXPERIMENT {exp_name} FAILED ===== ")
                    traceback.print_exc()
                    print("Args:", lens, coord, f"distortion={distortion}")
                    failures.append((exp_name, lens, coord, distortion))
            print(f'{count} / {len(experiment_params)} Kalibr completed')


        if len(failures):
            print(f"==== FAILED EXPERIMENTS ({len(failures)}) ====")
            print("(name, lens, coords, distortion)")
            for fail in failures:
                print(fail[0]) # just exp name


if __name__ == "__main__":
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--root-folder", type=str, default=f'{config["LENS_SETTINGS_DIR_SYNTH"]}/synthetic')
    parser.add_argument("--drone-radius", type=float, help="Radius of drone target, in meters", default=0.02)
    parser.add_argument("--led-radius", type=float, help="Radius of drone target, in meters", default=0.02)
    parser.add_argument("--gps-noise-m", type=float, help="GPS, in meters", default=0.0)
    parser.add_argument("--rtk-noise-cm", type=float, help="RTK jitter, in cm", default=1.0)

    parser.add_argument("--camera", type=str, default='arri', help="Type of camera to model")
    parser.add_argument("--lenses", type=str, default=['canon17', 'premista80'], nargs='+', help="Type of lens to model")

    parser.add_argument("--hardcoded-settings", type=float, nargs='+',help="List of floats. [<focal length 1>, <focus distance 1>, <focal length 2>, <focus distance 2>, ...]. Must have an even length. If not provided, settings will be fetched from the experiment file.")
    parser.add_argument("--settings-paths", type=str, nargs='+', default=[get_exp_settings_filename('canon17', empirical_mode=False), get_exp_settings_filename('premista80', empirical_mode=False)], help="Paths to custom settings file for each lens. If not provided, settings will be taken from .../autocalib/{lens}.json")

    parser.add_argument("--num-trials", type=int, default=1)

    args = parser.parse_args()

    assert (args.hardcoded_settings is None) or len(args.hardcoded_settings) % 2 == 0

    main(args)
