'''
Utilities common across all pipelines
'''
import json
import math
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import os
import pandas as pd
import re
import seaborn as sns
import yaml


# Import config of default paths to use for pipeline process
script_dir = os.path.dirname(os.path.abspath(__file__))
with open(f"{script_dir}/config.yaml", "r") as f:
    config = yaml.safe_load(f)


### OS UTILS
def ensure_folders_exist(folder_paths, root_dir=None):
    if type(folder_paths) == list:
        for folder in folder_paths:
            dir = os.path.join(root_dir, folder) if root_dir else folder
            os.makedirs(dir, exist_ok=True)
    else:
        folder_paths = os.path.join(root_dir, folder_paths) if root_dir else folder_paths
        os.makedirs(folder_paths, exist_ok=True)

def create_flag_file(flag_name, flags_dir="", data: str=None):
    if flags_dir:
        os.makedirs(flags_dir, exist_ok=True)
    with open(os.path.join(flags_dir, flag_name), 'w') as file:
        file.write(data or 'completed')

def read_flag_file(flag_name, flags_dir=""):
    with open(os.path.join(flags_dir, flag_name), 'r') as file:
        data = file.read()
    return data

def flag_missing(flag_name, flags_dir, skip_if_exists=True):
    '''Returns true if flag doesn't exist, or if skip_if exists is false (meaning always run)'''
    return not (os.path.isfile(os.path.join(flags_dir, flag_name)) and skip_if_exists)

### GETTING EXPERIMENT NAMES
def get_param_string(focal_length_idx, focus_distance_idx):
    return f'zoom_{focal_length_idx}_focus_distance_{focus_distance_idx}'

def get_real_exp_name(focal_length_mm, focus_distance_m, lens, settings_path=None):
    zoom_idx, focus_idx = get_idxs_snapping_to_settings(focal_length_mm, focus_distance_m, lens, True, settings_path=settings_path)
    return f'real_exp_{get_param_string(zoom_idx, focus_idx)}_{lens}'

def get_synth_board_exp_name(focal_length_mm, focus_distance_m, lens, settings_path=None):
    zoom_idx, focus_idx = get_idxs_snapping_to_settings(focal_length_mm, focus_distance_m, lens, False, settings_path=settings_path)
    return f'synth_board_{get_param_string(zoom_idx, focus_idx)}_{lens}'

def get_synth_drone_exp_name(focal_length_mm, focus_distance_m, lens, settings_path=None):
    zoom_idx, focus_idx = get_idxs_snapping_to_settings(focal_length_mm, focus_distance_m, lens, False, settings_path=settings_path)
    return f'synth_drone_{get_param_string(zoom_idx, focus_idx)}_{lens}'


### GETTING EXPERIMENT SETTINGS
### EXPERIMENT NAME <----> EXPERIMENT SETTINGS <----> SETTINGS INDICES
def get_exp_settings_filename(lens, empirical_mode, settings_path=None):
    if not settings_path:
        settings_dir = config['LENS_SETTINGS_DIR'] if empirical_mode else config['LENS_SETTINGS_DIR_SYNTH']
        suffix = '_synth' if not empirical_mode else ''
        settings_path = f"{settings_dir}/{lens}{suffix}.json"

    return settings_path

def get_exp_settings_by_lens(lens, empirical_mode, settings_path=None):
    '''
    Returns all experiment settings for the specified lens and empirical mode option. If settings_path is provided, it overrides the settings location retrieved.
    '''
    path = get_exp_settings_filename(lens, empirical_mode, settings_path=settings_path)

    with open(path, "r") as f:
        obj = json.load(f)
        focal_lengths_mm = np.array(obj["zooms"])
        focus_distances_mm = np.array(obj["focus_distances"])
        exp_details = obj["exp_details"]

    return focal_lengths_mm.astype(np.float64), focus_distances_mm.astype(np.float64), exp_details

def get_settings_by_exp_name(exp_name, settings_path=None):
    '''
    Get experiment settings for the specific experiment name specified.
    NOTE: this assumes that real appears in real experiment names, and synth appears in synthetic experiment names!
    '''
    param_string = re.search(r'(zoom_\d+_focus_distance_\d+)', exp_name).group(1)
    lens = re.search(r'focus_distance_\d+_([^_]+)', exp_name).group(1)
    empirical_mode = 'real' in exp_name

    _, _, all_exp_details = get_exp_settings_by_lens(lens, empirical_mode, settings_path=settings_path)
    try:
        exp_details = all_exp_details[param_string]
        return exp_details["zoom"], exp_details["focus_distance"], exp_details["board_size"], lens
    except KeyError:
        raise Exception(f"No exp_details entry for {param_string}. This should not happen.")

def get_idxs_by_exp_name(exp_name):
    zoom_idx, focus_idx = map(int, re.search(r'zoom_(\d+)_focus_distance_(\d+)', exp_name).groups())
    return zoom_idx, focus_idx

def get_idxs_snapping_to_settings(focal_length_mm, focus_distance_m, lens, empirical_mode, settings_path=None, verbose=False):
    # find settings that these are closest to those in the lens metadata file
    # NOTE: we are correctly using focus_distance here, not pinhole_to_obj
    # NOTE: indices should match regardless of empirical mode; only thing that changes is board size
    focus_distance_mm = focus_distance_m * 1000
    focal_lengths_mm, focus_distances_mm, _ = get_exp_settings_by_lens(lens, empirical_mode, settings_path=settings_path)
    focal_length_idx = np.argmin(np.abs(focal_lengths_mm - focal_length_mm))
    focus_distance_idx = np.argmin(np.abs(focus_distances_mm - focus_distance_mm))
    if verbose:
        print("Snapping settings:")
        print(f"\t{focal_length_mm}mm --> {focal_lengths_mm[focal_length_idx]}mm")
        print(f"\t{focus_distance_mm}mm --> {focus_distances_mm[focus_distance_idx]}mm")
    return focal_length_idx, focus_distance_idx

def get_param_string_by_zoom_and_focus(focal_length_mm, focus_distance_mm, lens, empirical_mode, settings_path=None):
    zoom_idx, focus_idx = get_idxs_snapping_to_settings(focal_length_mm, focus_distance_mm / 1000, lens, empirical_mode, settings_path=settings_path)
    return get_param_string(zoom_idx, focus_idx)


### RETRIEVING LENSES, CAMERAS, AND DISTORTION INFO
def get_lens_info(lens):
    assert lens in config['lenses'].keys()
    min_lens_focal_length = config['lenses'][lens]['min_lens_focal_length']
    max_lens_focal_length = config['lenses'][lens]['max_lens_focal_length']
    min_focus_distance = config['lenses'][lens]['min_focus_distance']
    lens_name = config['lenses'][lens]['lens_name']

    return min_lens_focal_length, max_lens_focal_length, min_focus_distance, lens_name

def get_camera_info(camera):
    assert camera in config['cameras'].keys()
    sensor_width_mm = config['cameras'][camera]['sensor_width_mm']
    sensor_height_mm = config['cameras'][camera]['sensor_height_mm']
    sensor_resolution_x = config['cameras'][camera]['sensor_resolution_x']
    sensor_resolution_y = config['cameras'][camera]['sensor_resolution_y']
    resolution_percentage = config['cameras'][camera]['resolution_percentage']

    return sensor_width_mm, sensor_height_mm, sensor_resolution_x, sensor_resolution_y, resolution_percentage

def compute_k1(focal_length_mm, pixels_per_mm, min_lens_focal_length, max_lens_focal_length, lens):
    '''Returns a k1 value so that visual interpolation seems smooth, with respect to chosen min_k1'''
    # Technically we need pixels_per_mm to do this, but the scale factors cancel out
    # so we omit for precision preservation
    # Compute focal lengths in pixelst

    # Determine k1 value to use
    min_k1 = config['lenses'][lens]['min_k1']

    min_lens_focal_length_in_pixels = min_lens_focal_length #* pixels_per_mm
    focal_length_in_pixels = focal_length_mm #* pixels_per_mm

    # Compute constant corresponding to distortion pixel offset scale
    min_visual_factor = min_k1 / (min_lens_focal_length_in_pixels ** 2)
    max_visual_factor = -min_visual_factor

    focal_length_frac = (focal_length_mm - min_lens_focal_length) / (max_lens_focal_length - min_lens_focal_length)
    target_visual_factor = (1 - focal_length_frac) * min_visual_factor + focal_length_frac * max_visual_factor

    k1 = focal_length_in_pixels ** 2 * target_visual_factor
    return k1

### BOARD SIZE ASSIGNMENTS AND SAMPLING SETTINGS
def get_board_assignments(expanded_lens_focal_lengths, expanded_focus_distances, lens_focal_lengths, focus_distances, lens, camera, max_board_size=6.4, empirical_mode=True):
    # assumes expanded_lens_focal_lengths and expanded_focus_distances are flattened & in same order
    # and lens_focal_lengths and focus_distances are in increasing order

    # Determine board assignments
    sensor_width_mm, sensor_height_mm, _, _, resolution_percentage = get_camera_info(camera)

    # NOTE: we assign boards based on camera_focal_length. We estimate these with thin lens equation
    _, camera_focal_lengths, _, pinhole_to_objs = get_thin_lens_conversions(expanded_lens_focal_lengths, expanded_focus_distances)

    fov_widths = sensor_width_mm * (pinhole_to_objs / camera_focal_lengths)
    fov_heights = sensor_height_mm * (pinhole_to_objs / camera_focal_lengths)
    obj_dists = pinhole_to_objs

    fov_widths = fov_widths.flatten()
    fov_heights = fov_heights.flatten()
    obj_dists = obj_dists.flatten()

    # Determine which boards cover which FOVs; add largest boards last to maximize board size
    board_sizes = [0.1, 0.2, 0.4, 0.8, 1.6, 3.2, 6.4]
    # truncate the below lists based on if board_sizes are <= max_board_size
    idx = next(filter(lambda x: x[1] > max_board_size, enumerate(board_sizes)), (len(board_sizes), None))[0]
    board_sizes = board_sizes[:idx]
    board_widths = [100, 200, 400, 800, 1600, 3200, 6400][:idx]
    board_heights = [75, 150, 300, 600, 1200, 2400, 4800][:idx]
    board_colors = ['violet', 'red', 'green', 'blue', "#FF7B7B", "#B2FF6AEC", "#60CDFF"][:idx]
    board_color_labels = ['AprilGrid 6 mm', 'AprilGrid 12 mm', 'AprilGrid 24 mm', 'AprilGrid 48 mm', 'AprilGrid 96 mm', 'AprilGrid 192 mm', 'AprilGrid 384 mm'][:idx]

    if lens in ['canon17', 'premista80']:
        # add drone option for large FSF for canon17 and premista80 experiments
        board_colors = [*board_colors, 'turquoise']
        board_color_labels = [*board_color_labels, 'Drone']

    board_colors = [*board_colors, 'grey']
    board_color_labels = [*board_color_labels, 'Skipped']

    colors = np.repeat('              ', len(fov_widths))
    colors[True] = 'grey'

    sizes = np.repeat(0.0, len(fov_widths))

    for bw, bh, bs, bc in zip(board_widths, board_heights, board_sizes, board_colors):
        angle = 45
        width_scale_factor = (1 - (bh / 2 * math.sin(math.radians(angle))) / obj_dists)
        height_scale_factor = (1 - (bw / 2 * math.sin(math.radians(angle))) / obj_dists)

        selected = (bw <= fov_widths * width_scale_factor) & (bh <= fov_heights * height_scale_factor)
        colors[selected] = bc
        sizes[selected] = bs

    # Empirical experiment setting overrides
    hardcodes = []

    # If using drones for large FSF calibration, determine cutoff between boards and drones based on camera height
    if lens in ['canon17', 'premista80']:
        camera_height = 1.44 # m
        cutoff_dists = (2 * camera_height * expanded_lens_focal_lengths / sensor_height_mm) * 1000 # mm
        selected = (sizes == 0.0) & (obj_dists <= cutoff_dists)
        colors[selected] = board_colors[-2]
        sizes[selected] = board_sizes[-2]

        unselected = (obj_dists > cutoff_dists)
        colors[unselected] = board_colors[-1]
        sizes[unselected] = 0.0

        # Designate drone experiments; drone size will be designated as -1, skippd will be 0.0
        hardcodes += [
            ('canon17', 0, 7, -1, 'turquoise'),
            ('canon17', 0, 9, -1, 'turquoise'),
            ('canon17', 2, 9, -1, 'turquoise'),
            ('canon17', 3, 7, -1, 'turquoise'),
            ('canon17', 3, 9, -1, 'turquoise'),
            ('canon17', 4, 9, -1, 'turquoise'),
        ]

        hardcodes += [
            ('premista80', 0, 9, -1, 'turquoise'),
            ('premista80', 2, 9, -1, 'turquoise'),
            ('premista80', 4, 9, -1, 'turquoise'),
        ]

    # Add in any additional overrides to experiment settings
    if empirical_mode:
        hardcodes += [
            ('canon17', 0, 0, 0.8, 'blue'),
            ('canon17', 5, 3, 0.8, 'blue'),
            ('canon17', 7, 4, 0.4, 'green')
        ]

        hardcodes += [
            ('canon17v2', 5, 3, 0.8, 'blue'),
        ]

        hardcodes += [
            ('premista80', 6, 0, 0.2, 'red'),
            ('premista80', 8, 1, 0.2, 'red'),
            ('premista80', 7, 7, 0.8, 'blue'),
            ('premista80', 8, 0, 0.1, 'violet')
        ]

        hardcodes += [
            ('premista80v2', 6, 0, 0.2, 'red'),
            ('premista80v2', 8, 1, 0.2, 'red'),
            ('premista80v2', 7, 7, 0.8, 'blue'),
            ('premista80v2', 8, 0, 0.1, 'violet')
        ]
    else:
        hardcodes += [
            ('premista80', 8, 0, 0.1, 'violet')
        ]

        hardcodes += [
            ('premista80v2', 8, 0, 0.1, 'violet')
        ]

    for hardcode in hardcodes:
        if lens != hardcode[0]:
            continue
        print("Hardcoding: ", hardcode)
        idx = (expanded_lens_focal_lengths == lens_focal_lengths[hardcode[1]]) & (expanded_focus_distances == focus_distances[hardcode[2]])
        sizes[idx] = hardcode[3]
        colors[idx] = hardcode[4]

    return sizes, colors, board_color_labels, board_colors

# Get list of (lens_focal_length, focus_distance) values based on lens and camera
def get_experiment_params(lens, camera, n_focus_distance_samples, soft_min_focus_distance, max_board_size=6.4, verbose=False, empirical_mode=True):
    # Get lens and camera info
    min_lens_focal_length, max_lens_focal_length, lens_min_focus_distance, _ = get_lens_info(lens)
    assert lens_min_focus_distance <= soft_min_focus_distance

    # Sample exponentially for focal length
    lens_focal_lengths = [min_lens_focal_length]

    exp_counter = 0
    while True:
        next_fl = int(lens_focal_lengths[-1] + 2 ** exp_counter)
        exp_counter += 1
        if next_fl < max_lens_focal_length:
            lens_focal_lengths.append(next_fl)
        else:
            break

    lens_focal_lengths.append(max_lens_focal_length)

    # Sample linearly in 1/D for focus distances
    inv_min_focus_distance = 1 / soft_min_focus_distance
    inv_max_focus_distance = 0

    inv_focus_distances = np.linspace(inv_min_focus_distance, inv_max_focus_distance, n_focus_distance_samples + 1)
    inv_focus_distances = inv_focus_distances[:-1]  # skip infinity

    focus_distances = 1 / inv_focus_distances
    focus_distances = np.array([lens_min_focus_distance, *focus_distances])

    experiment_raw_values = np.array(np.meshgrid(lens_focal_lengths, focus_distances)).T.reshape(-1, 2)  # (lens_focal_length, focus_distance)
    experiment_indices = np.array(np.meshgrid(range(len(lens_focal_lengths)), range(len(focus_distances)))).T.reshape(-1, 2)  # (lens_focal_length, focus_distance)

    expanded_lens_focal_lengths = experiment_raw_values[:, 0]
    expanded_focus_distances = experiment_raw_values[:, 1]

    sizes, colors, board_color_labels, board_colors = get_board_assignments(expanded_lens_focal_lengths, expanded_focus_distances, lens_focal_lengths, focus_distances, lens, camera, max_board_size=max_board_size, empirical_mode=empirical_mode)

    if verbose:
        show_distance_based_plot(experiment_raw_values, colors, lens=lens)
        show_exp_grid(board_colors, board_color_labels, colors, experiment_indices, lens, lens_focal_lengths, focus_distances)

    return lens_focal_lengths, focus_distances, experiment_indices, experiment_raw_values, sizes


### VISUALIZING EXPERIMENT SETTINGS
def show_exp_grid(board_colors, board_color_labels, colors, experiment_indices, lens, lfls_short, fds_short):
    # Get max grid size
    grid_size_x = len(lfls_short)
    grid_size_y = len(fds_short)

    # Create an empty grid with NaN values
    grid = np.full((grid_size_y, grid_size_x), np.nan, dtype=float)  # y first to match heatmap orientation

    # Create a dictionary to map colors to numerical values (order preserved)
    existing_colors = [color for color in board_colors if color in colors]
    color_mapping = {color: i for i, color in enumerate(existing_colors)}

    # Convert colors to mapped values
    mapped_values = [color_mapping[color] for color in colors]

    # Fill the grid with mapped color values
    for (x, y), value in zip(experiment_indices, mapped_values):
        grid[y, x] = value  # Note: Heatmap expects (row, col) so y first

    # Convert grid to a DataFrame
    df_grid = pd.DataFrame(grid)
    df_grid.index = np.round([fd / 1000 for fd in fds_short], 2)
    df_grid.columns = lfls_short

    # Define a color palette
    cmap = sns.color_palette(existing_colors, as_cmap=True)

    # Plot heatmap
    plt.figure(figsize=(6, 6))
    ax = sns.heatmap(df_grid, cmap=cmap, linewidths=0.5, linecolor="black", cbar=False, square=True)

    ax.tick_params(axis='y', labelrotation=0)
    ax.set_xlabel('Lens Focal Lengths (mm)', fontsize=12)
    ax.set_ylabel('Focus Distances (m)', fontsize=12)

    ax.set_title(f'{lens} Calibration Experiments', fontsize=14)

    # Create a custom legend for colors
    handles = [mpatches.Patch(color=color, label=label) for color, label in zip(board_colors, board_color_labels) if color in existing_colors]
    ax.legend(handles=handles, loc='lower center', bbox_to_anchor=(0.5, -0.30), ncol=3, frameon=False)

    # Show the plot
    ax.invert_yaxis()
    plt.tight_layout()
    plt.savefig(f'{lens}_real_experiments.pdf', bbox_inches="tight")

def show_distance_based_plot(experiment_params, colors, lens):
    x = experiment_params[:, 0]
    y = experiment_params[:, 1]

    plt.figure(figsize=(6, 6))
    plt.scatter(x, y / 1000, color=colors, s=20)
    plt.xlabel('Lens Focal Length (mm)')
    plt.ylabel('Focus Distance (m)')
    plt.title(f'{lens} Experiment Settings')

    plt.savefig(f'{lens}_real_experiments_scatter.pdf', bbox_inches="tight")

    # Now make a mono-chrome version (for presentation purposes)
    colors_mono = colors.copy()
    colors_mono[:] = 'grey'

    plt.figure(figsize=(6, 6))
    plt.scatter(x, y / 1000, color=colors_mono, s=20)
    plt.xlabel('Lens Focal Length (mm)')
    plt.ylabel('Focus Distance (m)')
    plt.title(f'{lens} Experiment Settings')

    plt.savefig(f'{lens}_real_experiments_scatter_mono.pdf', bbox_inches="tight")


### PARSING KALIBR RESULTS
def read_kalibr_result_file(filepath):
    if not os.path.isfile(filepath):
        return None

    with open(filepath, 'r') as file:
        kalibr_result = file.read()

    # Regex patterns for distortion and projection
    base_pattern = r"(distortion|projection):\s*\[\s*((?:[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?\s*)+)\]\s*\+\-\s*\[\s*((?:[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?\s*)*)\]"

    # Regex pattern for Avg EPE and Max EPE
    epe_pattern = r"Avg EPE:\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*;\s*Max EPE:\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)"

    # Find all distortion and projection matches
    matches = re.findall(base_pattern, kalibr_result)

    results = {}

    for match in matches:
        key = match[0]  # Either 'distortion' or 'projection'
        values = list(map(float, match[1].split()))  # Convert extracted values to float
        errors = list(map(float, match[2].split())) if match[2] else None

        results[key] = {
            "values": values,
            "errors": errors
        }

    # Find Avg EPE and Max EPE
    epe_match = re.search(epe_pattern, kalibr_result)
    if epe_match:
        results["epe"] = {
            "avg": float(epe_match.group(1)),
            "max": float(epe_match.group(2))
        }

    if 'projection' not in results:
        return None  # no match, this is an error for downstream to handle

    # Format it into a flat json; and also convert from Kalibr conventions to normal conventions (add 0.5 to principle point)
    return {
        'fx': results['projection']['values'][0],
        'fy': results['projection']['values'][1],
        'cx': results['projection']['values'][2] + 0.5,
        'cy': results['projection']['values'][3] + 0.5,
        'k1': results['distortion']['values'][0],
        'k2': results['distortion']['values'][1],
        'p1': results['distortion']['values'][2],
        'p2': results['distortion']['values'][3],
        'fx_uncertainty': results['projection']['errors'][0] if results['projection']['errors'] is not None else None,
        'fy_uncertainty': results['projection']['errors'][1] if results['projection']['errors'] is not None else None,
        'cx_uncertainty': results['projection']['errors'][2] if results['projection']['errors'] is not None else None,
        'cy_uncertainty': results['projection']['errors'][3] if results['projection']['errors'] is not None else None,
        'k1_uncertainty': results['distortion']['errors'][0] if results['distortion']['errors'] is not None else None,
        'k2_uncertainty': results['distortion']['errors'][1] if results['distortion']['errors'] is not None else None,
        'p1_uncertainty': results['distortion']['errors'][2] if results['distortion']['errors'] is not None else None,
        'p2_uncertainty': results['distortion']['errors'][3] if results['distortion']['errors'] is not None else None,
        'avg_epe': results['epe']['avg'],
        'max_epe': results['epe']['max']
    }


### DRONE UTILS
def normalize_drone_coordinates(points_3d):
    # normalize 3d points around origin & within unit sphere. assumes the input has an index column
    points_3d_normalized = np.array(points_3d)
    points_3d_normalized[:, 1:] -= np.mean(points_3d_normalized[:, 1:], axis=0)
    points_3d_normalized[:, 1:] /= np.max(np.linalg.norm(points_3d_normalized[:, 1:], axis=-1))
    return points_3d_normalized


### METADATA UTILS
def create_per_frame_meta_from_metadata_export(metapath, lens_name_suffix):
    obj = {"frames": {}}
    with open(metapath, "r") as f:
        meta = json.load(f)
        obj["descriptiveMetadata"] = {item["metadataSetName"]: item["metadataSetPayload"] | { "schema": item["metadataSetSchemaUri"] } for item in meta["descriptiveMetadataSets"]}
        obj["clipMetadata"] = {item["metadataSetName"]: item["metadataSetPayload"] | { "schema": item["metadataSetSchemaUri"] } for item in meta["clipBasedMetadataSets"]}

        lensModel = obj['descriptiveMetadata']['Lens Device']['lensModel'] # get lens from metadata
        lens = f"{config['metadata_lens_mapping'][lensModel]}{lens_name_suffix}"
        obj["lens"] = lens

        frames = meta["frameBasedMetadata"]["frames"]
        for frame in frames:
            lens_state = frame["frameBasedMetadataSets"]["Lens State"]
            idx = frame["frameId"]  # this has to exist, no exceptions

            # Each frame has a chance for missing metadata due to the pins disconnecting. If required metadata is missing, put NaN instead of values and/or erroring out.
            try:
                focal_length_mm = lens_state["lensFocalLength"] / 1000 # micrometers -> millimeters
            except KeyError:
                focal_length_mm = float('nan')

            # NOTE we are correctly using focus_distance here since its from lens metadata, not pinhole_to_obj
            try:
                focus_distance_m = lens_state["lensFocusDistanceMetric"] / 1000
            except KeyError:
                try:
                    focus_distance_imperial = lens_state["lensFocusDistanceImperial"] # in thousandths of an inch
                    focus_distance_m = focus_distance_imperial * 0.0000254
                except KeyError:
                    focus_distance_m = float('nan')

            obj["frames"][idx] = {
                "focal_length_mm": focal_length_mm,
                "focus_distance_m": focus_distance_m
            }
    return obj


### DEFINITION CONVERSION UTILS
def get_thin_lens_conversions(lens_focal_length_in_mm, focus_distance_in_mm):
    camera_focal_length_in_mm = (
        focus_distance_in_mm - np.sqrt(focus_distance_in_mm ** 2 - 4 * lens_focal_length_in_mm * focus_distance_in_mm)
    ) / 2

    pinhole_to_obj_in_mm = focus_distance_in_mm - camera_focal_length_in_mm

    return lens_focal_length_in_mm, camera_focal_length_in_mm, focus_distance_in_mm, pinhole_to_obj_in_mm
