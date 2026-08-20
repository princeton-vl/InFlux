import argparse
import json
import os
from common_utils import config, get_exp_settings_filename, get_experiment_params, get_param_string


def make_exp_json(experiment_params, lens_name, output_filepath):
    lens_focal_lengths, focus_distances, experiment_indices, experiment_raw_values, sizes = experiment_params

    exp_dict = {
        'zooms': [float(lfl) for lfl in lens_focal_lengths],
        'focus_distances': [float(fd) for fd in focus_distances],
        'exp_details': {}
    }

    for i in range(experiment_indices.shape[0]):
        exp_zoom_idx = experiment_indices[i][0]
        exp_fd_idx = experiment_indices[i][1]
        exp_name = get_param_string(exp_zoom_idx, exp_fd_idx)

        exp_zoom = experiment_raw_values[i][0]
        exp_fd = experiment_raw_values[i][1]

        exp_size = sizes[i]
        if lens_name in ['canon17', 'premista80']:
            if exp_size == 0 or exp_size == -1:
                exp_size = 'drone'

        exp_dict['exp_details'][exp_name] = {
            'zoom': float(exp_zoom),
            'focus_distance': float(exp_fd),
            'board_size': exp_size
        }

    with open(output_filepath, "w") as json_file:
        json.dump(exp_dict, json_file, indent=4)


def generate_experiment_settings(args):
    camera = args.camera
    lens = args.lens
    empirical_mode = args.empirical_mode

    output_filepath = get_exp_settings_filename(lens, empirical_mode)
    output_dir = output_filepath.rsplit('/', 1)[0]
    assert os.path.exists(output_dir), f"Experiment setting output directory {output_dir} does not exist; please create"

    # Determine lens-based extremal values and samples
    n_focus_distance_samples = config['n_focus_distance_samples']
    max_board_size = config['lenses'][lens]['max_board_size']
    soft_min_focus_distance = config['lenses'][lens]['soft_min_focus_distance']

    experiment_params = get_experiment_params(
        lens,
        camera,
        n_focus_distance_samples,
        soft_min_focus_distance,
        max_board_size=max_board_size,
        verbose=True,
        empirical_mode=empirical_mode
    )
    lens_focal_lengths, focus_distances, experiment_indices, experiment_raw_values, sizes = experiment_params

    print(f'lens focal lengths: {lens_focal_lengths}')
    print(f'focus_distances: {focus_distances}')

    print(f'Writing experiment settings to {output_filepath}')
    make_exp_json(experiment_params, lens, output_filepath)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Determine which experiments to run based on selected lens and whether running in empirical or synthetic mode.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument("--camera", type=str, choices=config['cameras'].keys(), help="Name of camera to generate experiment settings for", default='arri')
    parser.add_argument("--lens", type=str, choices=config['lenses'].keys(), help="Name of lens to generate experiment settings for", required=True)
    parser.add_argument("--empirical-mode", action="store_true", help="If set, will generate experiments for empirical mode; otherwise for synthetic mode")
    args = parser.parse_args()

    generate_experiment_settings(args)
