import argparse
import json
import matplotlib.pyplot as plt
import numpy as np
import os
import seaborn as sns

# Input:
# - --path: selected-trial JSON file
# - --intrinsic: intrinsic parameter to visualize
# - --output_path: destination directory
#
# Output:
# - a generic heatmap of the selected intrinsic values

# Given the intrinsic and selected-trial JSON path, return the trial data from
# each of the selected trial in the json in a grid of focal_length x focus_distance
# ASSUMPTIONS: we assume that the json substitutes missing values with -1 as
#              it should in the select trials script,
#              so there is data for a full grid of experiments
def get_raw_data(path, intrinsic):
    with open(path, 'r') as file:
        data = json.load(file)

    # initialize lists of unique focal lengths, unique focus distance, and their lengths
    n_focal_lengths = len(data['zooms'])
    n_focus_distances = len(data['focus_distances'])

    # initialize things to be returned
    ret_fd_grid = np.zeros(shape=(n_focal_lengths, n_focus_distances))
    ret_fl_grid = np.zeros(shape=(n_focal_lengths, n_focus_distances))
    ret_intrinsic_arr = np.zeros(shape=(n_focal_lengths, n_focus_distances))

    all_exp_details = data["exp_details"]

    # forms grid with focal length on rows and focus distance on columns
    for fl_idx in range(n_focal_lengths):
        for fd_idx in range(n_focus_distances):
            key = "zoom_" + str(fl_idx) + "_focus_distance_" + str(fd_idx)

            # Check if experiment is in the json file
            if all_exp_details.get(key) == None:
                ret_intrinsic_arr[fl_idx][fd_idx] = np.nan
                continue

            # Get actual zoom and focus distance
            ret_fl_grid[fl_idx][fd_idx] = all_exp_details[key]['zoom']
            ret_fd_grid[fl_idx][fd_idx] = all_exp_details[key]['focus_distance']

            # update intrinsics array
            ret_intrinsic_arr[fl_idx][fd_idx] = all_exp_details[key][intrinsic]


    # Replace invalid -1's with np.nan
    invalid_indices = ret_intrinsic_arr == -1
    ret_intrinsic_arr[invalid_indices] = np.nan

    return ret_fl_grid, ret_fd_grid, ret_intrinsic_arr

# given the data, list of unique focus distances, and list of unqiue focal lengths, and whether or not its real, intrinsic selected
# visualize the necessary plots like scatter and heatmap
def visualize(focal_length_grid, focus_distance_grid, intrinsics_data, intrinsic, output_path=None):
    print(output_path, intrinsic)
    os.makedirs(output_path, exist_ok=True)

    CMAP_FOR_VALUES = 'RdYlGn_r'
    cmap = plt.get_cmap(CMAP_FOR_VALUES)

    # Set the "bad color" (NaN values color) to a specific color, e.g., 'red'
    cmap.set_bad('#600')  # You can replace 'red' with any color you want for NaN values

    fig, ax = plt.subplots(1, 1, figsize=(12, 6))

    data = intrinsics_data.copy()
    data = data.T
    na_mask = np.isnan(data)
    data[na_mask] = 99999

    annot = np.char.mod('%.2f', data)
    annot[na_mask] = 'N/A'

    xticklabels = focal_length_grid[:,0].astype(int)
    yticklabels = np.round((focus_distance_grid[0,:] / 1000), 2).astype(float)

    # Plot the selected intrinsic values as a heatmap.
    sns.heatmap(data, ax=ax, cmap=cmap, cbar=False, annot=annot, fmt='',
        xticklabels=xticklabels,
        yticklabels=yticklabels,
    )
    ax.invert_yaxis()
    ax.tick_params(axis='y', rotation=0)
    ax.set_title("Values of " + intrinsic)
    plt.savefig(f'{output_path}/values_{intrinsic}.pdf', bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Visualize selected calibration intrinsic values")
    parser.add_argument("--path", type=str, help="Please provide the file path specifying the location of the json containing the selected trials", required=True)
    parser.add_argument("--intrinsic", type=str, help="Choose from the eight intrinsics: [fx, fy, cx, cy, p1, p2, k1, k2]", required=True)
    parser.add_argument("--output_path", type=str, help="Where to save heatmap", required=True)
    args = parser.parse_args()

    path = args.path
    intrinsic = args.intrinsic
    output_path=args.output_path

    assert args.intrinsic in ['fx', 'fy', 'cx', 'cy', 'p1', 'p2', 'k1', 'k2']



    fl_grid, fd_grid, intrinsic_arr = get_raw_data(path, intrinsic)
    visualize(fl_grid, fd_grid, intrinsic_arr, intrinsic, output_path=output_path)
