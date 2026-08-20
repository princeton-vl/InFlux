import argparse
import json
import numpy as np
import os
import os.path as osp
import re
import statistics
import sys

if __name__ == "__main__":
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    sys.path.append(os.path.dirname(SCRIPT_DIR))
from common_utils import config, get_exp_settings_by_lens


def select_trial(raw_fx, raw_fy, raw_cx, raw_cy, results_names):
    to_keep = not_outlier(raw_fx) & not_outlier(raw_fy) & not_outlier(raw_cx) & not_outlier(raw_cy)

    raw_fx = raw_fx[to_keep]
    raw_fy = raw_fy[to_keep]
    raw_cx = raw_cx[to_keep]
    raw_cy = raw_cy[to_keep]
    to_keep_original_indices = np.arange(len(to_keep))[to_keep]

    median_fx = statistics.median(raw_fx)
    median_fy = statistics.median(raw_fy)
    median_cx = statistics.median(raw_cx)
    median_cy = statistics.median(raw_cy)

    # Compute percent deviation from each metric's median result
    fx_percent_err = np.fabs(raw_fx - median_fx) / median_fx * 100
    fy_percent_err = np.fabs(raw_fy - median_fy) / median_fy * 100
    cx_percent_err = np.fabs(raw_cx - median_cx) / median_cx * 100
    cy_percent_err = np.fabs(raw_cy - median_cy) / median_cy * 100

    scores = fx_percent_err + fy_percent_err + cx_percent_err + cy_percent_err

    selected_trial = results_names[to_keep_original_indices[np.argmin(scores)]]
    return selected_trial

def not_outlier(data):
    # Ignore nan values for outlier bound computations
    valid_data = data[~np.isnan(data)]

    # Sort the data
    sorted_data = sorted(valid_data)

    assert len(sorted_data) >= 1  # we should have at least one valid trial due to previous checks

    # Calculate Q1 and Q3
    q1 = np.percentile(sorted_data, 25)
    q3 = np.percentile(sorted_data, 75)

    # Calculate IQR
    iqr = q3 - q1

    # Calculate bounds
    lower_bound = q1 - 1.5 * iqr
    upper_bound = q3 + 1.5 * iqr

    # Filter out the outliers
    outlier_flags = [(x >= lower_bound and x <= upper_bound) for x in data]

    return np.array(outlier_flags) & ~np.isnan(data)

# gather all of the trial data needed to make a selection using our selection algorithm
def gather_all_trial_data(results_dir, results_names, pause=False):
    raw_fx = []
    raw_fy = []
    raw_cx = []
    raw_cy = []

    for results_name in results_names:
        print(f"  Reading {results_dir}/{results_name}", flush=True)
        with open(f'{results_dir}/{results_name}', 'r') as file:
            result_json = json.load(file)
        if(result_json == None):
            raw_fx.append(np.nan)
            raw_fy.append(np.nan)
            raw_cx.append(np.nan)
            raw_cy.append(np.nan)
        else:
            raw_fx.append(result_json['fx'])
            raw_fy.append(result_json['fy'])
            raw_cx.append(result_json['cx'])
            raw_cy.append(result_json['cy'])

    raw_fx = np.array(raw_fx)
    raw_fy = np.array(raw_fy)
    raw_cx = np.array(raw_cx)
    raw_cy = np.array(raw_cy)

    return raw_fx, raw_fy, raw_cx, raw_cy


def select_trials_over_experiment(lens, exp_folders_root, empirical_mode, output_filepath, synth_selection=None, threshold=-1, threshold_cx_target=1712., threshold_cy_target=1101.):
    target_lfls, target_focus_distances, target_exp_details = get_exp_settings_by_lens(lens, empirical_mode)

    ret = {
        'zooms': target_lfls.tolist(),
        'focus_distances': target_focus_distances.tolist(),
        'exp_details': {}
    }

    ### Get actual experiment folder
    # Lambda to filter out bad experiments
    # TODO: do we actually need this anymore?
    descr_to_filter = ['REFILMED', 'moved', 'BAD', '.DS_Store']
    def should_keep_experiment(x):
        for descr in descr_to_filter:
            if descr in x:
                return False
        return True

    # gets all valid experiment names from the folder
    exp_names = [exp_name for exp_name in os.listdir(exp_folders_root) if should_keep_experiment(exp_name)]

    # get the experiment name
    def get_exp_name(exp_key):
        for exp_name in exp_names:
            if exp_key in exp_name:
                return exp_name
        return None

    # Iterate over ever single experiment
    for exp_key in target_exp_details:
        # Default return experiment detail
        target_info = target_exp_details[exp_key]
        curr_exp_details = {
            'target_metadata': target_info,
            'selected_trial': 'invalid',
            'zoom': -1,
            'focus_distance': -1,
            'board_size': -1,
            'fx': -1,
            'fy': -1,
            'cx': -1,
            'cy': -1,
            'k1': -1,
            'k2': -1,
            'p1': -1,
            'p2': -1,
            'initialization': {
                'fx': -1,
                'fy': -1,
                'cx': -1,
                'cy': -1,
                'k1': -1,
                'k2': -1,
                'p1': -1,
                'p2': -1
            }
        }

        if not empirical_mode:
            # Add additional keys to 'target_metadata' corresponding to ground truth data
            curr_exp_details['gt_data'] = {
                'fx': -1,
                'fy': -1,
                'cx': -1,
                'cy': -1,
                'k1': -1,
                'k2': -1,
                'p1': -1,
                'p2': -1,
            }

        # Find the experiment that corresponds to this key
        exp_name = get_exp_name(exp_key)
        if exp_name is not None:
            curr_exp_details['zoom'] = target_info['zoom']
            curr_exp_details['board_size'] = target_info['board_size']

            curr_exp_path = osp.join(exp_folders_root, exp_name)

            try:
                if empirical_mode:
                    # Check that target metadata matches up
                    with open(f'{osp.join(curr_exp_path, "run_metadata", "target_parameters.json")}', 'r') as file:
                        target_params = json.load(file)
                        assert(target_params["focal_length"] == target_info["zoom"])
                        assert(target_params["focus_distance"] == target_info["focus_distance"])
                        assert(target_params["board_size"] == target_info["board_size"])

                    # Grab actual metadata to fill in focus_distance
                    with open(f'{osp.join(curr_exp_path, "run_metadata", "actual_parameters.json")}', 'r') as file:
                        actual_params = json.load(file)

                    curr_exp_details['focus_distance'] = actual_params["focus_distance"]
                else:
                    # Grab ground truth intrinsics and store
                    with open(f'{osp.join(curr_exp_path, "ground_truth", "gt_intrinsics.json")}', 'r') as file:
                        gt_data = json.load(file)
                    curr_exp_details["gt_data"] = gt_data

                    # Copy target metadata's focus_distance
                    curr_exp_details["focus_distance"] = target_info["focus_distance"]

                # select the trial that works well
                def valid_result(result_name, is_real, synth_selection = None):
                    if is_real and "trial" in result_name and "result" in result_name:
                        return True
                    if not is_real:
                        # Only use eval files
                        if 'eval' not in result_name:
                            return False

                        # Check for one of four settings
                        is_guess = 'guess' in result_name
                        is_old = 'old' in result_name

                        if synth_selection == 'old_guess':
                            return is_old and is_guess
                        elif synth_selection == 'old_normal':
                            return is_old and not is_guess
                        elif synth_selection == 'new_guess':
                            return not is_old and is_guess
                        elif synth_selection == 'new_normal':
                            return not is_old and not is_guess
                    return False

                results_dir = osp.join(curr_exp_path, "results")
                if empirical_mode:
                    results_names = [result_name for result_name in os.listdir(results_dir) if valid_result(result_name, empirical_mode)]
                else:
                    assert(synth_selection != None)
                    results_names = [result_name for result_name in os.listdir(results_dir) if valid_result(result_name, empirical_mode, synth_selection=synth_selection)]

                raw_fx, raw_fy, raw_cx, raw_cy = gather_all_trial_data(results_dir, results_names)

                # If no valid results found, skip filling in data
                if np.isnan(raw_fx).all():
                    # Just add what we have and skip; no valid results
                    ret['exp_details'][exp_key] = curr_exp_details
                    continue

                # Select a trial and get its data
                selected_trial_name = select_trial(raw_fx, raw_fy, raw_cx, raw_cy, results_names)

                with open(f'{osp.join(curr_exp_path, "results", selected_trial_name)}', 'r') as file:
                    selected_trial_data = json.load(file)

                curr_exp_details['selected_trial'] = selected_trial_name.split("_")[1]
                curr_exp_details['fx'] = selected_trial_data['fx']
                curr_exp_details['fy'] = selected_trial_data['fy']
                curr_exp_details['cx'] = selected_trial_data['cx']
                curr_exp_details['cy'] = selected_trial_data['cy']
                curr_exp_details['k1'] = selected_trial_data['k1']
                curr_exp_details['k2'] = selected_trial_data['k2']
                curr_exp_details['p1'] = selected_trial_data['p1']
                curr_exp_details['p2'] = selected_trial_data['p2']

                # Get initialization info
                if empirical_mode:
                    log_path = osp.join(curr_exp_path, "trial_0", "calibration", "kalibr_calib_log.txt")
                else:
                    log_path = osp.join(curr_exp_path, "trial_0_with_guess", "calibration", "kalibr_calib_log.txt")

                # Regular expression to match the projection and distortion values
                proj_pattern = re.compile(r"\s*Projection initialized to:\s*\[([\d.\s\-e]+)\]")
                dist_pattern = re.compile(r"\s*Distortion initialized to:\s*\[([\d.\s\-e]+)\]")

                projection_values, distortion_values = None, None

                with open(log_path, 'r') as file:
                    for line in file:
                        if projection_values is None:
                            proj_match = proj_pattern.search(line)
                            if proj_match:
                                projection_values = list(map(float, proj_match.group(1).split()))

                        if distortion_values is None:
                            dist_match = dist_pattern.search(line)
                            if dist_match:
                                distortion_values = list(map(float, dist_match.group(1).split()))

                        # Stop searching once we have both values
                        if projection_values and distortion_values:
                            break

                if projection_values and distortion_values:
                    curr_exp_details['initialization']['fx'] = projection_values[0]
                    curr_exp_details['initialization']['fy'] = projection_values[1]
                    curr_exp_details['initialization']['cx'] = projection_values[2] + 0.5  # account for kalibr vs. normal convention
                    curr_exp_details['initialization']['cy'] = projection_values[3] + 0.5  # account for kalibr vs. normal convention
                    curr_exp_details['initialization']['k1'] = distortion_values[0]
                    curr_exp_details['initialization']['k2'] = distortion_values[1]
                    curr_exp_details['initialization']['p1'] = distortion_values[2]
                    curr_exp_details['initialization']['p2'] = distortion_values[3]

                    if threshold != -1:
                        # Override selected trial, if its cx and cy are off by too much
                        selected_cx_error = np.abs(curr_exp_details['cx'] - threshold_cx_target) / threshold_cx_target * 100
                        selected_cy_error = np.abs(curr_exp_details['cy'] - threshold_cy_target) / threshold_cy_target * 100

                        if selected_cx_error > threshold or selected_cy_error > threshold:
                            curr_exp_details['selected_trial'] = 'initialization'
                            curr_exp_details['fx'] = curr_exp_details['initialization']['fx']
                            curr_exp_details['fy'] = curr_exp_details['initialization']['fy']
                            curr_exp_details['cx'] = curr_exp_details['initialization']['cx']
                            curr_exp_details['cy'] = curr_exp_details['initialization']['cy']
                            curr_exp_details['k1'] = curr_exp_details['initialization']['k1']
                            curr_exp_details['k2'] = curr_exp_details['initialization']['k2']
                            curr_exp_details['p1'] = curr_exp_details['initialization']['p1']
                            curr_exp_details['p2'] = curr_exp_details['initialization']['p2']
                else:
                    print("Values not found")
                    assert False
            except Exception as e:
                print(f"Error processing experiment {exp_key} at path {curr_exp_path}: {e}")
                # Just add what we have and skip; no valid results
                ret['exp_details'][exp_key] = curr_exp_details
                continue

        ret['exp_details'][exp_key] = curr_exp_details

    # writes the final dictionary to a json
    with open(output_filepath, 'w') as file:
        json.dump(ret, file, indent=4)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Per lens representative trial selection script")
    parser.add_argument("--lens", type=str, choices=config['lenses'].keys(), required=True)
    parser.add_argument("--real", action="store_true", help="Include to specify real trial")
    parser.add_argument("--synth_selection", type=str, choices=['old_guess', 'old_normal', 'new_guess', 'new_normal'], help="Select from {old_guess, old_normal, new_guess, new_normal}")
    parser.add_argument("--threshold", type=float, help="Threshold to apply swap method", default=-1)
    parser.add_argument("--threshold-cx-target", type=float, help="The ideal cx value to compare against when applying threshold", default=1712.)
    parser.add_argument("--threshold-cy-target", type=float, help="The ideal cx value to compare against when applying threshold", default=1101.)
    parser.add_argument("--exp-folders-root", type=str, help="Path to folder containing all experiments to be parsed", required=True)
    parser.add_argument("--output-filepath", type=str, help="Path to .json output file containing all selected experiments and intrinsics", required=True)
    args = parser.parse_args()

    empirical_mode = args.real
    lens = args.lens
    synth_selection = args.synth_selection
    threshold = args.threshold
    threshold_cx_target = args.threshold_cx_target
    threshold_cy_target = args.threshold_cy_target
    exp_folders_root = args.exp_folders_root
    output_filepath = args.output_filepath

    # Call utility function, with all file paths determined
    select_trials_over_experiment(lens, exp_folders_root, empirical_mode, output_filepath, synth_selection=synth_selection, threshold=threshold, threshold_cx_target=threshold_cx_target, threshold_cy_target=threshold_cy_target)
