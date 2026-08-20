import argparse
import json
import matplotlib.pyplot as plt
import numpy as np
import os
import seaborn as sns
import sys

if __name__ == "__main__":
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    sys.path.append(os.path.dirname(SCRIPT_DIR))

from common_utils import config, get_camera_info
from scipy.spatial import Delaunay


np.set_printoptions(linewidth=np.inf)

class LUT:
    def __init__(self, experiment_data_path, lens):
        # Check that the specified lens is valid
        assert lens in config['lenses'].keys()

        # Ordering of how intrinsics are stored in intrinsics grid
        self.intrinsics_ordering = ['fx', 'fy', 'cx', 'cy', 'k1', 'k2', 'p1', 'p2']
        self.dim_map = {intr_str: idx for idx, intr_str in enumerate(self.intrinsics_ordering)}

        # Color mapping for visualization
        self.color_map = {"l" : np.array([1.,1,1]), "r" : np.array([1.,0,0]), "g" : np.array([0.,1,0]), "b" : np.array([0.,0,1]),}

        self.from_json(experiment_data_path, lens)
        self.make_regions()
        self.make_extrapolations()


    def from_json(self, experiment_data_path, lens):
        self.lens = lens

        # Read in selected experiment raw data
        with open(experiment_data_path, "r") as f:
            experiment_data = json.load(f)

        self.approx_zooms = experiment_data['zooms']
        self.approx_fds = experiment_data['focus_distances']

        self.nzoom = len(self.approx_zooms)
        self.nfdist = len(self.approx_fds)

        self.nintr = len(self.dim_map)

        # Create grid to hold actual zoom and focus distance values
        self.actual_metadata_grid = np.zeros((self.nzoom, self.nfdist, 2))  # 2 for (zoom, fdist)

        # Create per-zoom data structure for extrapolation calculations
        self.per_zoom_data = {}

        # Create grid to hold intrinsics values, indexed by zoom and focus distance
        self.grid = np.zeros((self.nzoom, self.nfdist, self.nintr))
        self.drone = {}

        self.color_grid = {}

        experiments = experiment_data['exp_details']
        self.experiments = experiments

        for zoom_ind in range(self.grid.shape[0]):
            for fdist_ind in range(self.grid.shape[1]):

                exp_name = f"zoom_{zoom_ind}_focus_distance_{fdist_ind}"

                # Fill in data if the experiment is valid; otherwise, fill with NaNs
                if exp_name in experiments.keys() and experiments[exp_name]["selected_trial"] != "invalid":

                    exp = experiments[exp_name]
                    data = np.array([exp[intr_str] for intr_str in self.intrinsics_ordering])
                    metadata = np.array([exp['zoom'], exp['focus_distance']])

                    self.actual_metadata_grid[zoom_ind, fdist_ind] = metadata

                    # Fill in per-zoom data structure
                    zoom = int(metadata[0])
                    focus_distance = metadata[1]
                    if zoom not in self.per_zoom_data.keys():
                        self.per_zoom_data[zoom] = {'fds': [], 'intrinsics': []}
                    self.per_zoom_data[zoom]['fds'].append(focus_distance)
                    self.per_zoom_data[zoom]['intrinsics'].append(data)

                    # Fill in grid and drone data structures
                    if exp['board_size'] == 'drone':
                        # Add datapoint to drone dict instead of grid
                        self.drone[(zoom_ind, fdist_ind)] = data
                        self.grid[zoom_ind, fdist_ind] = np.array([np.nan] * self.nintr)
                        self.color_grid[(zoom_ind, fdist_ind)] = 'U'
                    else:
                        # Add datapoint to grid
                        self.grid[zoom_ind, fdist_ind] = data

                        # assign colors to grid for visualization
                        if zoom_ind % 2 == 0 and fdist_ind % 2 == 0:
                            self.color_grid[(zoom_ind, fdist_ind)] = 'l'
                        elif zoom_ind % 2 == 0 and fdist_ind % 2 != 0:
                            self.color_grid[(zoom_ind, fdist_ind)] = 'r'
                        elif zoom_ind % 2 != 0 and fdist_ind % 2 == 0:
                            self.color_grid[(zoom_ind, fdist_ind)] = 'g'
                        elif zoom_ind % 2 != 0 and fdist_ind % 2 != 0:
                            self.color_grid[(zoom_ind, fdist_ind)] = 'b'
                else:
                    self.grid[zoom_ind, fdist_ind] = np.array([np.nan] * self.nintr)

        # Manual color assignments for visualizing specific lenses with drone experiments
        if self.lens == 'canon17':
            # NOTE canon17 drone point color labeling
            self.color_grid[(0, 7)] = 'l'
            self.color_grid[(3, 7)] = 'b'
            self.color_grid[(0, 9)] = 'r'
            self.color_grid[(2, 9)] = 'g'
            self.color_grid[(3, 9)] = 'l'
            self.color_grid[(4, 9)] = 'b'
            self.color_grid[(7, 9)] = 'r'

        elif self.lens == 'premista80':
            # NOTE premista80 drone point color labeling
            self.color_grid[(0, 9)] = 'b'
            self.color_grid[(2, 9)] = 'r'
            self.color_grid[(4, 9)] = 'b'


    def get_colors(self, region):
        if region.shape[0] == 3:
            (x_0, y_0), (x_1, y_1), (x_2, y_2) = region

            c0 = self.color_map[self.color_grid[(x_0, y_0)]]
            c1 = self.color_map[self.color_grid[(x_1, y_1)]]
            c2 = self.color_map[self.color_grid[(x_2, y_2)]]

            return c0, c1, c2

        (x_0, y_0), (x_1, y_1), (x_2, y_2), (x_3, y_3) = region

        c0 = self.color_map[self.color_grid[(x_0, y_0)]]
        c1 = self.color_map[self.color_grid[(x_1, y_1)]]
        c2 = self.color_map[self.color_grid[(x_2, y_2)]]
        c3 = self.color_map[self.color_grid[(x_3, y_3)]]

        return c0, c1, c2, c3


    def get_point_values(self, region):
        point_values = []

        for zoom, fdist in region:
            point_values.append(self.actual_metadata_grid[zoom, fdist][0])  # zoom value
            point_values.append(self.actual_metadata_grid[zoom, fdist][1])  # focus distance value

        return point_values


    def get_intrinsic(self, zoom_and_fdist, intrinsic, is_drone, ensure_region_type=True):
        zind = self.dim_map[intrinsic]
        zoom_ind, fdist_ind = zoom_and_fdist
        tup = tuple(map(int, (zoom_ind, fdist_ind)))

        if ensure_region_type:
            return (
                self.drone[tup][zind]
                if is_drone
                else self.grid[zoom_ind, fdist_ind, zind]
            )

        # If we're not ensuring region type, try both options
        try:
            return self.drone[tup][zind]
        except (KeyError, IndexError):
            pass

        try:
            return self.grid[zoom_ind, fdist_ind, zind]
        except (KeyError, IndexError):
            pass

        raise KeyError(f"No intrinsic found for indices {zoom_and_fdist} (drone={is_drone})")


    def make_regions(self):
        # all regions are lists of np.arrays, 3x2 for triangles and 4x2 for quads
        self.grid_regions = []
        edge_points = []

        for i in range(self.nzoom - 1):
            for j in range(self.nfdist - 1):
                quad = self.grid[i : i + 2, j : j + 2, 0]

                if not np.any(np.isnan(quad)):
                    self.grid_regions.append(np.array([[i, j], [i, j + 1], [i + 1, j], [i + 1, j + 1]]))

                elif not np.all(np.isnan(quad)):
                    edge_ps = np.argwhere(~np.isnan(quad)) + np.array([i, j])

                    for p in edge_ps:
                        edge_points.append(p)

        edge_points = np.array(edge_points)
        edge_points = np.unique(edge_points, axis=0)

        # Copy edge points of grid into drone dictionary if not already present
        for (zoom_ind, fdist_ind) in edge_points:
            if (zoom_ind, fdist_ind) not in self.drone.keys():
                self.drone[(zoom_ind, fdist_ind)] = self.grid[zoom_ind, fdist_ind].copy()

        triangulation_points = np.array(list(self.drone.keys()))

        if len(triangulation_points) >= 3:
            triangles = Delaunay(triangulation_points).simplices
            self.drone_regions = [triangulation_points[simplex] for simplex in triangles]
        else:
            self.drone_regions = []


    def region_mask(self, zoom_and_fdist, region):
        if region.shape[0] == 4:
            triangle1 = region[[0, 1, 3]]
            triangle2 = region[[0, 2, 3]]

            return self.check_in_triangle(zoom_and_fdist, triangle1) | self.check_in_triangle(zoom_and_fdist, triangle2)

        return self.check_in_triangle(zoom_and_fdist, region)


    def check_in_triangle(self, zoom_and_fdist, triangle, loose_check_percent_threshold=None):

        def area(x1, y1, x2, y2, x3, y3):
            return abs((x1*(y2 - y3) + x2*(y3 - y1) + x3*(y1 - y2)) / 2.0)

        # Check if within the triangle of actual zoom and fdist values, not their index
        x1, y1, x2, y2, x3, y3 = self.get_point_values(triangle)

        # px, py = zoom_val, fdist_val
        px, py = zoom_and_fdist[:, 0], zoom_and_fdist[:, 1]

        # Area of the full triangle
        A = area(x1, y1, x2, y2, x3, y3)

        # Area of the three sub-triangles with the point
        A1 = area(px, py, x2, y2, x3, y3)
        A2 = area(x1, y1, px, py, x3, y3)
        A3 = area(x1, y1, x2, y2, px, py)

        if loose_check_percent_threshold is not None:
            # Allow for some error in the area comparison
            threshold = loose_check_percent_threshold * A
            return np.abs(A - (A1 + A2 + A3)) < threshold
        else:
            # Check if sum of A1, A2, and A3 is equal to A
            return np.isclose(A, A1 + A2 + A3)


    def trapezoidal_interpolation(self, input, quad, intrinsic, ensure_region_type=True):
        zoom_0, fdist_0, zoom_1, fdist_1, zoom_2, fdist_2, zoom_3, fdist_3 = self.get_point_values(quad)

        assert zoom_0 - zoom_2 == zoom_1  - zoom_3

        z_0, z_1, z_2, z_3 = [self.get_intrinsic(quad[i], intrinsic, is_drone=False, ensure_region_type=ensure_region_type) for i in range(4)]


        def upper_line(x):
            m = (fdist_3 - fdist_1) / (zoom_3 - zoom_1)
            b = fdist_3 - m * zoom_3

            return m * x + b

        def lower_line(x):
            m = (fdist_2 - fdist_0) / (zoom_2 - zoom_0)
            b = fdist_2 - m * zoom_2

            return m * x + b

        fx = (input[:, 0] - zoom_0) / (zoom_2 - zoom_0)
        fy = (input[:, 1] - lower_line(input[:, 0])) / (upper_line(input[:, 0]) - lower_line(input[:, 0]))


        output = (1 - fx) * (1 - fy) * z_0
        output += (1 - fx) * fy * z_1
        output += fx * (1 - fy) * z_2
        output += fx * fy * z_3

        # Compute color assignment
        c0, c1, c2, c3 = self.get_colors(quad)

        colors = ((1 - fx) * (1 - fy))[..., None] * np.tile(c0, (input.shape[0], 1))
        colors += ((1 - fx) * fy)[..., None] * np.tile(c1, (input.shape[0], 1))
        colors += (fx * (1 - fy))[..., None] * np.tile(c2, (input.shape[0], 1))
        colors += (fx * fy)[..., None] * np.tile(c3, (input.shape[0], 1))

        return output[:, None], colors


    def triangular_interpolation(self, input, tri, intrinsic, ensure_region_type=True):
        x_0, y_0, x_1, y_1, x_2, y_2 = self.get_point_values(tri)
        z_0, z_1, z_2 = [self.get_intrinsic(tri[i], intrinsic, is_drone=True, ensure_region_type=ensure_region_type) for i in range(3)]

        v0 = np.array([x_1 - x_0, y_1 - y_0])
        v1 = np.array([x_2 - x_0, y_2 - y_0])
        v2s = input - np.array([[x_0, y_0]])

        d00 = np.dot(v0, v0)
        d01 = np.dot(v0, v1)
        d11 = np.dot(v1, v1)
        d20s = np.dot(v2s, v0)
        d21s = np.dot(v2s, v1)

        denom = d00 * d11 - d01 * d01

        vs = (d11 * d20s - d01 * d21s) / denom
        us = (d00 * d21s - d01 * d20s) / denom
        ws = 1.0 - vs - us

        barycentric_coords = np.vstack((ws, vs, us)).T

        output = np.sum(barycentric_coords * np.array([z_0, z_1, z_2]), axis=1)

        # Compute color assignment
        c0, c1, c2 = self.get_colors(tri)

        colors = barycentric_coords[:, 0][..., None] * np.tile(c0, (input.shape[0], 1))
        colors += barycentric_coords[:, 1][..., None] * np.tile(c1, (input.shape[0], 1))
        colors += barycentric_coords[:, 2][..., None] * np.tile(c2, (input.shape[0], 1))

        return output[:, None], colors


    def make_extrapolations(self):
        self.extrapolation_constants = {}

        # Get camera sensor info for pixel size conversions
        sensor_width_mm, sensor_height_mm, sensor_resolution_x, sensor_resolution_y, _ = get_camera_info('arri')

        for zoom in self.per_zoom_data.keys():
            fds = np.array(self.per_zoom_data[zoom]['fds'])
            cfls_x = np.array([intrinsics[self.dim_map['fx']] for intrinsics in self.per_zoom_data[zoom]['intrinsics']])
            cfls_y = np.array([intrinsics[self.dim_map['fy']] for intrinsics in self.per_zoom_data[zoom]['intrinsics']])

            # Convert from pixels to mm
            cfls_x = cfls_x / sensor_resolution_x * sensor_width_mm
            cfls_y = cfls_y / sensor_resolution_y * sensor_height_mm

            # Average cfls_x and cfls_y to get single cfls value
            cfls = (cfls_x + cfls_y) / 2

            # Compute pinhole to object distances
            ptos = fds - cfls

            x = 1 / ptos
            y = 1 / cfls

            # Fit line x + y = 1 / c, based on thin lens model
            one_over_c = (x + y).mean()

            self.extrapolation_constants[zoom] = 1 / one_over_c


    def extrapolate_fx_fy(self, input, zoom_min, zoom_max, intrinsic):
        assert intrinsic in ['fx', 'fy']

        # Get camera sensor info for pixel size conversions
        sensor_width_mm, sensor_height_mm, sensor_resolution_x, sensor_resolution_y, _ = get_camera_info('arri')

        # Compute CFL at zoom_min and zoom_max, based on focus distance
        def compute_cfl(fd, c):
            # Compute based on 1 / cfl + 1 / (fd - cfl) = 1 / c
            cfl_mm = (fd - np.sqrt(fd ** 2 - 4 * c * fd)) / 2

            # When fd is -1 (infinity), cfl = c
            cfl_mm[fd == -1] = c

            # Convert from mm back to pixels
            cfl = cfl_mm * sensor_resolution_x / sensor_width_mm
            return cfl

        fd = input[:, 1]
        cfls_zoom_min = compute_cfl(fd, self.extrapolation_constants[zoom_min])
        cfls_zoom_max = compute_cfl(fd, self.extrapolation_constants[zoom_max])

        # Interpolate between zooms
        frac = (input[:, 0] - zoom_min) / (zoom_max - zoom_min)
        return ((1 - frac) * cfls_zoom_min + frac * cfls_zoom_max)[:, None]

    def snap_to_highest_fd(self, input):
        # Keep track of which inputs have not been rectified yet
        output = np.full((input.shape[0], 2), np.nan)

        # Go through all zoom ranges with non-zero fd, and snap fd
        zooms = self.actual_metadata_grid[:, -1, 0]
        fds = self.actual_metadata_grid[:, -1, 1]
        non_zero_mask = zooms != 0
        zooms = zooms[non_zero_mask]
        fds = fds[non_zero_mask]

        for zoom_idx in range(len(zooms) - 1):
            zoom_min, zoom_max = zooms[zoom_idx], zooms[zoom_idx + 1]

            # Define helper function that does rectification
            fd1 = fds[zoom_idx]
            fd2 = fds[zoom_idx + 1]
            def rectify(unrectified_input):
                zoom = unrectified_input[:, 0]
                old_fd = unrectified_input[:, 1]

                frac = (zoom - zoom_min) / (zoom_max - zoom_min)
                new_fd =  (1 - frac) * fd1 + frac * fd2

                assert ((old_fd >= new_fd) | (old_fd == -1)).all()

                return np.hstack((zoom[:, None], new_fd[:, None]))

            # Select all inputs within consecutive zoom values, and still not rectified
            mask = (zoom_min <= input[:, 0]) & (input[:, 0] <= zoom_max) & np.isnan(output).any(axis=-1)
            if mask.sum() > 0:
                output[mask] = rectify(input[mask])

        return output


    def interpolate_all(self, input, intrinsic, extrapolate=False):
        output = np.full((input.shape[0], 1), np.nan)
        colors = np.zeros((input.shape[0], 3))

        used_triangles = []

        for quad in self.grid_regions:
            mask = self.region_mask(input, quad) & np.isnan(output).flatten()
            if mask.sum() > 0:
                o, c = self.trapezoidal_interpolation(input[mask], quad, intrinsic)
                output[mask], colors[mask] = o, c

        for tri in self.drone_regions:
            mask = self.region_mask(input, tri) & np.isnan(output).flatten()
            if mask.sum() > 0:
                output[mask], colors[mask] = self.triangular_interpolation(input[mask], tri, intrinsic)
                used_triangles.append(tri)

        if extrapolate:
            if intrinsic in ['fx', 'fy']:
                # Split input based on zoom values
                for zoom_idx in range(len(self.approx_zooms) - 1):
                    zoom_min, zoom_max = self.approx_zooms[zoom_idx], self.approx_zooms[zoom_idx + 1]

                    # Select all inputs within consecutive zoom values, and still missing value; note that NaN lens metadata will never be picked up for extrapolation
                    mask = (zoom_min <= input[:, 0]) & (input[:, 0] <= zoom_max) & np.isnan(output).flatten()
                    if mask.sum() > 0:
                        output[mask] = self.extrapolate_fx_fy(input[mask], zoom_min, zoom_max, intrinsic)
            else:
                # Select all inputs with non-NaN lens metadata, and missing output
                mask = (~np.isnan(input)).all(axis=-1) & np.isnan(output).flatten()
                if mask.sum() > 0:
                    # Get highest fds supported by LUT
                    modified_input = self.snap_to_highest_fd(input[mask])

                    # Requery interpolation with in bound points
                    output[mask], _, _ = self.interpolate_all(modified_input, intrinsic, extrapolate=False)

        return output, colors, used_triangles


    def visualize_regions(self, input, colors, used_triangles, n_zooms=150, n_fdists=150, region=None, show=True, alpha=0.5, ecol='black', save_path=None):
        plt.rcParams['font.family'] = 'serif'
        fig, ax = plt.subplots(figsize=(6, 6))

        xmin = np.min(input[:, 0])
        xmax = np.max(input[:, 0])
        ymin = np.min(input[:, 1])
        ymax = np.max(input[:, 1])
        ax.imshow(np.clip(colors.reshape((n_fdists, n_zooms, 3)), 0.0, 1.0), extent=[xmin, xmax, ymin, ymax], origin='lower', aspect='auto', interpolation='bilinear')


        if region is None:
            # for triangle in self.drone_regions:
            for triangle in used_triangles:
                x_0, y_0, x_1, y_1, x_2, y_2 = self.get_point_values(triangle)
                ax.fill([x_0, x_1, x_2], [y_0, y_1, y_2], facecolor='none', linewidth=1, alpha=alpha, edgecolor=ecol)

            for quad in self.grid_regions:
                x_0, y_0, x_3, y_3, x_1, y_1, x_2, y_2 = self.get_point_values(quad)
                ax.fill([x_0, x_1, x_2, x_3], [y_0, y_1, y_2, y_3], facecolor='none', linewidth=1, alpha=alpha, edgecolor=ecol)

        elif region.shape[0] == 3:
                x_0, y_0, x_1, y_1, x_2, y_2 = self.get_point_values(region)
                plt.fill([x_0, x_1, x_2], [y_0, y_1, y_2], color='red', alpha=alpha, edgecolor=ecol)

        elif region.shape[0] == 4:
                x_0, y_0, x_3, y_3, x_1, y_1, x_2, y_2 = self.get_point_values(region)
                plt.fill([x_0, x_1, x_2, x_3], [y_0, y_1, y_2, y_3], color='blue', linewidth=3, alpha=alpha, edgecolor=ecol)

        plt.grid(False)

        # Plot LUT and save
        plt.xlim(input[:, 0].min(), input[:, 0].max())
        plt.ylim(input[:, 1].min(), input[:, 1].max())
        plt.xlabel("Focal length (mm)")
        plt.ylabel("Focus distance (mm)")
        plt.title(f"Interpolation over LUT for {self.lens}")

        plt.savefig(save_path)
        plt.show()


    # Leave-one-out cross-validation experiment code
    def get_surrounding_regions(self, zoom_ind, fdist_ind):
        exp = np.array([zoom_ind, fdist_ind])

        grid_regions = []
        drone_regions = []

        for reg in self.grid_regions:
            if np.any(np.all(exp == reg, axis=1)):
                grid_regions.append(reg)

        for reg in self.drone_regions:
            if np.any(np.all(exp == reg, axis=1)):
                drone_regions.append(reg)

        return grid_regions, drone_regions


    def get_interpolation_trial_errors(self, intrinsic='fx', use_percent_error=True):
        error_grid = np.zeros((self.nzoom, self.nfdist)) * np.nan
        interpolation_type_color_grid = np.ones((self.nzoom, self.nfdist, 3))

        for nz in range(0, self.nzoom):
            for nfd in range(0, self.nfdist):
                zoom_extreme = (nz == 0 or nz == self.nzoom - 1)
                fdist_extreme = (nfd == 0 or nfd == self.nfdist - 1)
                if zoom_extreme and fdist_extreme:  # skip corner points, no interpolation possible
                    continue

                input_ind = np.array([[nz, nfd]])
                input_val = np.array([self.get_point_values(input_ind)])

                grs, drs = self.get_surrounding_regions(nz, nfd)

                if len(grs) == 0 and len(drs) == 0:  # no experiment performed, skip
                    continue

                # Get unique set of all vertices of surrounding regions
                all_vertices = np.unique(np.vstack(grs + drs), axis=0)

                # Remove current vertex from consideration for interpolation
                idx = np.where((all_vertices == np.array([nz, nfd])).all(axis=1))[0][0]
                all_vertices = np.delete(all_vertices, idx, axis=0)

                # Find all axis-aligned rectangles that can be formed with the surrounding vertices
                rectangle_indices = get_axis_aligned_rectangles(all_vertices)

                # Use rectangular interpolation if possible
                if len(rectangle_indices) > 0:
                    # Identify rectangle with least span over zoom indices; tiebreaks broken by overall rectangle size (all sizes computed in index differences)
                    rectangle_diagonals = np.array([[rectangle[0], rectangle[1]] for rectangle in rectangle_indices])
                    rectangle_diagonals = all_vertices[rectangle_diagonals]
                    rectangle_diagonals = np.abs(rectangle_diagonals[:, 1] - rectangle_diagonals[:, 0])

                    # Perform rectangle selection
                    row_sum = rectangle_diagonals.sum(axis=1)
                    idx = np.lexsort((row_sum, rectangle_diagonals[:, 0]))[0]
                    selected_rectangle = rectangle_indices[idx]
                    selected_rectangle = all_vertices[np.array(selected_rectangle)]

                    # Perform interpolation
                    zmin, zmax = np.min(selected_rectangle[:, 0]), np.max(selected_rectangle[:, 0])
                    fdmin, fdmax = np.min(selected_rectangle[:, 1]), np.max(selected_rectangle[:, 1])

                    quad_reg = np.array([[zmin, fdmin],
                                        [zmin, fdmax],
                                        [zmax, fdmin],
                                        [zmax, fdmax]])

                    interp, _ = self.trapezoidal_interpolation(input_val, quad_reg, intrinsic, ensure_region_type=False)
                    interp = interp[0, 0]

                    true_intrinsic = self.get_intrinsic(input_ind.squeeze(), intrinsic, is_drone=False, ensure_region_type=False)

                    error_grid[nz, nfd] = np.abs(interp - true_intrinsic) / true_intrinsic if use_percent_error else np.abs(interp - true_intrinsic)

                    interpolation_type_color_grid[nz, nfd] = np.array([0, 1, 0])  # green for quadrilateral interpolation

                else:
                    # Use triangular interpolation if possible
                    triangulation_points = all_vertices

                    triangles = Delaunay(triangulation_points).simplices
                    tri_regs = [triangulation_points[simplex] for simplex in triangles]

                    for tri_reg in tri_regs:
                        if self.check_in_triangle(input_val, tri_reg, loose_check_percent_threshold=1.0)[0]:
                            interp, _ = self.triangular_interpolation(input_val, tri_reg, intrinsic, ensure_region_type=False)
                            interp = interp[0, 0]

                            true_intrinsic = self.get_intrinsic(input_ind.squeeze(), intrinsic, is_drone=True, ensure_region_type=False)

                            error_grid[nz, nfd] = np.abs(interp - true_intrinsic) / true_intrinsic if use_percent_error else np.abs(interp - true_intrinsic)
                            interpolation_type_color_grid[nz, nfd] = np.array([1, 0, 0])  # red for triangular interpolation
                            break

        return error_grid, interpolation_type_color_grid


    def get_leave_one_out_records(self):
        records = {}

        def intrinsics_to_dict(values):
            return {
                intr: float(values[self.dim_map[intr]])
                for intr in self.intrinsics_ordering
            }

        for nz in range(0, self.nzoom):
            for nfd in range(0, self.nfdist):
                exp_name = f"zoom_{nz}_focus_distance_{nfd}"

                record = {
                    "status": "skipped",
                    "reason": None,
                    "interpolation_type": None,
                    "intrinsics_gt": None,
                    "intrinsics_interpolated": None,
                }

                if exp_name not in self.experiments.keys() or self.experiments[exp_name]["selected_trial"] == "invalid":
                    record["reason"] = "no_experiment"
                    records[exp_name] = record
                    continue

                true_values = np.array([self.experiments[exp_name][intr] for intr in self.intrinsics_ordering])
                record["intrinsics_gt"] = intrinsics_to_dict(true_values)

                zoom_extreme = (nz == 0 or nz == self.nzoom - 1)
                fdist_extreme = (nfd == 0 or nfd == self.nfdist - 1)
                if zoom_extreme and fdist_extreme:  # skip corner points, no interpolation possible
                    record["reason"] = "corner_point"
                    records[exp_name] = record
                    continue

                input_ind = np.array([[nz, nfd]])
                input_val = np.array([self.get_point_values(input_ind)])

                grs, drs = self.get_surrounding_regions(nz, nfd)

                if len(grs) == 0 and len(drs) == 0:  # no experiment performed, skip
                    record["reason"] = "no_surrounding_regions"
                    records[exp_name] = record
                    continue

                # Get unique set of all vertices of surrounding regions
                all_vertices = np.unique(np.vstack(grs + drs), axis=0)

                # Remove current vertex from consideration for interpolation
                idx = np.where((all_vertices == np.array([nz, nfd])).all(axis=1))[0][0]
                all_vertices = np.delete(all_vertices, idx, axis=0)

                # Find all axis-aligned rectangles that can be formed with the surrounding vertices
                rectangle_indices = get_axis_aligned_rectangles(all_vertices)

                interpolated_values = {}

                # Use rectangular interpolation if possible
                if len(rectangle_indices) > 0:
                    # Identify rectangle with least span over zoom indices; tiebreaks broken by overall rectangle size (all sizes computed in index differences)
                    rectangle_diagonals = np.array([[rectangle[0], rectangle[1]] for rectangle in rectangle_indices])
                    rectangle_diagonals = all_vertices[rectangle_diagonals]
                    rectangle_diagonals = np.abs(rectangle_diagonals[:, 1] - rectangle_diagonals[:, 0])

                    # Perform rectangle selection
                    row_sum = rectangle_diagonals.sum(axis=1)
                    idx = np.lexsort((row_sum, rectangle_diagonals[:, 0]))[0]
                    selected_rectangle = rectangle_indices[idx]
                    selected_rectangle = all_vertices[np.array(selected_rectangle)]

                    # Perform interpolation
                    zmin, zmax = np.min(selected_rectangle[:, 0]), np.max(selected_rectangle[:, 0])
                    fdmin, fdmax = np.min(selected_rectangle[:, 1]), np.max(selected_rectangle[:, 1])

                    quad_reg = np.array([[zmin, fdmin],
                                        [zmin, fdmax],
                                        [zmax, fdmin],
                                        [zmax, fdmax]])

                    for intrinsic in self.intrinsics_ordering:
                        interp, _ = self.trapezoidal_interpolation(input_val, quad_reg, intrinsic, ensure_region_type=False)
                        interpolated_values[intrinsic] = float(interp[0, 0])

                    record["status"] = "present"
                    record["reason"] = "normal"
                    record["interpolation_type"] = "quadrilateral"
                    record["intrinsics_interpolated"] = interpolated_values

                else:
                    # Use triangular interpolation if possible
                    triangulation_points = all_vertices

                    triangles = Delaunay(triangulation_points).simplices
                    tri_regs = [triangulation_points[simplex] for simplex in triangles]

                    for tri_reg in tri_regs:
                        if self.check_in_triangle(input_val, tri_reg, loose_check_percent_threshold=1.0)[0]:
                            for intrinsic in self.intrinsics_ordering:
                                interp, _ = self.triangular_interpolation(input_val, tri_reg, intrinsic, ensure_region_type=False)
                                interpolated_values[intrinsic] = float(interp[0, 0])

                            record["status"] = "present"
                            record["reason"] = "normal"
                            record["interpolation_type"] = "triangular"
                            record["intrinsics_interpolated"] = interpolated_values
                            break

                if record["status"] == "skipped" and record["reason"] is None:
                    record["reason"] = "no_valid_interpolation_region"

                records[exp_name] = record

        return records


    def visualize_leave_one_out_experiment_trial_types(self, input, colors, used_triangles, interpolation_type_color_grid, n_zooms=150, n_fdists=150, region=None, show=True, alpha=0.5, ecol='black', save_path=None):
        plt.rcParams['font.family'] = 'serif'
        fig, ax = plt.subplots(figsize=(15, 10))

        xmin = np.min(input[:, 0])
        xmax = np.max(input[:, 0])
        ymin = np.min(input[:, 1])
        ymax = np.max(input[:, 1])
        ax.imshow(np.clip(colors.reshape((n_fdists, n_zooms, 3)), 0.0, 1.0), extent=[xmin, xmax, ymin, ymax], origin='lower', aspect='auto', interpolation='bilinear')


        if region is None:
            # for triangle in self.drone_regions:
            for triangle in used_triangles:
                x_0, y_0, x_1, y_1, x_2, y_2 = self.get_point_values(triangle)
                ax.fill([x_0, x_1, x_2], [y_0, y_1, y_2], facecolor='none', linewidth=1, alpha=alpha, edgecolor=ecol)

            for quad in self.grid_regions:
                x_0, y_0, x_3, y_3, x_1, y_1, x_2, y_2 = self.get_point_values(quad)
                ax.fill([x_0, x_1, x_2, x_3], [y_0, y_1, y_2, y_3], facecolor='none', linewidth=1, alpha=alpha, edgecolor=ecol)

        elif region.shape[0] == 3:
                x_0, y_0, x_1, y_1, x_2, y_2 = self.get_point_values(region)
                plt.fill([x_0, x_1, x_2], [y_0, y_1, y_2], color='red', alpha=alpha, edgecolor=ecol)

        elif region.shape[0] == 4:
                x_0, y_0, x_3, y_3, x_1, y_1, x_2, y_2 = self.get_point_values(region)
                plt.fill([x_0, x_1, x_2, x_3], [y_0, y_1, y_2, y_3], color='blue', linewidth=3, alpha=alpha, edgecolor=ecol)

        zoom_indices, fdist_indices = np.meshgrid(np.arange(self.nzoom), np.arange(self.nfdist), indexing='ij')

        exp_centers = self.get_point_values(np.hstack((zoom_indices.flatten()[:, None], fdist_indices.flatten()[:, None])))
        exp_centers = np.array(exp_centers).reshape(self.nzoom, self.nfdist, 2)

        rect_width = (xmax - xmin) * 0.01 / 15 * 10
        rect_height = (ymax - ymin) * 0.01

        for zoom_idx in range(self.nzoom):
            for fdist_idx in range(self.nfdist):
                center = exp_centers[zoom_idx, fdist_idx]
                rect = plt.Rectangle((center[0] - rect_width/2, center[1] - rect_height/2),
                        rect_width, rect_height,
                        linewidth=0.5, edgecolor='black', facecolor=interpolation_type_color_grid[zoom_idx, fdist_idx])
                ax.add_patch(rect)

        plt.grid(False)

        # Add legend with custom rectangles
        legend_labels = {
            (0, 1, 0): 'Bilinear Trial',
            (1, 0, 0): 'Barycentric Trial',
            (1, 1, 1): 'No Trial'
        }

        legend_handles = []
        for color, label in legend_labels.items():
            patch = plt.Rectangle((0, 0), 1, 1, facecolor=color,
                                edgecolor='black', linewidth=0.3)
            legend_handles.append((patch, label))

        handles, labels = zip(*legend_handles)
        ax.legend(handles, labels, loc='upper center',
                bbox_to_anchor=(0.5, -0.08), ncol=3,
                frameon=True, fontsize=10)

        # Plot LUT and save
        plt.xlim(input[:, 0].min(), input[:, 0].max())
        plt.ylim(input[:, 1].min(), input[:, 1].max())
        plt.xlabel("Focal length (mm)", fontsize=12)
        plt.ylabel("Focus distance (mm)", fontsize=12)
        plt.title(f"{self.lens} LUT Leave-One-Out Validation Experiment Trial Types", fontsize=16)

        plt.savefig(save_path)
        plt.show()


def get_axis_aligned_rectangles(points):
    rectangles = []
    seen = set()

    # Create a set for O(1) lookup
    point_set = set(map(tuple, points))

    # Create a mapping from points to their indices
    point_to_idx = {tuple(pt): idx for idx, pt in enumerate(points)}

    n = len(points)

    # For each pair of points, check if they can be opposite corners
    for i in range(n):
        for j in range(i+1, n):
            x1, y1 = points[i]
            x2, y2 = points[j]

            # Skip if they're on the same horizontal or vertical line
            if x1 == x2 or y1 == y2:
                continue

            # Check if the other two corners exist
            corner1 = (x1, y2)
            corner2 = (x2, y1)

            if corner1 in point_set and corner2 in point_set:
                # Found a rectangle! Get all 4 indices
                idx3 = point_to_idx[corner1]
                idx4 = point_to_idx[corner2]

                # Create a canonical form for duplicate detection (sorted)
                canonical = tuple(sorted([i, j, idx3, idx4]))

                # Only add if we haven't seen this rectangle before
                if canonical not in seen:
                    seen.add(canonical)
                    # Store with i, j first, then the other two corners
                    rect_indices = (i, j, idx3, idx4)
                    rectangles.append(rect_indices)

    return rectangles


def get_leave_one_out_error_grid_from_records(records, nzoom, nfdist, intrinsic='fx', use_percent_error=True):
    error_grid = np.zeros((nzoom, nfdist)) * np.nan

    for nz in range(0, nzoom):
        for nfd in range(0, nfdist):
            exp_name = f"zoom_{nz}_focus_distance_{nfd}"
            record = records[exp_name]

            if record["status"] != "present":
                continue

            true_intrinsic = record["intrinsics_gt"][intrinsic]
            interp = record["intrinsics_interpolated"][intrinsic]

            error_grid[nz, nfd] = np.abs(interp - true_intrinsic) / true_intrinsic if use_percent_error else np.abs(interp - true_intrinsic)

    return error_grid


def get_interpolation_type_color_grid_from_records(records, nzoom, nfdist):
    interpolation_type_color_grid = np.ones((nzoom, nfdist, 3))

    for nz in range(0, nzoom):
        for nfd in range(0, nfdist):
            exp_name = f"zoom_{nz}_focus_distance_{nfd}"
            record = records[exp_name]

            if record["interpolation_type"] == "quadrilateral":
                interpolation_type_color_grid[nz, nfd] = np.array([0, 1, 0])  # green for quadrilateral interpolation
            elif record["interpolation_type"] == "triangular":
                interpolation_type_color_grid[nz, nfd] = np.array([1, 0, 0])  # red for triangular interpolation

    return interpolation_type_color_grid


def visualize_LUT(selected_trial_path, lens, intrinsic='fx', save_dir='', n_zooms=150, n_fdists=150):
    '''
    Save LUT color gradient visualization.

    Args:
        selected_trial_path (str): path to JSON containing experiment data
        lens (str): which lens to visualize (must be in config['lenses'])
        intrinsic (str) : which intrinsic to base output on (won't matter for vis)
        save_dir (str): directory to save visualization to (will be saved as save_dir/LUT_{lens_title}.pdf)
    '''
    # Initialize LUT object
    lut = LUT(selected_trial_path, lens)

    # Create grid of points to visualize colors over
    x_vals = lut.actual_metadata_grid[:, :, 0]  # zooms
    y_vals = lut.actual_metadata_grid[:, :, 1]  # focus distances
    x_vals = x_vals[x_vals > 0]
    y_vals = y_vals[y_vals > 0]

    y_custom_max = lut.actual_metadata_grid[:, -1, 1]
    y_custom_max = y_custom_max[y_custom_max > 0].min()

    x = np.linspace(min(x_vals), max(x_vals), n_zooms)
    y = np.linspace(min(y_vals), y_custom_max, n_fdists)

    X, Y = np.meshgrid(x, y)
    input_points = np.hstack((X.flatten()[..., None], Y.flatten()[..., None]))

    _, colors, used_triangles = lut.interpolate_all(input_points, intrinsic)
    lut.visualize_regions(input_points, colors, used_triangles, n_zooms=n_zooms, n_fdists=n_fdists, show=True, alpha=1.0, ecol='black', save_path=os.path.join(save_dir, f"LUT_{lut.lens}.pdf"))


def visualize_leave_one_out_errors(focal_length_grid, focus_distance_grid, error_grid, intrinsic, lens=None, using_barycentric=None, save_path='', use_percent_error=True):
    CMAP_FOR_ERRS = 'RdYlGn_r'
    cmap = plt.get_cmap(CMAP_FOR_ERRS)

    # Set the "bad color" (NaN values color) to a specific color, e.g., 'red'
    cmap.set_bad('grey')  # You can replace 'red' with any color you want for NaN values


    fig, ax = plt.subplots(1, 1, figsize=(6, 6))
    error_grid = error_grid.T * 100 if use_percent_error else error_grid.T
    na_mask = np.isnan(error_grid)

    errors_annot = np.char.mod('%.2f', error_grid)
    errors_annot[na_mask] = 'N/A'

    xticklabels = np.array(focal_length_grid).astype(int)
    yticklabels = np.round((np.array(focus_distance_grid) / 1000), 2).astype(float)

    #plot heatmap
    sns.heatmap(error_grid, ax=ax, cmap=cmap, cbar=False, annot=errors_annot, vmin=0.0, vmax=5, fmt='',
                xticklabels=xticklabels,
                yticklabels=yticklabels,
    )
    ax.invert_yaxis()
    ax.tick_params(axis='y', rotation=0)

    # Get grid dimensions
    n_rows, n_cols = error_grid.shape

    # Add black squares at 4 corners
    corner_size = 1  # Size of each corner square
    corners = [
        (0, 0),                          # Top-left
        (n_cols - corner_size, 0),       # Top-right
        (0, n_rows - corner_size),       # Bottom-left
        (n_cols - corner_size, n_rows - corner_size)  # Bottom-right
    ]

    for x, y in corners:
        rect = plt.Rectangle((x, y), corner_size, corner_size,
                            facecolor='black', edgecolor='black', linewidth=0)
        ax.add_patch(rect)

    title = f'{intrinsic} % Error for {lens} LUT Leave-One-Out LUT Validation Experiments' if use_percent_error \
        else f'{intrinsic} Absolute Error for {lens} LUT Leave-One-Out LUT Validation Experiments'
    ax.set_title(title)
    ax.set_xlabel('Lens Focal Length (mm)')
    ax.set_ylabel('Focus Distance (m)')

    # Mark barycentric trials
    using_barycentric
    x_coords, y_coords = np.where(using_barycentric)

    for x_coord, y_coord in zip(x_coords, y_coords):
        rect_x = [x_coord, x_coord, x_coord + 1, x_coord + 1, x_coord]
        rect_y = [y_coord, y_coord + 1, y_coord + 1, y_coord, y_coord]

        ax.plot(rect_x, rect_y, color='cyan', linewidth=3)

    plt.savefig(save_path, bbox_inches="tight")
    plt.close()

    # Print out stats
    print(f'median error for {intrinsic}: {np.median(error_grid[~na_mask])}')


def run_leave_one_out_experiment(selected_trial_path, lens, save_dir='', records_dir=None, intrinsic_errors_dir=None, n_zooms=150, n_fdists=150):
    '''
    Run leave one out validation experiment.

    Args:
        selected_trial_path (str): path to JSON containing experiment data
        lens (str): which lens to visualize (must be in config['lenses'])
        intrinsic (str) : which intrinsic to base output on (won't matter for vis)
        save_dir (str): directory to save leave-one-out visualizations
        records_dir (str): directory to save machine-readable leave-one-out records
        intrinsic_errors_dir (str): directory to save per-intrinsic leave-one-out error visualizations
    '''
    if records_dir is None:
        records_dir = save_dir
    if intrinsic_errors_dir is None:
        intrinsic_errors_dir = save_dir

    for directory in [save_dir, records_dir, intrinsic_errors_dir]:
        if directory != '':
            os.makedirs(directory, exist_ok=True)

    # Initialize LUT object
    lut = LUT(selected_trial_path, lens)

    # Save leave-one-out value records
    leave_one_out_records = lut.get_leave_one_out_records()
    leave_one_out_json_path = os.path.join(records_dir, f"{lut.lens}_leave_one_out_values.json")
    with open(leave_one_out_json_path, "w") as f:
        json.dump(leave_one_out_records, f, indent=4)

    # Run experiments
    error_grids = []
    for intrinsic in lut.intrinsics_ordering:
        use_percent_error = (intrinsic in ['fx', 'fy', 'cx', 'cy'])

        error_grid = get_leave_one_out_error_grid_from_records(leave_one_out_records, lut.nzoom, lut.nfdist, intrinsic=intrinsic, use_percent_error=use_percent_error)
        error_grids.append(error_grid)

    interpolation_type_color_grid = get_interpolation_type_color_grid_from_records(leave_one_out_records, lut.nzoom, lut.nfdist)

    ### Visualize interpolation scheme
    # Create grid of points to visualize colors over
    x_vals = lut.actual_metadata_grid[:, :, 0]  # zooms
    y_vals = lut.actual_metadata_grid[:, :, 1]  # focus distances
    x_vals = x_vals[x_vals > 0]
    y_vals = y_vals[y_vals > 0]

    y_custom_max = lut.actual_metadata_grid[:, -1, 1]
    y_custom_max = y_custom_max[y_custom_max > 0].min()

    x = np.linspace(min(x_vals), max(x_vals), n_zooms)
    y = np.linspace(min(y_vals), y_custom_max, n_fdists)

    X, Y = np.meshgrid(x, y)
    input_points = np.hstack((X.flatten()[..., None], Y.flatten()[..., None]))

    _, colors, used_triangles = lut.interpolate_all(input_points, intrinsic)
    colors = colors * 0 + 1

    lut.visualize_leave_one_out_experiment_trial_types(input_points, colors, used_triangles, interpolation_type_color_grid=interpolation_type_color_grid, n_zooms=n_zooms, n_fdists=n_fdists, show=True, alpha=1.0, ecol='black', save_path=os.path.join(save_dir, f"{lut.lens}_trial_types.pdf"))
    using_barycentric = np.all(interpolation_type_color_grid == np.array([1, 0, 0]), axis=2)

    for error_grid, intrinsic in zip(error_grids, lut.intrinsics_ordering):
        use_percent_error = (intrinsic in ['fx', 'fy', 'cx', 'cy'])

        visualize_leave_one_out_errors(lut.approx_zooms, lut.approx_fds, error_grid, intrinsic, lens, using_barycentric=using_barycentric, save_path=os.path.join(intrinsic_errors_dir, f"{lut.lens}_leave_one_out_{intrinsic}_errors.pdf"), use_percent_error=use_percent_error)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lens type and real/synthetic flag parser")
    parser.add_argument("--lens", type=str, choices=config['lenses'].keys(), required=True)
    parser.add_argument("--selected-trials-dir", type=str, help="Specify path to folder containing selected trials .json files.", default=config['lut_creation']['SELECTED_TRIALS_DIR'])
    parser.add_argument("--output-path", type=str, help="Specify root path to save visualizations.", default='outputs')
    parser.add_argument("--artifact-path", type=str, help="Specify root path to save machine-readable artifacts.", default='artifacts')
    args = parser.parse_args()

    lens = args.lens
    selected_trials_dir = args.selected_trials_dir
    selected_trial_path = f'{selected_trials_dir}/{lens}_selected_trials.json'
    output_path = args.output_path
    artifact_path = args.artifact_path

    lut_output_path = os.path.join(output_path, "lut", lens)
    leave_one_out_output_path = os.path.join(lut_output_path, "leave_one_out")
    leave_one_out_intrinsic_errors_path = os.path.join(leave_one_out_output_path, "intrinsic_errors")
    leave_one_out_records_path = os.path.join(artifact_path, "lut_leave_one_out_records")

    os.makedirs(lut_output_path, exist_ok=True)
    os.makedirs(leave_one_out_output_path, exist_ok=True)
    os.makedirs(leave_one_out_intrinsic_errors_path, exist_ok=True)
    os.makedirs(leave_one_out_records_path, exist_ok=True)

    # Visualize LUT interpolation
    visualize_LUT(selected_trial_path, lens, save_dir=lut_output_path, n_zooms=150, n_fdists=150)

    # Run leave-one-out cross-validation experiment on LUT
    run_leave_one_out_experiment(
        selected_trial_path,
        lens,
        save_dir=leave_one_out_output_path,
        records_dir=leave_one_out_records_path,
        intrinsic_errors_dir=leave_one_out_intrinsic_errors_path,
    )
