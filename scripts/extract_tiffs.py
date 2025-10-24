import os
import subprocess
import sys


def extract_tiffs(input_video, output_dir, start_number=0, fps=None):
    # Validate input video exists
    if not os.path.exists(input_video):
        raise FileNotFoundError(f"Input video not found: {input_video}")
    
    # Make output directory
    os.makedirs(output_dir, exist_ok=True)
    
    # Determine output pattern based on format
    output_pattern = os.path.join(output_dir, f'%07d.tiff')
    
    # Build FFmpeg command
    cmd = [
        'ffmpeg',
        "-vsync", "0",                        # prevents frame drops / duplicates
        '-i', input_video,
        '-start_number', str(start_number),
    ]
    
    # Add FPS filter if specified
    if fps is not None:
        cmd.extend(['-vf', f'fps={fps}'])
    
    # Add quality/compression settings based on format
    cmd.extend(['-pix_fmt', 'rgb24'])  # TIFF format
    
    cmd.append(output_pattern)
    
    print(f"Extracting frames from: {input_video}")
    print(f"Output directory: {output_dir}")
    print(f"Command: {' '.join(cmd)}")
    
    # Run FFmpeg
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(result.stderr)  # FFmpeg outputs progress to stderr
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg error: {e.stderr}")
        sys.exit(1)
    
    # Count extracted frames
    frame_count = len([f for f in os.listdir(output_dir) if f.endswith(f'.tiff')])
    print(f"✓ Extracted {frame_count} frames to: {output_dir}")
    
    # Calculate total size
    total_size_gb = sum(
        os.path.getsize(os.path.join(output_dir, f)) 
        for f in os.listdir(output_dir) 
        if f.endswith(f'.tiff')
    ) / (1024**3)
    print(f"✓ Total size: {total_size_gb:.2f} GB")
