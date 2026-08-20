import bpy
import csv
import logging
import math
import os
import sys

from utils import CALIBRATION_MATRIX, DETECTION_COORDS, NO_DISTORTION_DATA, RENDERS_COMPLETE
from mathutils import Matrix


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

    ndc = coord_4d.xyz / coord_4d.w

    # Map NDC to screen coordinates
    screen_x = (ndc.x + 1) / 2 * scene.render.resolution_x
    screen_y = (1 - ndc.y) / 2 * scene.render.resolution_y  # Flip Y for screen
    return screen_x, screen_y

def initialize_camera(camera_type, focal_length_mm, resolution_percentage):
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

    return camera_object

def initialize_board(drone_radius):
    # Create a flat circular board
    bpy.ops.mesh.primitive_circle_add(radius=drone_radius, vertices=64, location=(0, 0, 1))
    board = bpy.context.object
    board.name = "flat_board"

    # Fill the circle to make it a disc
    bpy.context.view_layer.objects.active = board
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.fill()
    bpy.ops.object.mode_set(mode='OBJECT')

    # Ensure correct scaling
    board.scale[0] = 1.0
    board.scale[1] = 1.0

    # Apply a red material
    material = bpy.data.materials.new(name="SolidMaterial")
    material.diffuse_color = (0.8, 0.2, 0.2, 1)  # Red color

    if len(board.data.materials) > 0:
        board.data.materials[0] = material
    else:
        board.data.materials.append(material)

    # Rotate the board so it faces upwards
    board.rotation_euler = (math.radians(180), 0, 0)

    return board


def generate_board_movements(scene, camera, board, pinhole_to_obj, angles, coords):
    count = 1

    for angle, coord in zip(angles, coords):
        x_coord, y_coord, z_coord = coord
        x_ang, y_ang, z_ang = angle

        board.location = (x_coord, y_coord, z_coord)
        board.rotation_euler = (math.radians(x_ang), math.radians(y_ang), math.radians(z_ang))
        board.keyframe_insert(data_path='location', frame=count)
        board.keyframe_insert(data_path='rotation_euler', frame=count)

        count += 1

    num_frames = count - 1
    for frame in range(1, num_frames + 1):
        scene.frame_set(frame)

def render_frames(camera, num_frames, output_folder):
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
        scene.render.filepath = f'{output_folder}/frame_{frame:04}.png'
        bpy.ops.render.render(write_still=True)

def main(coords_3d, angle_file, exp_root_folder, led_radius, camera_type, focal_length_mm, pinhole_to_obj, resolution_percentage):
    os.makedirs(exp_root_folder, exist_ok=True)

    ### Prep scene
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
    board = initialize_board(drone_radius=led_radius)

    # Create a camera
    camera = initialize_camera(camera_type=camera_type, focal_length_mm=focal_length_mm, resolution_percentage=resolution_percentage)


    output_folder = f"{exp_root_folder}/{NO_DISTORTION_DATA}"
    os.makedirs(output_folder, exist_ok=True)

    coords = []
    with open(coords_3d, mode='r') as file:
        csv_reader = csv.reader(file)
        for row in csv_reader:
            coords.append([float(row[1]), float(row[2]), float(row[3])])

    angles = []
    with open(angle_file, mode='r') as file:
        csv_reader = csv.reader(file)
        for row in csv_reader:
            angles.append([float(row[1]), float(row[2]), float(row[3])])

    n = len(coords)

    generate_board_movements(scene, camera, board, pinhole_to_obj=pinhole_to_obj, angles = angles, coords = coords)

    render_frames(camera, n, output_folder)

    return n
