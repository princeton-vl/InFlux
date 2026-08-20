import bpy
import csv
import logging
import math
import numpy as np
import os
import sys

from mathutils import Matrix, Euler


def import_image_as_mesh_plane(image_path, height):
    """Import a shadeless board plane with Blender 4.2's native operator."""
    image_path = os.path.abspath(image_path)
    result = bpy.ops.image.import_as_mesh_planes(
        "EXEC_DEFAULT",
        files=[{"name": os.path.basename(image_path)}],
        directory=os.path.dirname(image_path) + os.sep,
        shader="SHADELESS",
        interpolation="Linear",
        extension="CLIP",
        use_transparency=False,
        relative=False,
        align_axis="+Z",
        offset=False,
        height=float(height),
    )
    if "FINISHED" not in result:
        raise RuntimeError(f"Could not import board image as a mesh plane: {image_path}")
    return bpy.context.view_layer.objects.active

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
    f_in_mm = camera.lens
    scene = bpy.context.scene
    W = resolution_x_in_px = scene.render.resolution_x
    H = resolution_y_in_px = scene.render.resolution_y
    scale = scene.render.resolution_percentage / 100
    sensor_width_mm = camera.sensor_width
    sensor_height_mm = camera.sensor_height

    pixel_aspect_ratio = scene.render.pixel_aspect_x / scene.render.pixel_aspect_y

    if (camera.sensor_fit == 'VERTICAL'):
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

def generate_board_movements(camera, board, pinhole_to_obj, angle=45, board_canonical_coords_2d=None):
    scene = bpy.context.scene

    # Compute FOV bounds at chosen focus distance(s)
    f_in_mm = camera.lens
    sensor_width_mm = camera.sensor_width
    sensor_height_mm = camera.sensor_height

    FOV_x = pinhole_to_obj / f_in_mm * sensor_width_mm
    FOV_y = pinhole_to_obj / f_in_mm * sensor_height_mm

    # Verify that board fits within FOV
    board_width = board.dimensions[0]
    board_height = board.dimensions[1]

    ### Compute board keypoints ###
    def add_tuples(tuples):
        result = (0, 0, 0)
        for tup in tuples:
            result = (result[0] + tup[0], result[1] + tup[1], result[2] + tup[2])
        return result

    # Default board coordinates: board is cenetered in FOV
    base_board_coordinates = (0, 0, pinhole_to_obj)
    base_board_orientation = (math.radians(180), math.radians(0), math.radians(0))

    # Offset calculations
    def get_skew_orientation_offset(frontmost_edge):
        if frontmost_edge == 'left':
            return (math.radians(0), math.radians(-angle), math.radians(0))
        elif frontmost_edge == 'right':
            return (math.radians(0), math.radians(angle), math.radians(0))
        elif frontmost_edge == 'top':
            return (math.radians(angle), math.radians(0), math.radians(0))
        elif frontmost_edge == 'bottom':
            return (math.radians(-angle), math.radians(0), math.radians(0))
        elif frontmost_edge == 'none':
            return (math.radians(0), math.radians(0), math.radians(0))
        else:
            raise ValueError('Invalid frontmost edge. Pick from {left, right, top, bottom, none}')

    def get_skew_and_flat_corner_offset(frontmost_edge, is_front, corner):
        if frontmost_edge == 'none':
            # Offsets to place flat board into corners of the FOV
            corner_x_offset = (FOV_x - board_width) / 2
            corner_y_offset = (FOV_y - board_height) / 2
        else:
            # Figure out skew specific details
            if frontmost_edge == 'left':
                base_length = board_width
                secondary_length = board_height
                fov_length = FOV_x
                secondary_fov_length = FOV_y
                aligned_edge = frontmost_edge if is_front else 'right'
            elif frontmost_edge == 'right':
                base_length = board_width
                secondary_length = board_height
                fov_length = FOV_x
                secondary_fov_length = FOV_y
                aligned_edge = frontmost_edge if is_front else 'left'
            elif frontmost_edge == 'top':
                base_length = board_height
                secondary_length = board_width
                fov_length = FOV_y
                secondary_fov_length = FOV_x
                aligned_edge = frontmost_edge if is_front else 'bottom'
            elif frontmost_edge == 'bottom':
                base_length = board_height
                secondary_length = board_width
                fov_length = FOV_y
                secondary_fov_length = FOV_x
                aligned_edge = frontmost_edge if is_front else 'top'
            else:
                raise ValueError('Invalid frontmost edge. Pick from {left, right, top, bottom, none}')

            # Compute main, complicated offset
            edge_to_board_center = base_length / 2 * math.cos(math.radians(angle))

            closer_scale_factor = (1 - (base_length / 2 * math.sin(math.radians(angle))) / pinhole_to_obj)
            further_scale_factor = (1 + (base_length / 2 * math.sin(math.radians(angle))) / pinhole_to_obj)

            closer_edge_to_axis_length = fov_length / 2 * closer_scale_factor
            further_edge_to_axis_length = fov_length / 2 * further_scale_factor

            if is_front:
                offset_distance = closer_edge_to_axis_length - edge_to_board_center
            else:
                offset_distance = min(further_edge_to_axis_length - edge_to_board_center, closer_edge_to_axis_length + edge_to_board_center)

            # Compute secondary offset (mangification + projection)
            secondary_offset_distance = (secondary_fov_length * closer_scale_factor - secondary_length) / 2

            if aligned_edge == 'left' or aligned_edge == 'right':
                corner_x_offset = offset_distance
                corner_y_offset = secondary_offset_distance
            else:
                corner_x_offset = secondary_offset_distance
                corner_y_offset = offset_distance

        if corner == 'top_right':
            return (corner_x_offset, -corner_y_offset, 0)
        elif corner == 'top_left':
            return (-corner_x_offset, -corner_y_offset, 0)
        elif corner == 'bottom_right':
            return (corner_x_offset, corner_y_offset, 0)
        elif corner == 'bottom_left':
            return (-corner_x_offset, corner_y_offset, 0)
        else:
            raise ValueError('Invalid corner. Pick from {top_right, top_left, bottom_right, bottom_left}')

    def get_extrema_among_tuples(tups):
        min_x = float('inf')
        max_x = -float('inf')
        min_y = float('inf')
        max_y = -float('inf')

        z_coord = None

        for tup in tups:
            min_x = min(tup[0], min_x)
            max_x = max(tup[0], max_x)
            min_y = min(tup[1], min_y)
            max_y = max(tup[1], max_y)

            if z_coord is None:
                z_coord = tup[2]
            else:
                assert z_coord == tup[2]

        return min_x, max_x, min_y, max_y, z_coord


    count = 1
    if board_canonical_coords_2d is not None:
        points_2d = []
        points_3d = []

        # Set up homogeneous coordinates
        append_array = np.zeros(board_canonical_coords_2d.shape)
        append_array[:, 1] = 1  # Set the second column to 1
        canonical_points = np.hstack((board_canonical_coords_2d, append_array))

        # Get intrinsics info (for 2D projection)
        calib = get_calibration_matrix_K_from_blender(camera)
        f_in_mm = camera.lens
        scene = bpy.context.scene
        W = resolution_x_in_px = scene.render.resolution_x
        H = resolution_y_in_px = scene.render.resolution_y
        scale = scene.render.resolution_percentage / 100
        sensor_width_mm = camera.sensor_width
        sensor_height_mm = camera.sensor_height

        pixel_aspect_ratio = scene.render.pixel_aspect_x / scene.render.pixel_aspect_y

        if (camera.sensor_fit == 'VERTICAL'):
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

    else:
        points_2d = None
        points_3d = None

    for skew in ['none', 'left', 'right', 'top', 'bottom']:
        board_rotation = add_tuples([base_board_orientation, get_skew_orientation_offset(skew)])
        rotation_matrix = Euler(get_skew_orientation_offset(skew)).to_quaternion().to_matrix().to_3x3()
        board_extrema_locations = []

        for corner in ['top_left', 'top_right', 'bottom_left', 'bottom_right']:
            is_front = skew in corner

            # Determine board locations for each extreme corner
            board_extrema_locations.append(add_tuples([base_board_coordinates, get_skew_and_flat_corner_offset(skew, is_front, corner)]))

        # Check board actually fits
        # assert board_extrema_locations[0][0] < board_extrema_locations[1][0]  # x: left < right
        # assert board_extrema_locations[0][1] < board_extrema_locations[2][1]  # y: top < bottom

        min_x, max_x, min_y, max_y, z_coord = get_extrema_among_tuples(board_extrema_locations)

        # Heuristic: for each x% of board dimension between extrema coords, add a node
        if skew == 'none':
            nx = 5
            ny = 4

        x_range = np.linspace(min_x, max_x, nx)
        y_range = np.linspace(min_y, max_y, ny)

        for y_coord in y_range:
            for x_coord in x_range:
                board.location = (x_coord, y_coord, z_coord)
                board.rotation_euler = board_rotation
                board.keyframe_insert(data_path='location', frame=count)
                board.keyframe_insert(data_path='rotation_euler', frame=count)

                # If canonical points are specified, compute 3D locations and 2D projections
                if board_canonical_coords_2d is not None:
                    # Build extrinsics matrix
                    extrinsics = np.hstack((np.array(rotation_matrix), np.array(board.location)[:, None]))
                    append_array = np.array([0, 0, 0, 1])
                    extrinsics = np.vstack((extrinsics, append_array))

                    # Compute 3D locations
                    batch_3d = extrinsics[None, ...] @ canonical_points[..., None]
                    batch_3d = batch_3d[:, :-1, 0] / batch_3d[:, -1]
                    points_3d += [(count - 1, point_3d[0], point_3d[1], point_3d[2]) for point_3d in batch_3d]

                    # Compute 2D locations
                    batch_2d = batch_3d[:, :2] / batch_3d[:, -1, None] * f_in_mm
                    batch_2d = batch_2d * s_u + np.array([calib[0][2], calib[1][2]])

                    points_2d += [(count - 1, point_2d[0], point_2d[1]) for point_2d in batch_2d]

                count += 1

    num_frames = count - 1
    for frame in range(1, num_frames + 1):
        scene.frame_set(frame)

    return num_frames, points_2d, points_3d

def render_frames(camera, num_frames, exp_root_folder):
    scene = bpy.context.scene

    # Set the start and end frames of your animation
    start_frame = 1
    end_frame = num_frames

    # Set the scene's start and end frame
    scene.frame_start = start_frame
    scene.frame_end = end_frame

    scene.camera = camera

    # Iterate over each frame and render
    for frame in range(start_frame, end_frame + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        scene.render.filepath = f'{exp_root_folder}/frame_{frame:04}.png'
        bpy.ops.render.render(write_still=True)


def initialize_camera(camera_type, camera_focal_length_in_mm, resolution_percentage):
    scene = bpy.context.scene

    if camera_type == 'bm12':
        # sensor_width_mm=27.03
        # sensor_height_mm=14.25
        # sensor_resolution_x = 12288
        # sensor_resolution_y = 6480
        raise ValueError('Invalid camera type. Pick from {arri}')
    elif camera_type =='arri':
        sensor_width_mm=28.25
        sensor_height_mm=18.17
        sensor_resolution_x = 3424
        sensor_resolution_y = 2202
    else:
        raise ValueError('Invalid camera type. Pick from {arri}')

    # Normalize pixel dimensions
    sensor_height_mm_new = sensor_width_mm / sensor_resolution_x * sensor_resolution_y
    percent_err = math.fabs(sensor_height_mm_new - sensor_height_mm) / sensor_height_mm * 100
    assert percent_err < 0.5
    sensor_height_mm = sensor_height_mm_new

    # Create camera data
    camera_data = bpy.data.cameras.new("Camera")

    # Set camera intrinsics
    camera_data.sensor_width = sensor_width_mm
    camera_data.sensor_height = sensor_height_mm
    camera_data.lens = camera_focal_length_in_mm

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

    return camera_object

def initialize_board(board_size, noise_level):
    scene = bpy.context.scene

    # Board size specific settings
    if board_size == 0.1:
        image_path = 'board_designs/calib.io_kalibr_100x75_8x11_6_v2.png'
        size = 0.1
        tag_size = 0.006
        spacing_multiplier = 0.3
        nCols = 11
        nRows = 8
    elif board_size == 0.2:
        image_path = 'board_designs/calib.io_kalibr_200x150_8x11_12.png'
        size = 0.2
        tag_size = 0.012
        spacing_multiplier = 0.3
        nCols = 11
        nRows = 8
    elif board_size == 0.4:
        image_path = 'board_designs/calib.io_kalibr_400x300_8x11_24.png'
        size = 0.4
        tag_size = 0.024
        spacing_multiplier = 0.3
        nCols = 11
        nRows = 8
    elif board_size == 0.8:
        image_path = 'board_designs/calib.io_kalibr_800x600_8x11_48.png'
        size = 0.8
        tag_size = 0.048
        spacing_multiplier = 0.3
        nCols = 11
        nRows = 8
    elif board_size == 1.6:
        image_path = 'board_designs/calib.io_kalibr_800x600_4x5_96.png'
        size = 0.8
        tag_size = 0.096
        spacing_multiplier = 0.3
        nCols = 5
        nRows = 4
    elif board_size == 3.2:
        image_path = 'board_designs/calib.io_kalibr_3200x2400_8x11_192.png'
        size = 3.2
        tag_size = 0.192
        spacing_multiplier = 0.3
        nCols = 11
        nRows = 8
    elif board_size == 6.4:
        image_path = 'board_designs/calib.io_kalibr_3200x2400_4x6_384.png'
        size = 3.2
        tag_size = 0.384
        spacing_multiplier = 0.3
        nCols = 6
        nRows = 4
    else:
        raise ValueError(
            'Invalid calibration board size. '
            'Pick from {0.1, 0.2, 0.4, 0.8, 1.6, 3.2, 6.4}'
        )

    if noise_level == 0:
        board_canonical_coords_2d = get_canonical_board_points_2d(tag_size, spacing_multiplier, nCols, nRows)
    else:
        board_canonical_coords_2d = None

    # Attempt with planes
    # bpy.ops.image.import_as_mesh_planes(
    #     shader='SHADELESS',
    #     files=[{'name': os.path.abspath(image_path)}],
    #     directory="/".join(image_path.split("/")[:-1]),
    #     height = size * 0.75
    # )
    import_image_as_mesh_plane(image_path, height=size * 0.75)

    board_object = bpy.data.objects[image_path.split("/")[-1][:-4]]

    # Set board location and orientation
    board_object.location = (0, 0, 1)
    board_object.rotation_euler = (math.radians(180), math.radians(0), math.radians(0))

    return board_object, board_canonical_coords_2d


def get_canonical_board_points_2d(tag_size, spacing_multiplier, nCols, nRows):
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


def run_calib_visualization(board_size, noise_level, camera_focal_length_in_mm, pinhole_to_obj, resolution_percentage, camera_type, root_folder, exp_name):
    # Determine experiment name and setup folders
    exp_root_folder = f'{root_folder}/{exp_name}'
    os.makedirs(exp_root_folder, exist_ok=True)

    # Delete all objects in the scene and clear corresponding data
    clear_scene()
    scene = bpy.context.scene

    for cam in bpy.data.cameras:
        if cam.users == 0:
            bpy.data.cameras.remove(cam)

    #for img in bpy.data.images:
    #    if img.users == 0:
    #        bpy.data.images.remove(img)

    for light in bpy.data.lights:
        if light.users == 0:
            bpy.data.lights.remove(light)

    for action in bpy.data.actions:
        if action.users == 0:
            bpy.data.actions.remove(action)

    # Make sure scene is 1:1
    scene.unit_settings.scale_length = 1.0

    # Create a board
    board, board_canonical_coords_2d = initialize_board(board_size=board_size, noise_level=noise_level)

    # Create a camera
    camera = initialize_camera(camera_type=camera_type, camera_focal_length_in_mm=camera_focal_length_in_mm, resolution_percentage=resolution_percentage)

    # Generate board movements
    num_frames, board_2d_points, board_3d_points = generate_board_movements(camera.data, board, pinhole_to_obj=pinhole_to_obj, angle=45, board_canonical_coords_2d=board_canonical_coords_2d)

    if board_2d_points is not None:
        with open(f'{exp_root_folder}/coords_2d.csv', mode='w', newline='') as file:
            writer = csv.writer(file)

            # Write each point on a new line
            for point in board_2d_points:
                writer.writerow(point)

    if board_3d_points is not None:
        with open(f'{exp_root_folder}/coords_3d.csv', mode='w', newline='') as file:
            writer = csv.writer(file)

            # Write each point on a new line
            for point in board_3d_points:
                writer.writerow(point)

    # Print calibration matrix
    calib_matrix = get_calibration_matrix_K_from_blender(camera.data)
    print(calib_matrix)

    # Render images
    render_frames(camera, num_frames, exp_root_folder)

    with open(f'{exp_root_folder}/calibration_matrix.txt', 'w') as file:
        file.write(f'{calib_matrix[0][0]},{calib_matrix[1][1]},{calib_matrix[0][2]},{calib_matrix[1][2]}')

    return calib_matrix
