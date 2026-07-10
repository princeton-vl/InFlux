import os
import subprocess
import tarfile


def extract_files(scene_dir, split_dir, config_path, tmp_dir, remove_archives=True):
    scene = os.path.basename(scene_dir)
    tar_archives, mkv_archives = _find_archives(scene_dir)

    if not tar_archives and not mkv_archives:
        return

    print(f"Extracting {scene}...")

    for archive in tar_archives:
        _extract_tar(archive, remove_archive=remove_archives)

    if mkv_archives:
        _unpack_scene_mkvs(scene, split_dir, config_path, tmp_dir)
        if remove_archives:
            for archive in mkv_archives:
                os.remove(archive)
                print(f"Removed archive: {archive}")


def _find_archives(scene_dir):
    tar_archives = []
    mkv_archives = []
    for root, _, files in os.walk(scene_dir):
        for name in sorted(files):
            path = os.path.join(root, name)
            if name.endswith(".tar.gz"):
                tar_archives.append(path)
            elif name.endswith(".mkv"):
                mkv_archives.append(path)
    return tar_archives, mkv_archives


def _unpack_scene_mkvs(scene, split_dir, config_path, tmp_dir):
    cmd = [
        "cvdpack",
        "unpack",
        "--input",
        split_dir,
        "--output",
        split_dir,
        "--config",
        config_path,
        "--tmp_folder",
        tmp_dir,
        "--subset",
        f"scene={scene}",
    ]

    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError as e:
        raise RuntimeError(
            "cvdpack not found. Install with: pip install cvdpack"
        ) from e
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"cvdpack unpack failed for {scene} (exit code {e.returncode})"
        ) from e


def _extract_tar(input_tar, remove_archive=True):
    if not os.path.exists(input_tar):
        raise FileNotFoundError(f"Input archive not found: {input_tar}")

    archive_dir = os.path.dirname(input_tar)
    if os.path.basename(input_tar).endswith("_visual_maps.tar.gz"):
        output_dir = os.path.dirname(archive_dir)
    else:
        output_dir = archive_dir

    os.makedirs(output_dir, exist_ok=True)

    print(f"Extracting archive: {input_tar}")

    with tarfile.open(input_tar, "r:gz") as tar:
        tar.extractall(path=output_dir)

    if remove_archive:
        os.remove(input_tar)
        print(f"Removed archive: {input_tar}")