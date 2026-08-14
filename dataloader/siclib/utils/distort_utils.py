# Source: https://github.com/princeton-vl/calibgen/blob/main/influx/synthetic_boards/distort_utils.py

import cv2
import multiprocessing as mp
import numpy as np
import os

from tqdm import tqdm

def get_distorted_image(intrinsics, distortion, image):
    h, w, _ = image.shape
    dtype = image.dtype

    map_x, map_y = get_distortion_remap(intrinsics, distortion, h, w)

    # Remap the image; note that remap uses map_x and map_y to use (0, 0) as pixel center
    distorted_image = cv2.remap(
        image,
        map_x,
        map_y,
        cv2.INTER_LINEAR,
    )

    return np.astype(distorted_image, dtype)

    # Plot
    # fig, axs = plt.subplots(1, 2, figsize=(10, 5))  # 1 row, 2 columns

    # # Display first image
    # axs[0].imshow(image)
    # axs[0].scatter(x - 0.5, y - 0.5, marker='.')
    # axs[1].imshow(distorted_image)
    # # axs[1].scatter(x_distorted - 0.5, y_distorted - 0.5, marker='.')
    # plt.show()

def get_distorted_coords(intrinsics, distortion, coords):
    # NOTE: this assumes that coordinates and principle point are specified in same convention
    # default convention is 0.5 = center of pixel

    k1, k2, p1, p2 = distortion

    # assumed to be of the form (N, 2)
    x = coords[:, 0]
    y = coords[:, 1]

    # Extract intrinsics values
    fx = intrinsics[0]
    fy = intrinsics[1]
    cx = intrinsics[2]
    cy = intrinsics[3]

    # Normalize coordinates
    x = (x - cx) / fx
    y = (y - cy) / fy

    # Calculate the radial distance from the center
    r2 = x**2 + y**2

    # Calculate the radial distortion
    x_distorted = x * (1 + k1 * r2 + k2 * r2**2)
    y_distorted = y * (1 + k1 * r2 + k2 * r2**2)

    # Calculate the tangential distortion
    x_distorted += 2 * p1 * x * y + p2 * (r2 + 2 * x**2)
    y_distorted += p1 * (r2 + 2 * y**2) + 2 * p2 * x * y

    # Denormalize coordinates
    x_distorted = x_distorted * fx + cx
    y_distorted = y_distorted * fy + cy

    # # Remap the image
    # distorted_image = cv2.remap(image, x_distorted.astype(np.float32), y_distorted.astype(np.float32), cv2.INTER_LINEAR)

    return x_distorted, y_distorted

def get_undistorted_coords(intrinsics, distortion, distorted_coords, max_iter=5):
    # NOTE: this assumes that coordinates and principle point are specified in same convention
    # default convention is 0.5 = center of pixel

    k1, k2, p1, p2 = distortion

    # assumed to be of the form (N, 2)
    x_distorted = distorted_coords[:, 0]
    y_distorted = distorted_coords[:, 1]

    # Extract intrinsics values
    fx = intrinsics[0]
    fy = intrinsics[1]
    cx = intrinsics[2]
    cy = intrinsics[3]

    # Normalize coordinates
    x_distorted = (x_distorted - cx) / fx
    y_distorted = (y_distorted - cy) / fy

    # Initialize guesses for undistorted coordinates
    x, y = x_distorted, y_distorted

    # Iterative solver to undistort coordinates
    for _ in range(max_iter):
        r2 = x**2 + y**2

        delta_x = 2 * p1 * x * y + p2 * (r2 + 2 * x**2)
        delta_y = 2 * p2 * x * y + p1 * (r2 + 2 * y**2)
        radial_factor = 1 + k1 * r2 + k2 * r2 ** 2
        x, y = (x_distorted - delta_x) / radial_factor, (y_distorted - delta_y) / radial_factor

    # Denormalize coordinates
    x = x * fx + cx
    y = y * fy + cy

    return x, y


def get_distortion_remap(intrinsics, distortion, h, w):
    """Build remap coordinates for cv2.remap from distortion parameters.

    Returns:
        map_x, map_y: float32 arrays of shape (h, w), pixel-center corrected.
    """
    k1, k2, p1, p2 = distortion
    dist_coeffs = np.array([k1, k2, p1, p2], dtype=np.float64)
    fx, fy, cx, cy = intrinsics[:4]
    K = np.array([[fx, 0, cx],
                [0, fy, cy],
                [0,  0,  1]], dtype=np.float64)

    # Create a meshgrid for the image coordinates; pixel centers have 0.5 offset
    x_distorted, y_distorted = np.meshgrid(np.arange(w, dtype=np.float64), np.arange(h, dtype=np.float64))
    x_distorted += 0.5 # take center of pixel
    y_distorted += 0.5
    distorted_pts = np.stack([x_distorted.ravel(), y_distorted.ravel()], axis=-1).reshape(-1, 1, 2)

    undistorted_pts = cv2.undistortPoints(distorted_pts, K, dist_coeffs, P=K)

    # Reshape to maps for remap, which uses corner-based coordinates, so we convert from center-based convention
    map_x = undistorted_pts[:, 0, 0].reshape(h, w).astype(np.float32) - 0.5
    map_y = undistorted_pts[:, 0, 1].reshape(h, w).astype(np.float32) - 0.5

    return map_x, map_y

def image_distorter_proc(intrinsics, distortion, writing_queue, completion_queue, pid):
    """Read from the queue; this spawns as a separate Process"""
    while True:
        msg = writing_queue.get()  # Read from the queue and do nothing
        if msg == "DONE":
            completion_queue.put("DONE")
            break
        else:
            original_image_path, distorted_image_path = msg

            img = cv2.imread(original_image_path)
            distorted_img = get_distorted_image(intrinsics, distortion, img)

            cv2.imwrite(distorted_image_path, distorted_img)

            completion_queue.put((pid))

def progress_bar_proc(completion_queue, n_tasks, n_workers):
    done_counter = 0
    with tqdm(total=n_tasks) as pbar:
        while True:
            msg = completion_queue.get()
            if msg == "DONE":
                done_counter += 1

                if done_counter == n_workers:
                    break
            else:
                pbar.update(1)
    return 0


def get_distorted_images_parallel(intrinsics, distortion, original_image_paths, distorted_image_paths, n_workers=os.cpu_count() - 1):
    writing_queues = {pid: mp.Queue() for pid in range(n_workers)}
    completion_queue = mp.Queue()

    worker_dict = {}
    for i in range(n_workers):
        worker_dict[i] = mp.Process(target=image_distorter_proc, args=(intrinsics, distortion, (writing_queues[i]), (completion_queue), i))
        worker_dict[i].daemon = True
        worker_dict[i].start()

    # Instantiate and start progress bar process
    worker_dict[n_workers] = mp.Process(target=progress_bar_proc, args=((completion_queue), len(distorted_image_paths), n_workers))
    worker_dict[n_workers].daemon = True
    worker_dict[n_workers].start()

    # Add tasks to queues
    for idx, msg in enumerate(zip(original_image_paths, distorted_image_paths)):
        writing_queues[idx % n_workers].put(msg)
    for idx in range(n_workers):
        writing_queues[idx].put("DONE")

    # Ensure all VoL workers finish
    for i in range(len(worker_dict.keys())):
        worker_dict[i].join()

    # Close queues
    for queue in writing_queues.values():
        queue.close()
    completion_queue.close()
