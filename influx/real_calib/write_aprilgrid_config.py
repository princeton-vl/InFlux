import yaml

def get_aprilgrid_config(board_size):
    # extra behavior for 1.6, 3.2, 6.4
    assert board_size in [0.1, 0.2, 0.4, 0.8, 1.6, 3.2, 6.4], "Unsupported board size"
    tag_size_fac = 50 / 3  # eg 0.4 / tag_size_fac = 0.024
    if board_size in [0.1, 0.2, 0.4, 0.8]:
        return {
            "tagCols": 11,
            "tagRows": 8,
            "tagSpacing": 0.3,
            "tagSize": board_size / tag_size_fac,
            "target_type": "aprilgrid"
        }
    elif board_size == 1.6:
        return {
            "tagCols": 5,
            "tagRows": 4,
            "tagSpacing": 0.3,
            "tagSize": board_size / tag_size_fac,
            "target_type": "aprilgrid"
        }
    elif board_size == 3.2:
        return {
            "tagCols": 11,
            "tagRows": 8,
            "tagSpacing": 0.3,
            "tagSize": board_size / tag_size_fac,
            "target_type": "aprilgrid"
        }
    elif board_size == 6.4:  # TODO: update this, we are not using checkerboard
        return {
            "tagCols": 6,
            "tagRows": 4,
            "tagSpacing": 0.3,
            "tagSize": board_size / tag_size_fac,
            "target_type": "aprilgrid"
        }

def write_config(target_path, april_board_size):
    # Generate a target.yaml based on inputs
    calib_config = get_aprilgrid_config(april_board_size)

    with open(target_path, 'w') as file:
        yaml.dump(calib_config, file)
