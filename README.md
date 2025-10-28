<p align="center">

  <h1 align="center">InFlux: A Benchmark for Self-Calibration of Dynamic Intrinsics of Video Cameras</h1>
  <p align="center">
    <a href="https://www.linkedin.com/in/erlian"><strong>Erich Liang</strong></a>
    ·
    <a href="https://www.linkedin.com/in/romabhattacharjee"><strong>Roma Bhattacharjee*</strong></a>
    ·
    <a href="https://www.linkedin.com/in/sreemanti-dey-3022281b7"><strong>Sreemanti Dey*</strong></a>
    ·
    <a href="https://www.linkedin.com/in/rafael-m-233a94386/"><strong>Rafael Moschopoulos</strong></a>
    ·
    <a href="https://www.linkedin.com/in/caitlin-wang-8527a2231"><strong>Caitlin Wang</strong></a>
    ·
    <a href="https://www.michelliao.com/"><strong>Michel Liao</strong></a>
    ·
    <a href="https://www.linkedin.com/in/grace-tan-00449132a"><strong>Grace Tan</strong></a>
    ·
    <a href="https://www.linkedin.com/in/andrew-wang-048b89233"><strong>Andrew Wang</strong></a>
    ·
    <a href="https://kkayan.com/"><strong>Karhan Kayan</strong></a>
    ·
    <a href="https://stamatisalex.github.io/"><strong>Stamatis Alexandropoulos</strong></a>
    ·
    <a href="https://www.cs.princeton.edu/~jiadeng/"><strong>Jia Deng</strong></a>
  </p>
  <p align="center">
    (*equal contribution)
  </p>
  <h4 align="center">
  Princeton University    
  </h4>
</p>

<h3 align="center"><a href="https://influx.cs.princeton.edu/">Website</a> | <a href="https://arxiv.org/abs/2510.23589">Paper</a> </a></h3>

<p align="center">
  <a href="">
    <img src="./media/main_fig.png" alt="Logo" width="98%">
  </a>
</p>


## Citation
If you use our benchmark, data, or method in your work, please cite our paper:
```
@misc{liang2025influx,
      title={InFlux: A Benchmark for Self-Calibration of Dynamic Intrinsics of Video Cameras}, 
      author={Erich Liang and Roma Bhattacharjee and Sreemanti Dey and Rafael Moschopoulos and Caitlin Wang and Michel Liao and Grace Tan and Andrew Wang and Karhan Kayan and Stamatis Alexandropoulos and Jia Deng},
      year={2025},
      eprint={2510.23589},
      archivePrefix={arXiv},
      primaryClass={cs.CV},
      url={https://arxiv.org/abs/2510.23589}, 
}
```

## Downloading the Dataset
You can download our dataset from [Hugging Face](https://huggingface.co/datasets/princeton-vl/InFlux). Please follow the instructions [here](docs/README_download.md).

To view the videos locally, we recommend using VLC Media Viewer, which can be downloaded [here](https://www.videolan.org/).

## Evaluating Your Camera Intrinsics Prediction Method

### Installation

For basic functionality (submitting results):
```bash 
conda create --name influx python=3.10
conda activate influx
pip install .
```

### Submission Format

First, generate a single submission json with the following format:

**`submission.json`**:

```
{
    "submission_metadata": {
        "method_name": "your_method_name",
        "intrinsics_type": "rad-tan"   // or "mei"
    },
    "test_video1": {
        "0": {                         // Frame index as a string
            "fx": 0.0,
            "fy": 0.0,
            "cx": 0.0,
            "cy": 0.0,
            "k1": 0.0,
            "k2": 0.0,
            "p1": 0.0,
            "p2": 0.0
        },
        "1": {
            "fx": 0.0,
            "fy": 0.0,
            "cx": 0.0,
            "cy": 0.0,
            "k1": 0.0,
            "k2": 0.0,
            "p1": 0.0,
            "p2": 0.0
        }
        // ... continue for all frames in the test video
    },
    "test_video2": {
        // same format for other test videos
    }
}
```
**Notes**:
- All frame indices must be strings (e.g., "0", "1", "2", …). Do not use leading zeros.
- `intrinsics_type` must be either "rad-tan" or "mei".
- If your method uses a different intrinsics type, please contact us at influxbenchmark@gmail.com

To generate an example submission json that is formatted correctly but needs values filled in, you can run the following command:
```
influx-generate-sample \
    --intr-type <rad-tan|mei> \
    --output <path/to/output_file.json>
```

### Submit Your Results

Submit your predictions to the evaluation server using the command below. Replace the placeholders:

```bash
influx-upload \
    --email your_email \
    --path path_to_your_submission_json \
    --method_name your_method_name
```

**Important**: the `--method_name` argument must exactly match the `method_name` specified in the `submission_metadata` section of your JSON file.

After submission, a validation function will check your JSON file. To ensure it passes:
- Avoid special characters or spaces in the **file name** and **method name**.
- Include **all test videos and frames** in your submission.
- Provide **all required intrinsics** for the specified `intrinsics_type` for every frame.
- Ensure that `fx`, `fy`, `cx`, and `cy` values are non-negative.

### After Submission

Upon submission, you will receive a unique submission ID, which serves as the identifier for your submission. Results are typically emailed within a few hours. Please note that each email user may upload only three submissions every seven days.

### Making Your Submission Public

To make your submission public, run:

```bash
influx-make-public \
    --id submission_id \
    --email your_email \
    --anonymous False \
    --method_name your_method_name \
    --publication "your publication name" \
    --url_publication "https://your_publication" \
    --url_code "https://your_code" \
```

You may set `"Anonymous"` as the publication name if the work is under review. The `url_publication`, `url_code` fields are optional.
