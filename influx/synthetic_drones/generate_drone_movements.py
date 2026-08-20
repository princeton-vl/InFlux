#!/usr/bin/env python

import bpy
import csv
import logging
import math
import matplotlib.patches as patches
import matplotlib.pyplot as plt
import numpy as np
import os
import sys

sys.path.append('..')

from common_utils import normalize_drone_coordinates
from mathutils import Matrix
from utils import ANGLES_CSV, CALIBRATION_MATRIX, DETECTION_COORDS, DETECTION_COORDS_PLOT, DETECTION_SUCCESSES, NUM_ACCEPTED, TARGET_CSV, TARGET_NORM_CSV, TARGET_YAML, GT_3D_CSV


class Suppress:
    def __enter__(self, logfile=os.devnull):
        open(logfile, "w").close()
        self.old = os.dup(1)
        sys.stdout.flush()
        os.close(1)
        os.open(logfile, os.O_WRONLY)
        self.level = logging.root.manager.disable
        logging.disable(logging.CRITICAL)

    def __exit__(self, type, value, traceback):
        os.close(1)
        os.dup(self.old)
        os.close(self.old)
        logging.disable(self.level)

def clear_scene(keep=[], targets=None, materials=True):
    D = bpy.data
    if targets is None:
        targets = get_all_bpy_data_targets()

    if materials:
        targets.append(D.materials)

    for t in targets:
        if t in keep:
            continue
        for o in t:
            if o in keep or o.name in keep:
                continue
            t.remove(o)

    with Suppress():
        bpy.ops.ptcache.free_bake_all()

def get_all_bpy_data_targets():
    D = bpy.data
    return [
        D.objects,
        D.collections,
        D.movieclips,
        D.particles,
        D.meshes,
        D.curves,
        D.armatures,
        D.node_groups,
    ]


def get_calibration_matrix_K_from_blender(camera):
    f_in_mm = camera.data.lens
    scene = bpy.context.scene
    W = resolution_x_in_px = scene.render.resolution_x
    H = resolution_y_in_px = scene.render.resolution_y
    scale = scene.render.resolution_percentage / 100
    sensor_width_mm = camera.data.sensor_width
    sensor_height_mm = camera.data.sensor_height

    pixel_aspect_ratio = scene.render.pixel_aspect_x / scene.render.pixel_aspect_y

    if (camera.data.sensor_fit == 'VERTICAL'):
        # the sensor height is fixed (sensor fit is horizontal),
        # the sensor width is effectively changed with the pixel aspect ratio
        s_u = resolution_x_in_px * scale / sensor_width_mm / pixel_aspect_ratio  # pixels per milimeter
        s_v = resolution_y_in_px * scale / sensor_height_mm
    else: # 'HORIZONTAL' and 'AUTO'
        # the sensor width is fixed (sensor fit is horizontal),
        # the sensor height is effectively changed with the pixel aspect ratio
        pixel_aspect_ratio = scene.render.pixel_aspect_x / scene.render.pixel_aspect_y
        s_u = resolution_x_in_px * scale / sensor_width_mm
        s_v = resolution_y_in_px * scale * pixel_aspect_ratio / sensor_height_mm


    # Parameters of intrinsic calibration matrix K
    alpha_u = f_in_mm * s_u
    alpha_v = f_in_mm * s_v
    u_0 = resolution_x_in_px * scale / 2
    v_0 = resolution_y_in_px * scale / 2
    skew = 0 # only use rectangular pixels

    K = Matrix(
        ((alpha_u, skew,    u_0),
        (    0  , alpha_v, v_0),
        (    0  , 0,        1 )))
    return K

def get_screen_position(scene, camera, obj_location):
    # Get the dependency graph for the current scene
    depsgraph = bpy.context.evaluated_depsgraph_get()

    # Get camera view-projection matrix
    view_matrix = camera.matrix_world.inverted()
    proj_matrix = camera.calc_matrix_camera(
        depsgraph=depsgraph,
        x=scene.render.resolution_x,
        y=scene.render.resolution_y,
        scale_x=scene.render.pixel_aspect_x,
        scale_y=scene.render.pixel_aspect_y
    )
    view_proj_matrix = proj_matrix @ view_matrix

    # Convert world coordinates to normalized device coordinates (NDC)
    coord_4d = view_proj_matrix @ obj_location.to_4d()
    if coord_4d.w == 0.0:
        raise ValueError("Invalid transformation, w=0")

    ndc = coord_4d.xyz / coord_4d.w

    # Map NDC to screen coordinates
    screen_x = (ndc.x + 1) / 2 * scene.render.resolution_x
    screen_y = (1 - ndc.y) / 2 * scene.render.resolution_y  # Flip Y for screen
    return round(screen_x), round(screen_y)

def generate_board_movements(camera, pinhole_to_obj, drone_radius, x_density=5, y_density=4, num_planes=4, depth_variation=0.25, gps_noise_m=0, rtk_noise_cm=0.0):
    scene = bpy.context.scene

    # Compute FOV bounds at chosen focus distance(s)
    f_in_mm = camera.data.lens
    sensor_width_mm = camera.data.sensor_width
    sensor_height_mm = camera.data.sensor_height

    screen_width = scene.render.resolution_x
    screen_height = scene.render.resolution_y
    print(f"Screen dimensions: {screen_width} x {screen_height}")

    fov_x_at_focus_dist = pinhole_to_obj / f_in_mm * sensor_width_mm # (m)
    fov_y_at_focus_dist = pinhole_to_obj / f_in_mm * sensor_height_mm

    scales = np.linspace(1 - depth_variation, 1 + depth_variation, num_planes) # for testing. in practice, make this less exaggerated

    fov_xs = (fov_x_at_focus_dist * scales) - 2 * drone_radius # subtracting the width of the drone
    fov_ys = (fov_y_at_focus_dist * scales) - 2 * drone_radius # subtracting the height of the drone
    depths = pinhole_to_obj * scales

    points_per_plane = x_density * y_density
    num_points = len(scales) * points_per_plane
    points_3d = np.zeros((num_points, 3))

    for k, (scale, fov_x, fov_y, depth) in enumerate(zip(scales, fov_xs, fov_ys, depths)):
        xs = np.linspace(-fov_x / 2, fov_x / 2, x_density)
        ys = np.linspace(-fov_y / 2, fov_y / 2, y_density)
        xs_flat, ys_flat = np.meshgrid(xs, ys)
        xs_flat = xs_flat.flatten()
        ys_flat = ys_flat.flatten()

        # zig zag thru the grid, reverse if on odd plane
        for i in range(y_density):
            row_idxs = i * x_density, (i + 1) * x_density
            if i % 2 == 1:
                xs_flat[row_idxs[0]:row_idxs[1]] = xs_flat[row_idxs[0]:row_idxs[1]][::-1]

        if k % 2 == 1:
            xs_flat = xs_flat[::-1]
            ys_flat = ys_flat[::-1]

        points_3d[k*points_per_plane:(k+1)*points_per_plane, 0] = xs_flat
        points_3d[k*points_per_plane:(k+1)*points_per_plane, 1] = ys_flat
        points_3d[k*points_per_plane:(k+1)*points_per_plane, 2] = depth

    def random_points_in_unit_sphere(N):
        """Generate N random 3D points uniformly inside a unit sphere."""
        points = []
        while len(points) < N:
            p = np.random.uniform(-1, 1, size=(N, 3))  # Sample in a cube
            mask = np.linalg.norm(p, axis=1) <= 1  # Keep only points inside the sphere
            points.extend(p[mask])  # Add valid points

        return np.array(points[:N])

    n_points = points_3d.shape[0]
    # GPS noise: Perturb ground truth drone path
    gps_3d_noise = random_points_in_unit_sphere(n_points) * gps_noise_m / 2
    points_3d += gps_3d_noise

    # RTK noise: Perturb reported 3d point locations
    rtk_3d_noise = random_points_in_unit_sphere(n_points) * float(rtk_noise_cm) / 100 / 2
    reported_points_3d = points_3d + rtk_3d_noise

    num_accepteds = [points_per_plane] * len(scales)
    # Set up homogeneous coordinates

    # Get intrinsics info (for 2D projection)
    calib = get_calibration_matrix_K_from_blender(camera)
    f_in_mm = camera.data.lens
    scene = bpy.context.scene
    W = resolution_x_in_px = scene.render.resolution_x
    H = resolution_y_in_px = scene.render.resolution_y
    scale = scene.render.resolution_percentage / 100
    sensor_width_mm = camera.data.sensor_width
    sensor_height_mm = camera.data.sensor_height

    pixel_aspect_ratio = scene.render.pixel_aspect_x / scene.render.pixel_aspect_y

    if (camera.data.sensor_fit == 'VERTICAL'):
        # the sensor height is fixed (sensor fit is horizontal),
        # the sensor width is effectively changed with the pixel aspect ratio
        s_u = resolution_x_in_px * scale / sensor_width_mm / pixel_aspect_ratio  # pixels per milimeter
        s_v = resolution_y_in_px * scale / sensor_height_mm
    else: # 'HORIZONTAL' and 'AUTO'
        # the sensor width is fixed (sensor fit is horizontal),
        # the sensor height is effectively changed with the pixel aspect ratio
        pixel_aspect_ratio = scene.render.pixel_aspect_x / scene.render.pixel_aspect_y
        s_u = resolution_x_in_px * scale / sensor_width_mm
        s_v = resolution_y_in_px * scale * pixel_aspect_ratio / sensor_height_mm

        if camera.type != 'CAMERA':
            raise TypeError("The specified object is not a camera.")

        # Compute 2D locations
        points_2d = points_3d[:, :2] / points_3d[:, -1, None] * f_in_mm
        points_2d = points_2d * s_u + np.array([calib[0][2], calib[1][2]])

    # add columns to the front with numpoints
    points_2d = np.hstack([np.arange(num_points)[:,None], points_2d])
    points_3d = np.hstack([np.arange(num_points)[:,None], points_3d])
    reported_points_3d = np.hstack([np.arange(num_points)[:,None], reported_points_3d])
    angles = np.zeros((points_3d.shape))
    angles[:,0] = np.arange(num_points)

    return num_points, points_2d, points_3d, reported_points_3d, angles, num_accepteds

def initialize_camera(camera_type, focal_length_mm, resolution_percentage, pinhole_to_obj):
    scene = bpy.context.scene

    if camera_type == 'bm12':
        sensor_width_mm=27.03
        sensor_height_mm=14.25
        sensor_resolution_x = 12288
        sensor_resolution_y = 6480

        # Normalize pixel dimensions
        sensor_height_mm_new = sensor_width_mm / sensor_resolution_x * sensor_resolution_y
        percent_err = math.fabs(sensor_height_mm_new - sensor_height_mm) / sensor_height_mm * 100
        assert percent_err < 0.5
        sensor_height_mm = sensor_height_mm_new
    elif camera_type == "arri":
        sensor_width_mm=28.25
        sensor_height_mm=18.17
        sensor_resolution_x = 3424
        sensor_resolution_y = 2202

        # Normalize pixel dimensions
        sensor_height_mm_new = sensor_width_mm / sensor_resolution_x * sensor_resolution_y
        percent_err = math.fabs(sensor_height_mm_new - sensor_height_mm) / sensor_height_mm * 100
        assert percent_err < 0.5
        sensor_height_mm = sensor_height_mm_new
    else:
        raise ValueError('Invalid camera type. Pick from {bm12, arri}')

    # Create camera data
    camera_data = bpy.data.cameras.new("Camera")

    # Set camera intrinsics
    camera_data.sensor_width = sensor_width_mm
    camera_data.sensor_height = sensor_height_mm
    camera_data.lens = focal_length_mm

    # Set render settings
    scene.render.resolution_x = sensor_resolution_x
    scene.render.resolution_y = sensor_resolution_y
    scene.render.resolution_percentage = resolution_percentage
    scene.render.pixel_aspect_x = 1
    scene.render.pixel_aspect_y = 1

    # Create camera object
    camera_object = bpy.data.objects.new("Camera 1", camera_data)

    # Set camera location
    camera_object.location = (0, 0, 0)
    camera_object.rotation_euler = (math.radians(180), math.radians(0), math.radians(0))  # point in +Z

    scene.collection.objects.link(camera_object)

    # Calculate board size from FOV
    FOV_x = pinhole_to_obj / focal_length_mm * sensor_width_mm
    FOV_y = pinhole_to_obj / focal_length_mm * sensor_height_mm
    board_size = 1.0 * max(FOV_x, FOV_y)

    return camera_object, board_size

def initialize_board(board_size, density):
    bpy.ops.mesh.primitive_circle_add(radius=board_size / 4, vertices = 64, location=(0, 0, 1))
    sphere = bpy.context.object
    sphere.name = "flat"

    bpy.context.view_layer.objects.active = sphere
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.fill()
    bpy.ops.object.mode_set(mode='OBJECT')

    sphere.scale[0] = 1.0
    sphere.scale[1] = 1.0

    material = bpy.data.materials.new(name="SolidMaterial")
    material.diffuse_color = (0.8, 0.2, 0.2, 1) # Red color

    if len(sphere.data.materials) > 0:
        sphere.data.materials[0] = material
    else:
        sphere.data.materials.append(material)

    sphere.rotation_euler = (math.radians(180), math.radians(0), math.radians(0))

    # board_canonical_coords_2d = get_canonical_aprilgrid_points_2d(board_size)
    board_canonical_coords_2d = get_canonical_meshgrid_points_2d(board_size, density)

    return sphere, board_canonical_coords_2d

def get_canonical_aprilgrid_points_2d(board_size):
    tag_size = board_size / 0.1 * 0.006
    spacing_multiplier = 0.3
    nCols = 11
    nRows = 8

    # Compute board size
    total_width = (nCols + (nCols - 1) * spacing_multiplier) * tag_size
    total_height = (nRows + (nRows - 1) * spacing_multiplier) * tag_size

    center_offset = np.array([total_width / 2, total_height / 2])

    coords = []

    for j in range(2 * nRows):
        for i in range(2 * nCols):
            x_coord = (1 + spacing_multiplier) * tag_size * (i // 2) + tag_size * (i % 2)
            y_coord = (1 + spacing_multiplier) * tag_size * (j // 2) + tag_size * (j % 2)

            coords.append([x_coord, y_coord])

    coords = np.array(coords)
    coords = coords - center_offset

    return coords

def get_canonical_meshgrid_points_2d(board_size, density):
    nCols = density
    nRows = density

    xv, yv = np.meshgrid(np.linspace(-board_size/2, board_size/2, nCols), np.linspace(-board_size/2, board_size/2, nRows))
    coords = np.stack([xv.flatten(), yv.flatten()], axis=-1)

    return coords

def plot_points2d(points_2d, filename, focal_length_mm, pinhole_to_obj):
    points = np.array(points_2d)
    fig, ax = plt.subplots()
    rect = patches.Rectangle((0, 0), 3424, 2202, linewidth=1, edgecolor='r', facecolor='none')
    ax.add_patch(rect)
    ax.scatter(points[:,1], points[:,2], marker="o", s=1, c=points[:,0], cmap="viridis")
    fig.gca().invert_yaxis()
    ax.set_title(f"Focal length: {focal_length_mm}mm, Pinhole to obj: {pinhole_to_obj}m")
    fig.savefig(filename)

def main(args):
    camera_type = args.camera_type
    drone_radius = args.drone_radius
    focal_length_mm = args.focal_length_mm
    pinhole_to_obj = args.pinhole_to_obj
    resolution_percentage = args.resolution_percentage
    x_density = args.x_density
    y_density = args.y_density
    num_planes = args.num_planes
    depth_variation = args.depth_variation
    gps_noise_m = args.gps_noise_m
    rtk_noise_cm = args.rtk_noise_cm
    root_folder = args.root_folder
    coord_convention = args.coord_convention

    exp_name = args.exp_name or f'synthdrone_zoom_{focal_length_mm}_pinhole_to_obj_{pinhole_to_obj}_drone_radius_{drone_radius}_path_{x_density}x{y_density}x{num_planes}_depthvar_{depth_variation}'
    exp_root_folder = os.path.join(root_folder, exp_name)
    os.makedirs(exp_root_folder, exist_ok=True)

    # Delete all objects in the scene and clear corresponding data
    clear_scene()
    scene = bpy.context.scene

    for cam in bpy.data.cameras:
        if cam.users == 0:
            bpy.data.cameras.remove(cam)

    for light in bpy.data.lights:
        if light.users == 0:
            bpy.data.lights.remove(light)

    for action in bpy.data.actions:
        if action.users == 0:
            bpy.data.actions.remove(action)

    # Make sure scene is 1:1
    scene.unit_settings.scale_length = 1.0

    # Create a camera
    camera, board_size = initialize_camera(camera_type=camera_type, focal_length_mm=focal_length_mm, resolution_percentage=resolution_percentage, pinhole_to_obj=pinhole_to_obj)

    # Generate board movements
    num_frames, points_2d, points_3d, reported_points_3d, angles, num_accepteds = generate_board_movements(camera, pinhole_to_obj, drone_radius, x_density, y_density, num_planes, depth_variation, gps_noise_m=gps_noise_m, rtk_noise_cm=rtk_noise_cm)

    # normalize 3d points around origin & within unit sphere
    reported_points_3d_normalized = normalize_drone_coordinates(reported_points_3d)

    # Print calibration matrix
    calib_matrix = get_calibration_matrix_K_from_blender(camera)
    print("Calib matrix:", calib_matrix)

    with open(f'{exp_root_folder}/{CALIBRATION_MATRIX}', 'w') as file:
        file.write(str(calib_matrix))

    if points_2d is not None:
        # plot points_2d and save to figure
        plot_points2d(points_2d, f"{exp_root_folder}/{DETECTION_COORDS_PLOT}", focal_length_mm, pinhole_to_obj)
        with open(f'{exp_root_folder}/{DETECTION_COORDS}', mode='w', newline='') as file, open(f'{exp_root_folder}/{DETECTION_SUCCESSES}', 'w') as successes_file:
            writer = csv.writer(file)

            # Write each point on a new line
            for point in points_2d:
                # force all points to be in same observation,
                shift = 0.5 if coord_convention == "kalibr" else 0
                row = [x - shift for x in point]
                row[0] = 0
                writer.writerow(row)
                successes_file.write("0,1\n")

    if points_3d is not None:
        with open(f'{exp_root_folder}/{GT_3D_CSV}', mode='w', newline='') as file:
            writer = csv.writer(file)
            for point in points_3d:
                writer.writerow(point)

    # Use noisy 3d as input to Kalibr
    if reported_points_3d is not None:
        with open(f'{exp_root_folder}/{TARGET_CSV}', mode='w', newline='') as file:
            writer = csv.writer(file)
            for point in reported_points_3d:
                writer.writerow(point)

        with open(f'{exp_root_folder}/{TARGET_NORM_CSV}', mode='w', newline='') as file:
            writer = csv.writer(file)
            for point in reported_points_3d_normalized:
                writer.writerow(point)

        # yaml file should contain normalized coords
        with open(f'{exp_root_folder}/{TARGET_YAML}', mode='w', newline='') as file:
            file.write("target_type: pointcloud\npoints:\n")
            for point in reported_points_3d_normalized:
                file.write(f"- [{point[1]}, {point[2]}, {point[3]}]\n")

    if angles is not None:
        with open(f'{exp_root_folder}/{ANGLES_CSV}', mode='w', newline='') as file:
            writer = csv.writer(file)
            for angle in angles:
                writer.writerow(angle)

    # nice to have, not required for the rest of the pipeline
    if num_accepteds is not None:
        with open(f'{exp_root_folder}/{NUM_ACCEPTED}', mode='w', newline='') as file:
            for n in num_accepteds:
                file.write(f"{n}\n")

    print(f"Wrote coordinates to {exp_root_folder}")


if __name__ == "__main__":
    raise SystemExit(
        "This module is a helper and is not a supported standalone entrypoint. Run run_all_drones.py instead."
    )
