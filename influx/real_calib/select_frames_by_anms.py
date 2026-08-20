import argparse
import json
import matplotlib.animation as anim
import matplotlib.pyplot as plt
import multiprocessing as mp
import numpy as np
import os
import shutil
import sys

from kneed import KneeLocator
from tqdm import tqdm


def anms(detections, c_robust=1.0, min_supp_r=None):
    '''
    Run adaptive non-maximal suppression on the full sequence of frames.
    Return a list of indices of selected frames to add to the ROS bag.

    c_robust same as c_robust from ANMS paper (<= 1)
    '''

    frame_idxs = np.array(sorted([idx for idx in detections.keys()]))
    dets = np.array([detections[idx]['detections_frac'] for idx in frame_idxs])
    # dets[i] = detection fraction (0-1) of frame frame_idxs[i]

    # remove from consideration any frame that has too low detections
    min_dets_mask = dets > 0
    frame_idxs, dets = frame_idxs[min_dets_mask], dets[min_dets_mask]

    # r_ij[i,j] = diff between frame idxs
    aj, ai = np.meshgrid(frame_idxs, frame_idxs)
    r_ij = np.abs(ai - aj).astype(float)

    # det_ratio[i,j] = det[i] / det[j]
    aj, ai = np.meshgrid(dets, dets)
    det_ratio = ai / aj

    # j should suppress i if: det[i] < c_robust * det[j].
    # thus, it should be included in the min_j calculation (j will suppress i by making i's radius smaller.)
    # prevent suppression if opposite condition is true by setting to inf (won't be the min)
    doesnt_suppress_mask = det_ratio >= c_robust
    r_ij[doesnt_suppress_mask] = np.inf

    r_i = np.min(r_ij, axis=-1)
    print("r_i:")
    print(r_i)
    # note: if r_i[i] = np.inf, that means its not suppressed by anything else. i.e. dets[i] = 1.0

    if not min_supp_r:
        max_r = 40 # TODO how to not hardcode this
        # get num_pts for each r
        rs = np.arange(0, max_r)
        # y axis: for each r, find how many pts are >= r
        num_pts = np.zeros(rs.shape)
        for j, r in enumerate(rs):
            num_pts[j] = r_i[r_i >= r].shape[0]

        kneedle = KneeLocator(rs, num_pts, curve="convex", direction="decreasing")
        elbow_r = kneedle.knee

        print(f"Chose elbow r = {elbow_r}")

        min_supp_r = elbow_r

    return sorted(frame_idxs[r_i >= min_supp_r]), {"r_i": r_i, "frame_idxs": frame_idxs, "min_supp_r": min_supp_r}

def plot_frames_vs_r(ax, r_i, max_r=40, r=None):
    always_there = (r_i == np.inf).sum()
    rs = np.arange(0, max_r)
    # y axis: for each r, find how many pts are >= r
    num_pts = np.zeros(rs.shape)
    for j, r_ in enumerate(rs):
        num_pts[j] = r_i[r_i >= r_].shape[0]

    ax.plot([0, max_r], [always_there, always_there], '--', color='gray')
    ax.plot(rs, num_pts)
    vert_bar = ax.plot([rs[0], rs[0]], [0, len(r_i)], '--', color='red')
    if r:
        vert_bar[0].set_xdata([r, r])

    # ax.set_ylim(0, 600)
    ax.set_xlabel("Min suppression radius\n")
    ax.set_ylabel("# points selected")
    ax.set_title(f"# points above min supp radius")


    return vert_bar, rs


def plot_selected_frames_lines(ax, detections, selected_indices):
    # fig, ax = plt.subplots()
    ax.plot(sorted([int(x) for x in detections.keys()]), [detections[idx]['num_detections'] for idx in sorted(detections.keys())], zorder=1, color="blue")
    ax.scatter(sorted([int(x) for x in detections.keys()]), [detections[idx]['num_detections'] for idx in sorted(detections.keys())], s=3, zorder=2, color="blue")

    selected_scat = ax.scatter(selected_indices, [detections[idx]['num_detections'] for idx in selected_indices], s=12, zorder=3, color="red")

    ax.set_xlabel("Frame")
    ax.set_ylabel("# detections")
    ax.set_title("Selected frames")

    return selected_scat


def select_and_copy_frames(old_image_folder, new_image_folder, detections_json, *, c_robust, min_supp_r=None, n_workers=os.cpu_count()-1, exclude_consecutive=True, plot=False):

    assert os.path.isdir(old_image_folder)

    print(f'Converting {old_image_folder} to Kalibr ROS bag folder format at {new_image_folder}...')

    # delete and recreate NEW_IMAGE_FOLDER so its empty
    shutil.rmtree(new_image_folder, ignore_errors=True)
    os.makedirs(new_image_folder, exist_ok=True)

    # Figure out number of writer workers to use

    # get selected indices
    with open(detections_json, "r") as f:
        obj = json.load(f)
        detections = {int(k): v for k, v in obj.items()}

    selected_indices, extra_data = anms(detections, c_robust=c_robust, min_supp_r=min_supp_r)
    n_images = len(selected_indices)
    print(f"Selected indices ({n_images}): {selected_indices}")

    if exclude_consecutive:
        # for any consecutive indices w same number detections, only keep the middle one
        i, j = 0, 0
        while i < len(selected_indices):
            while j < len(selected_indices) and selected_indices[j] == selected_indices[i] + (j - i) and detections[selected_indices[i]]['num_detections'] == detections[selected_indices[j]]['num_detections']:
                j += 1
            if j - i >= 3:
                # remove all but the middle one
                selected_indices = selected_indices[:i] + [selected_indices[(i + j) // 2]] + selected_indices[j:]
            i += 1
            j = i
        print("Num after removing consecutive: ", len(selected_indices))

    # PLOT 1 : elbow
    fig, axs = plt.subplots(1, 2, figsize=(16, 5), gridspec_kw={"width_ratios": [0.3, 0.7]})
    # Plot 1: curve
    plot_frames_vs_r(axs[0], extra_data["r_i"], r=extra_data["min_supp_r"])

    # PLOT 2: x: frame_idx, y: num_detections
    plot_selected_frames_lines(axs[1], detections, selected_indices)
    axs[1].set_title('ANMS. c_robust={},min_supp_r={}, sel={}/{}'.format(c_robust, extra_data["min_supp_r"], len(selected_indices), len(detections)))

    # save fig
    fig.savefig(os.path.join(new_image_folder, 'anms_selected_frames.png'), dpi=300)

    if plot:
        plt.show()
        sys.exit(0)

    pool = mp.Pool(processes=n_workers)
    results = []
    pbar = tqdm(total=n_images)

    def update(_):
        pbar.update()

    image_paths = [f for f in os.listdir(old_image_folder) if os.path.isfile(os.path.join(old_image_folder, f))]
    image_paths = sorted([f for f in image_paths if os.path.splitext(f)[1].lower() in ['.bmp', '.png', '.jpg', '.jpeg', '.tiff', '.tif']])
    for idx in selected_indices:
        old_filename = image_paths[idx]

        # Spoof a nanosecond-based filename
        spoofed_seconds = int(old_filename.split('.')[0])
        file_extension = os.path.splitext(old_filename)[1]

        spoofed_nanoseconds = int(spoofed_seconds * 1e9)
        new_filename = str(spoofed_nanoseconds) + '.' + file_extension

        old_path = os.path.join(old_image_folder, old_filename)
        new_path = os.path.join(new_image_folder, new_filename)

        res = pool.apply_async(copy_file, (old_path, new_path), callback=update)
        results.append(res)

    for r in results:
        r.wait()

    return selected_indices

def copy_file(old_path, new_path):
    # symlink has to be relative, so it doesn't break when docker mounts the dir
    relpath = os.path.relpath(old_path, os.path.dirname(new_path))
    os.symlink(relpath, new_path)
    # convert to png is too slow
    # with Image.open(old_path) as img:
    #     # Resize the image
    #     # Save as PNG
    #     img.save(new_path, format="PNG")

def generate_anim(args, c_robust=1.0):
    # get selected indices
    with open(args.detections_json, "r") as f:
        obj = json.load(f)
        detections = {int(k): v for k, v in obj.items()}

    max_r = 40
    selected_indices, extra_data = anms(detections, c_robust=c_robust, min_supp_r=1)
    frame_idxs = extra_data["frame_idxs"]
    r_i = extra_data["r_i"]

    fig, axs = plt.subplots(1, 2, figsize=(16, 5), gridspec_kw={"width_ratios": [0.3, 0.7]})

    # Plot 1: curve
    vert_bar, rs = plot_frames_vs_r(axs[0], extra_data["r_i"])

    # Plot 2: lines (selected frames)
    selected_scat = plot_selected_frames_lines(axs[1], detections, selected_indices)

    plt.tight_layout()

    def update(i): # i
        axs[0].set_title(f"(r={rs[i]})")
        vert_bar[0].set_xdata([rs[i], rs[i]])

        selected_indices = sorted(frame_idxs[r_i >= rs[i]])
        selected_dets = [detections[idx]['num_detections'] for idx in selected_indices]
        dat = np.vstack([selected_indices, selected_dets]).T
        axs[1].set_title(f'c_robust={c_robust},r={rs[i]}, sel={len(selected_indices)}/{len(detections)}')
        selected_scat.set_offsets(dat)


    ani = anim.FuncAnimation(fig=fig, func=update, frames=max_r, interval=8)
    plt.show()
    ani.save(f"anim_min_r_c={c_robust}.mp4", fps=8)

def generate_graphs(args):
    # get selected indices
    with open(args.detections_json, "r") as f:
        obj = json.load(f)
        detections = {int(k): v for k, v in obj.items()}

    cs = [0.85, 0.875, 0.9, 0.925, 0.9375, 0.95, 0.9625, 0.975, 0.9875, 1.0]
    fig, axs = plt.subplots(2, len(cs) // 2, figsize=(18, 12))
    for i, c_robust in enumerate(cs):
        # TODO could use plot_frames_vs_r helper here
        selected_indices, extra_data = anms(detections, c_robust=c_robust, min_supp_r=1)
        r_i = extra_data["r_i"]
        always_there = (r_i == np.inf).sum()
        # biggest = np.max(r_i[r_i != np.inf])
        rs = np.arange(0, 40)
        num_pts = np.zeros(rs.shape)
        for j, r in enumerate(rs):
            # find how many pts are >= r
            num_pts[j] = r_i[r_i >= r].shape[0]

        axs[i // 5, i % 5].plot([np.min(rs), np.max(rs)], [always_there, always_there], '--', color='gray')
        axs[i // 5, i % 5].plot(rs, num_pts)
        # axs[i // 5, i % 5].set_ylim(0, 600)
        axs[i // 5, i % 5].set_xlabel("Min suppression radius\n")
        axs[i // 5, i % 5].set_ylabel("# points selected")
        axs[i // 5, i % 5].set_title(f"c={c_robust}")
    plt.suptitle("# points above min supp radius, for varying c_robusts\n")
    plt.tight_layout()
    plt.savefig("min_supp_r_comparisons.png")
    plt.show()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--image_folder', type=str, help="Path to directory of all frames.", required=True)
    parser.add_argument('--new_image_folder', type=str, help="Directory in which to write kalibr-formatted selected frames.", required=True)
    parser.add_argument('--detections_json', type=str, help="Path to detections JSON file", required=True)

    sel_group = parser.add_argument_group("Frame selection criteria")
    sel_group.add_argument('--min_supp_r', type=float, help="Threshold minimum suppression radius for frames to be selected. Lower means more frames will be selected. (Variable number of frames). If not provided, will automatically find best min_supp_r via elbow detection.")

    parser.add_argument('--c_robust', type=float, default=1, help="Max ratio for a point to be considered suppressed by another frame. (See ANMS paper for details)")
    parser.add_argument('--n_writer_procs', type=int, default=os.cpu_count() - 1, help="Number of writer processes to spawn. Default is max CPUs - 1")
    parser.add_argument('--include_consecutive', action="store_true", help="Include strings of consecutive & identical frames. Default is to exclude all but one")
    parser.add_argument('--plot', action="store_true", help="Plot selected frames")
    args = parser.parse_args()

    # generate_graphs(args)
    # generate_anim(args, c_robust=1.0)

    assert args.c_robust <= 1 and args.c_robust > 0
    select_and_copy_frames(
        args.image_folder,
        args.new_image_folder,
        args.detections_json,
        c_robust=args.c_robust,
        min_supp_r=args.min_supp_r,
        n_workers=args.n_writer_procs,
        exclude_consecutive=not args.include_consecutive,
        plot=args.plot
    )
