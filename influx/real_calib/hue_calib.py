import cv2
import imageio
import matplotlib.pyplot as plt
import numpy as np
import os

from tqdm import tqdm

# HSV thresholds for red, not used when multiple thresholds are considered.
red_lb = np.array([0, 100, 120])
red_ub = np.array([50, 255, 255])

magenta_lb = np.array([130, 100, 120])
magenta_ub = np.array([180, 255, 255])

# detection thresholds
min_bright_bbox_size = 10
min_bbox_size = 8
max_bbox_size = 1000 # when it glitches, its a big line

# cv2 text utils
font = cv2.FONT_HERSHEY_SIMPLEX
org = (00, 185)
fontScale = 1
font_color = (0, 255, 0)
thickness = 2


# ============================================================================================ Per Frame ============================================================================================ #

def color_channel_viz(img_bgr, path):
    """
    Draws a histogram of some color channel in an image.

    Args:
        img_bgr (np.array): BGR format image to count hues from.
        path (str): Filepath to save histogram to.
    """

    img_hls = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HLS)
    light_distr = img_hls[:, :, 1].flatten()

    fig = plt.hist(light_distr, [i for i in range(180)])
    plt.title("Lightness Distribution")
    plt.xlabel("Lightness Value")
    plt.ylabel("Frequency")
    plt.savefig(path) # why is this erroring


def get_red_mask(img_bgr):
    """
    Gets a mask for reddish values in an image. Not used when multiple thresholds are considered.
averaged_center.png
    Args:
        img_bgr (np.array): BGR format image to mask.

    Returns:
        mask (np.array): Binary mask where white pixels are reddish.
    """
    img_hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)

    mask1 = cv2.inRange(img_hsv, red_lb, red_ub)
    mask2 = cv2.inRange(img_hsv, magenta_lb, magenta_ub)

    mask = mask1 + mask2

    return mask

def get_bright_white_mask(img_bgr):
    """
    Gets a mask for very white values in an image. Not used when multiple thresholds are considered.
averaged_center.png
    Args:
        img_bgr (np.array): BGR format image to mask.

    Returns:
        mask (np.array): Binary mask where white pixels are whitish.
    """
    img_hls = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HLS)
    mask = img_hls[:,:,1] > 210
    mask = (mask * 255).astype(np.uint8)

    return mask


def get_white_mask(img_bgr):
    """
    Gets a mask for whitish values in an image. Not used when multiple thresholds are considered.
averaged_center.png
    Args:
        img_bgr (np.array): BGR format image to mask.

    Returns:
        mask (np.array): Binary mask where white pixels are whitish.
    """
    img_hls = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HLS)
    mask = img_hls[:,:,1] > 150
    mask = (mask * 255).astype(np.uint8)

    return mask


def contour_ellipse(img_bgr, mask, mode, output_path):
    """
    Gets ellipse around maximal contour surrounding a singular masked region.

    Args:
        img_bgr (np.array): BGR format image.
        mask (np.array): Binary mask.

    Returns:
        cont_mask (np.array): Image of the maximal contour on a black background.
        ellipse_img (np.array): Input image with maximal ellipse drawn in green.
        center (np.array): Center (u, v) of maximal ellipse. Not integers.
        all_ellipses_img (np.array): Input image with all ellipses drawn in green.
    """
    contours, _ = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

    # contour = max(contours, key=len)
    cont_masks = []
    centers = []
    ellipse_imgs = []
    all_ellipses_img = img_bgr.copy()

    if len(contours) == 0:
        return cont_masks, centers, ellipse_imgs, None, None

    max_vals = None # (channel we wanna maximize, major/minor ratio)
    max_idx = None

    counter = 0
    for contour in contours:
        if len(contour) >= 5:
            cont_mask = cv2.drawContours(np.zeros_like(img_bgr), [contour], 0, (0, 255, 0), 3)

            ellipse = cv2.fitEllipse(contour)

            center, bbox, angle = ellipse

            major = max(ellipse[1])
            minor = min(ellipse[1])

            # throw out glitches
            if np.any(np.isnan(np.array([*center, *bbox, angle]))) or minor == 0:
                # print("Rejecting bc nan", ellipse)
                continue

            ratio = major/minor

            # extra restrictions for using bright
            if mode == 'bright':
                if major < min_bright_bbox_size or minor < min_bright_bbox_size:
                    # print("Rejecting bc of size (more strict for bright)", bbox)
                    continue
                if ratio >= 1.5:
                    print("Rejecting bright bc too ellipsoid", bbox)
                    continue
            else:
                if major < min_bbox_size or minor < min_bbox_size:
                    # print("Rejecting bc of size", bbox)
                    continue

            if mode in ['white', 'bright']:
                # require that there is some red around the detection
                ymin = max(0, int(center[1] - major))
                ymax = int(center[1] + major)
                xmin = max(0, int(center[0] - major))
                xmax = int(center[0] + major)
                cropped = img_bgr[ymin:ymax, xmin:xmax, :]
                # if cropped.size == 0

                red_mask_cropped = get_red_mask(cropped) # Testing, should be white
                cv2.imwrite(f'{output_path}/cropped.png', cropped)
                cv2.imwrite(f'{output_path}/red_mask_cropped.png', red_mask_cropped)
                if (x := ((red_mask_cropped > 0).sum() / red_mask_cropped.size)) < 0.25:
                    print(f"rejecting bc not enough red nearby ({x})")
                    continue

            if major > max_bbox_size or minor > max_bbox_size:
                print("Line glitch, rejecting", bbox)
                continue

            # if major / minor >= 1 and major / minor <= 2:
            if True:
                center = np.array(center)[::-1]
                ellipse_img = cv2.ellipse(img_bgr.copy(), ellipse, (0, 255, 0), 2)
                all_ellipses_img = cv2.ellipse(all_ellipses_img, ellipse, (0, 255, 0), 2)

                ellipse_mask = np.zeros(img_bgr.shape[:2], dtype=np.uint8)
                cv2.ellipse(ellipse_mask, ellipse, 255, thickness=-1)
                img_hls = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HLS)
                mean_hls = cv2.mean(img_hls, mask=ellipse_mask)[:3]

                if mode in ['white', 'bright']:
                    # get the contour with highest mean lightness. if (approx) tie, use the more round one
                    if max_vals is None or mean_hls[1] > max_vals[0]:
                        max_vals = (mean_hls[1], ratio)
                        max_idx = counter
                elif mode == 'red':
                    # get the contour with highest mean saturation. if (approx) tie, use the more round one
                    if max_vals is None or mean_hls[2] > max_vals[0]:
                        max_vals = (mean_hls[2], ratio)
                        max_idx = counter
                    if mean_hls[2] > 0.9 * max_vals[0] and ratio < max_vals[1]:
                        print('using more round')
                        max_vals = (mean_hls[2], ratio)
                        max_idx = counter

                cont_masks.append(cont_mask)
                centers.append(center)
                ellipse_imgs.append(ellipse_img)

                counter += 1

    return cont_masks, ellipse_imgs, centers, max_idx, all_ellipses_img


def hue_calib(*, src, frames_dest, overwrite, start_idx=0):


    img_paths = sorted([file for file in os.listdir(src) if ".tiff" in file])
    frame_idxs = np.arange(start_idx, len(img_paths))

    writer = None
    if frames_dest:
        os.makedirs(frames_dest, exist_ok=True)
        writer = imageio.get_writer(os.path.join(frames_dest, "output_video.mp4"), fps=15, codec="libx264", pixelformat="yuv420p")

    def write_img(img, img_path):
        writer.append_data(img[:,:,::-1])
        cv2.imwrite(os.path.join(frames_dest, img_path), img)

    def get_best_ellipse_center(centers, max_idx, ellipse_imgs, label, frame, return_image, img_override=None):
        if len(centers) == 0:
            return None, None
        center = np.array(centers[max_idx])

        new_img = None
        if return_image:
            # draw on the image
            new_img = img_override if img_override is not None else ellipse_imgs[max_idx]
            c = center.astype(int)
            new_img[c[0] - 1 : c[0] + 1, c[1] - 1 : c[1] + 1] = np.array([0, 255, 0])

            new_img = cv2.putText(new_img, f"[{frame}]: {center} - {label}", org, font, fontScale,
                    font_color, thickness, cv2.LINE_AA, False)

        return center, new_img

    # debugging by drawing a mask as bw img
    def to3chan(img):
        return np.repeat(img[:,:,None], 3, axis=-1)

    img_paths = np.array(img_paths)
    # last_center = None
    centers = np.zeros((len(frame_idxs), 3)) # first col is the frame idx
    # centers[:, 0] = frame_idxs # prepare the first col
    center_successes = np.zeros((len(frame_idxs), 2))
    # center_successes[:, 0] = frame_idxs
    for frame_idx, img_path in tqdm(zip(frame_idxs, img_paths[frame_idxs])):
        if not overwrite and os.path.exists(os.path.join(frames_dest, img_path)):
            continue

        print(f"[{frame_idx}]")

        img = cv2.imread(os.path.join(src, img_path))

        bright_mask = get_bright_white_mask(img)
        white_mask = get_white_mask(img)
        red_mask = get_red_mask(img)

        return_image = frames_dest is not None
        found_center = False

        for _ in range(1): # dumb way to allow breaking early
            # Brightest white
            _, bright_ellipse_imgs, bright_centers, bright_max_idx, bright_ellipses_img = contour_ellipse(img, bright_mask, mode='bright', output_path=frames_dest)
            center, new_img = get_best_ellipse_center(bright_centers, bright_max_idx, bright_ellipse_imgs, 'brightest white', frame_idx, return_image)
            if center is not None:
                found_center = True
                break

            # White
            _, white_ellipse_imgs, white_centers, white_max_idx, white_ellipses_img = contour_ellipse(img, white_mask, mode='white', output_path=frames_dest)
            center, new_img = get_best_ellipse_center(white_centers, white_max_idx, white_ellipse_imgs, 'white', frame_idx, return_image)
            # new_img, center = attempt_centers(white_centers, white_max_idx, white_ellipse_imgs, 'white', img_override=to3chan(white_mask))
            # new_img, center = attempt_centers(white_centers, white_max_idx, white_ellipse_imgs, 'white', img_override=white_ellipses_img)
            if center is not None:
                found_center = True
                break

            # Red
            _, red_ellipse_imgs, red_centers, red_max_idx, red_ellipses_img = contour_ellipse(img, red_mask, mode='red', output_path=frames_dest)
            center, new_img = get_best_ellipse_center(red_centers, red_max_idx, red_ellipse_imgs, 'red', frame_idx, return_image)
            # new_img, center = attempt_centers(red_centers, red_max_idx, red_ellipse_imgs, 'red', img_override=to3chan(red_mask))
            # new_img, center = attempt_centers(red_centers, red_max_idx, red_ellipse_imgs, 'red', img_override=red_ellipses_img)
            if center is not None:
                found_center = True
                break

        if found_center:
            centers[frame_idx, 1:] = center
            center_successes[frame_idx, 1] = 1
        else:
            new_img = img
            print(f"[ERROR] COULD NOT FIND DRONE: FRAME {frame_idx}")
            # leave the center as 0, 0, success as 0
        if writer:
            write_img(new_img, img_path)

        # failed to find a center
        # or just drop the frame
        # if last_center is not None:
        #     last_center_img = img.copy()
        #     last_center_img[last_center[0] - 1 : last_center[0] + 1, last_center[1] - 1 : last_center[1] + 1] = np.array([0, 255, 0])
        #     write_img(last_center_img, img_path)
        #     print(f"[ERROR] COULD NOT FIND ELLIPSE: FRAME {i} - using last good center {last_center}")
        # else:
            # write_img(to3chan(red_mask), img_path) # troublehsooting
            # write_img(red_ellipses_img, img_path)

    if writer:
        writer.close()

    # swap x and y columns
    centers[:, [1,2]] = centers[:, [2,1]]
    return centers, center_successes


if __name__ == "__main__":
    raise SystemExit(
        "This module is a helper and is not a supported standalone entrypoint. "
        "Run process_video_by_detections.py instead."
    )
