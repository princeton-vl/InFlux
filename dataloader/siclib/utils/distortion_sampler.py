from collections.abc import Mapping

import numpy as np
from scipy.stats import truncnorm

CORNER_MAX_DELTA = 80
CORNER_MIN_DELTA = -50

FACTOR_MAX = 0.5
FACTOR_MIN = -0.10

TOPMID_MAX_DELTA = CORNER_MAX_DELTA * FACTOR_MAX
TOPMID_MIN_DELTA = CORNER_MIN_DELTA * FACTOR_MAX

SENSOR_WIDTH = 0.032 # 32mm
SENSOR_HEIGHT = 0.018 # 18mm


def _get_section(profile, key):
    value = profile.get(key, {})
    if not isinstance(value, Mapping):
        raise TypeError(f"distortion.{key} must be a mapping")
    return value


def sample_distortion_coefs(H, W, LFL, FD, profile=None):
    """
    Generates plausible radial and tangential distortion coefficients by sampling displacement at
    two control points: corner and top_middle (delta_corner, delta_topmid) based on the image's
    Camera Focal Length (CFL) and calculates the appropriate (k1, k2) values to create such displacement.

    Small tangential coefs (p1, p2) are independently sampled from a gaussian after (k1, k2) has been determined.

    Args:
        H (int): Image height in pixels.
        W (int): Image width in pixels.
        LFL (float): Lens Focal Length of image.
        FD (float): Focus Distance of image.
        profile (Mapping, optional): Distortion sampling configuration. The
            ``influx_pp`` profile exposes the original sampler values. The
            ``none`` profile returns zero coefficients and ignores all numeric
            settings in the mapping.

    Returns:
        np.ndarray: [k1, k2, p1, p2] where k are radial and p are tangential
                    distortion coefficients (OpenCV/Brown-Conrady model).
    """
    if profile is None:
        profile = {}
    if not isinstance(profile, Mapping):
        raise TypeError("distortion profile must be a mapping")

    profile_name = profile.get("profile", "influx_pp")
    if profile_name == "none":
        return np.zeros(4, dtype=np.float64)
    if profile_name != "influx_pp":
        raise ValueError(
            f"Unknown distortion profile {profile_name!r}; expected "
            "'influx_pp' or 'none'"
        )

    sensor = _get_section(profile, "sensor")
    corner = _get_section(profile, "corner_displacement")
    factor_conf = _get_section(profile, "top_mid_factor")
    top_mid = _get_section(profile, "top_mid_displacement")
    tangential = _get_section(profile, "tangential")

    sensor_width = float(sensor.get("width_m", SENSOR_WIDTH))
    sensor_height = float(sensor.get("height_m", SENSOR_HEIGHT))
    if sensor_width <= 0 or sensor_height <= 0:
        raise ValueError("sensor width and height must be positive")

    CFL = (1/LFL - 1/FD)**-1
    if (CFL <= 0):
        raise ValueError(f"CFL calculated to be nonpositive. {CFL=:.2f}")
    fx = W / sensor_width * CFL
    fy = H / sensor_height * CFL
    f_avg = (fx + fy) / 2.0

    # 1. Sample corner displacement (in pixels) using a truncated Gaussian.
    # The mean displacement scales linearly with focal length to maintain
    # visual consistency across different zoom levels.
    mean_points = corner.get(
        "mean_by_focal_px",
        [[1500.0, 20.0], [30000.0, 80.0]],
    )
    if len(mean_points) != 2 or any(len(point) != 2 for point in mean_points):
        raise ValueError(
            "distortion.corner_displacement.mean_by_focal_px must contain "
            "exactly two [focal_px, mean_displacement_px] points"
        )
    (f0, d0), (f1, d1) = mean_points
    f0, d0, f1, d1 = map(float, (f0, d0, f1, d1))
    if f0 == f1:
        raise ValueError("mean_by_focal_px focal values must differ")
    m = (d1 - d0) / (f1 - f0)
    b = d0 - (m * f0)
    mean_displ = m * f_avg + b

    corner_min_delta = float(corner.get("min_px", CORNER_MIN_DELTA))
    corner_max_delta = float(corner.get("max_px", CORNER_MAX_DELTA))
    std_displ = float(corner.get("std_px", 50))
    if corner_min_delta > corner_max_delta:
        raise ValueError("corner displacement min_px cannot exceed max_px")
    if std_displ <= 0:
        raise ValueError("corner displacement std_px must be positive")

    # Define bounds for truncated normal distribution
    a_dist = (corner_min_delta - mean_displ) / std_displ
    b_dist = (corner_max_delta - mean_displ) / std_displ
    delta_corner = truncnorm.rvs(a_dist, b_dist, loc=mean_displ, scale=std_displ)

    # 2. Sample the relationship factor between corner and top-mid displacement.
    # This factor determines if the distortion is purely barrel/pincushion, or "mustache".
    factor_min = float(factor_conf.get("min", FACTOR_MIN))
    factor_max = float(factor_conf.get("max", FACTOR_MAX))
    std_factor = float(factor_conf.get("std", 0.15))
    mean_factor = float(factor_conf.get("mean", 1/7))
    if factor_min > factor_max:
        raise ValueError("top-mid factor min cannot exceed max")
    if std_factor <= 0:
        raise ValueError("top-mid factor std must be positive")
    a_fact = (factor_min - mean_factor) / std_factor
    b_fact = (factor_max - mean_factor) / std_factor
    factor = truncnorm.rvs(a_fact, b_fact, loc=mean_factor, scale=std_factor)

    # 3. Calculate dependent displacement at the top-middle edge
    topmid_min_delta = float(top_mid.get("min_px", TOPMID_MIN_DELTA))
    topmid_max_delta = float(top_mid.get("max_px", TOPMID_MAX_DELTA))
    if topmid_min_delta > topmid_max_delta:
        raise ValueError("top-middle displacement min_px cannot exceed max_px")
    delta_topmid = np.clip(delta_corner * factor, topmid_min_delta, topmid_max_delta)

    # 4. Solve for k1, k2 and sample small random values for tangential distortion (p1, p2)
    k1, k2 = solve_for_k1k2(delta_corner, delta_topmid, H, W, fx, fy)
    tangential_std = float(tangential.get("std", 0.0001))
    if tangential_std < 0:
        raise ValueError("tangential std cannot be negative")
    p1, p2 = np.random.normal(0, tangential_std, 2)

    return np.array([k1, k2, p1, p2])


def solve_for_k1k2(delta_corner, delta_topmid, H, W, fx, fy):
    """
    Solves a system of linear equations to find radial distortion coefficients.

    Given the desired pixel displacements at the corner and the top-middle
    of the image, this function finds k1 and k2 in the radial distortion model:
    Δr = k1*r^3 + k2*r^5

    Args:
        delta_corner (float): Desired pixel shift at the image corner.
        delta_topmid (float): Desired pixel shift at the top-middle edge.
        H, W (int): Image dimensions.
        fx, fy (float): Focal lengths.

    Returns:
        tuple: (k1, k2) coefficients.
    """
    f = (fx + fy) / 2

    # Compute normalized radial coordinates (r) for the two control points
    # r = distance_from_center / focal_length
    r_mid = (H / 2) / f
    r_corner = np.sqrt((H/2)**2 + (W/2)**2) / f

    # Set up the linear system Ax = b
    # x = [k1, k2]^T
    # b = [delta_corner, delta_topmid]^T
    A = np.array([
        [f * r_corner**3, f * r_corner**5],
        [f * r_mid**3,    f * r_mid**5]
    ])

    b = np.array([delta_corner, delta_topmid])

    # Solve for [k1, k2]
    k1, k2 = np.linalg.solve(A, b)

    return k1, k2


def main():
    # Example Setup
    H = 2202
    W = 3424

    # Run the system
    lfl = 0.036 #m
    fd = 2 #m
    dist_coefs = sample_distortion_coefs(H, W, lfl, fd)

    print(f"--- Results ---")
    print(f"Sampled k1: {dist_coefs[0]:.6e}")
    print(f"Sampled k2: {dist_coefs[1]:.6e}")

    print(f"Distortion Coefficients: {dist_coefs[:]}")


if __name__ == "__main__":
    main()
