<h1 align="center">InFlux and InFlux++: Real and Synthetic Data for Estimating Dynamic Camera Intrinsics</h1>

<p align="center">
  <a href="https://influx.cs.princeton.edu/"><strong>Website</strong></a>
  ·
  <a href="#getting-started"><strong>Getting Started</strong></a>
  ·
  <a href="https://arxiv.org/abs/2607.05389"><strong>InFlux++ Paper</strong></a>
  ·
  <a href="https://arxiv.org/abs/2510.23589"><strong>InFlux Paper</strong></a>
  ·
  <a href="https://huggingface.co/datasets/princeton-vl/InFlux-Real"><strong>InFlux-Real</strong></a>
  ·
  <a href="https://huggingface.co/datasets/princeton-vl/InFlux-Synth"><strong>InFlux-Synth</strong></a>
  ·
  <a href="https://influx.cs.princeton.edu/leaderboard"><strong>Leaderboard</strong></a>
</p>

<p align="center">
  <a href="https://arxiv.org/abs/2607.05389">
    <img src="./media/influx_pp_teaser.gif" alt="InFlux++ overview" width="98%">
  </a>
</p>

## Overview

The InFlux project provides a **unified real-world benchmark**, **synthetic training data**, and a **live evaluation leaderboard** for estimating camera intrinsics in videos with dynamic camera intrinsics.

**InFlux [NeurIPS 2025]** established the first real-world benchmark with per-frame ground truth camera intrinsics for real-world videos with dynamic intrinsics. It comprises **143K+ annotated frames from 386 high-resolution videos**.

**InFlux++ [ECCV 2026]** builds on InFlux through two new components. **InFlux++ Real** extends the real-world benchmark with **514K+ newly captured frames from 334 high-resolution videos**, substantially broadening the diversity of scenes, subject motion, and camera trajectories. **InFlux++ Synth** introduces a procedurally generated synthetic dataset with **441K+ annotated frames from 1,841 videos** for training dynamic camera intrinsics prediction models. Every synthetic video includes per-frame ground truth camera intrinsics and camera pose, and a subset additionally includes depth and surface normals.

## Main Contributions

| Work | Main contributions | Public releases |
|---|---|---|
| **[InFlux](https://proceedings.neurips.cc/paper_files/paper/2025/file/8a8eca190088852067b4e8cc1b907122-Paper-Datasets_and_Benchmarks_Track.pdf)** | <ul><li>Introduced the first real-world benchmark with per-frame ground truth camera intrinsics for videos with dynamic intrinsics</li><li>Extended Kalibr to improve calibration accuracy and robustness</li></ul> | <ul><li>The <code>influx/</code> partition of <a href="https://huggingface.co/datasets/princeton-vl/InFlux-Real">InFlux-Real</a></li><li><a href="https://github.com/princeton-vl/InFlux/tree/main/third_party/kalibr">Kalibr extensions</a></li></ul> |
| **[InFlux++](https://arxiv.org/abs/2607.05389)** | <ul><li>Introduced InFlux++ Real, expanding the diversity of real-world scenes, subject motion, and camera trajectories</li><li>Introduced InFlux++ Synth, which contains synthetic training videos with per-frame ground truth intrinsics, camera pose, and additional annotations</li></ul> | <ul><li>The <code>influx_pp_real/</code> partition of <a href="https://huggingface.co/datasets/princeton-vl/InFlux-Real">InFlux-Real</a></li><li><a href="https://huggingface.co/datasets/princeton-vl/InFlux-Synth">InFlux-Synth</a></li><li><a href="https://github.com/princeton-vl/InFlux">InFlux-Synth data loader</a></li></ul> |

## Publications and Citation

If you find our real-world benchmark, synthetic training data, or code useful, please cite the corresponding paper. If you use the complete InFlux-Real release or report results on both the **`influx/`** and **`influx_pp_real/`** benchmark partitions, please cite both InFlux and InFlux++.

<h3 align="center">
  <a href="https://arxiv.org/abs/2607.05389">InFlux++: Real and Synthetic Data for Estimating Dynamic Camera Intrinsics</a>
</h3>

<p align="center">
  <a href="https://erichliang.github.io/">Erich Liang</a>
  ·
  <a href="http://zh1kang.com/">Caleb Kha-Uong<sup>*</sup></a>
  ·
  <a href="https://www.linkedin.com/in/chinmaya-saran">Chinmaya Saran<sup>*</sup></a>
  ·
  <a href="https://www.linkedin.com/in/sreemanti-dey-3022281b7">Sreemanti Dey<sup>*</sup></a>
  ·
  <a href="https://www.linkedin.com/in/david-liu-71398523a">David W. Liu</a>
  ·
  <a href="https://www.linkedin.com/in/harry-ouyang">Junhan Ouyang</a>
  ·
  <a href="https://www.linkedin.com/in/benjamin-zhou-234344268">Benjamin Zhou</a>
  ·
  <a href="https://www.cs.princeton.edu/~jiadeng/">Jia Deng</a>
</p>

<p align="center">
  <sup>*</sup> Equal contribution
</p>

<p align="center">
  <em>European Conference on Computer Vision (ECCV), 2026</em>
</p>

```bibtex
@misc{liang2026influxrealsyntheticdata,
    title = {InFlux++: Real and Synthetic Data for Estimating Dynamic Camera Intrinsics},
    author = {Erich Liang and Caleb Kha-Uong and Chinmaya Saran and Sreemanti Dey and David W. Liu and Junhan Ouyang and Benjamin Zhou and Jia Deng},
    year = {2026},
    eprint = {2607.05389},
    archivePrefix = {arXiv},
    primaryClass = {cs.CV},
    url = {https://arxiv.org/abs/2607.05389}
}
```

<h3 align="center">
  <a href="https://proceedings.neurips.cc/paper_files/paper/2025/file/8a8eca190088852067b4e8cc1b907122-Paper-Datasets_and_Benchmarks_Track.pdf">InFlux: A Benchmark for Self-Calibration of Dynamic Intrinsics of Video Cameras</a>
</h3>

<p align="center">
  <a href="https://erichliang.github.io/">Erich Liang</a>
  ·
  <a href="https://www.linkedin.com/in/romabhattacharjee">Roma Bhattacharjee<sup>*</sup></a>
  ·
  <a href="https://www.linkedin.com/in/sreemanti-dey-3022281b7">Sreemanti Dey<sup>*</sup></a>
  ·
  <a href="https://www.linkedin.com/in/rafael-m-233a94386/">Rafael Moschopoulos</a>
  ·
  <a href="https://www.linkedin.com/in/caitlin-wang-8527a2231">Caitlin Wang</a>
  ·
  <a href="https://www.michelliao.com/">Michel Liao</a>
  ·
  <a href="https://www.linkedin.com/in/grace-tan-00449132a">Grace Tan</a>
  ·
  <a href="https://www.linkedin.com/in/andrew-wang-048b89233">Andrew Wang</a>
  ·
  <a href="https://kkayan.com/">Karhan Kayan</a>
  ·
  <a href="https://stamatisalex.github.io/">Stamatis Alexandropoulos</a>
  ·
  <a href="https://www.cs.princeton.edu/~jiadeng/">Jia Deng</a>
</p>

<p align="center">
  <sup>*</sup> Equal contribution
</p>

<p align="center">
  <em>Neural Information Processing Systems, Datasets and Benchmarks Track (NeurIPS), 2025</em>
</p>

<p align="center">
  <a href="https://arxiv.org/abs/2510.23589">
    <img src="./media/main_fig.png" alt="InFlux benchmark overview" width="98%">
  </a>
</p>

```bibtex
@inproceedings{liang2025influx,
    author = {Liang, Erich and Bhattacharjee, Roma and Dey, Sreemanti and Moschopoulos, Rafael and Wang, Caitlin and Liao, Michel and Tan, Grace and Wang, Andrew and Kayan, Karhan and Alexandropoulos, Stamatis and Deng, Jia},
    booktitle = {Advances in Neural Information Processing Systems},
    editor = {D. Belgrave and C. Zhang and H. Lin and R. Pascanu and P. Koniusz and M. Ghassemi and N. Chen},
    pages = {},
    publisher = {Curran Associates, Inc.},
    title = {InFlux: A Benchmark for Self-Calibration of Dynamic Intrinsics of Video Cameras},
    url = {https://proceedings.neurips.cc/paper_files/paper/2025/file/8a8eca190088852067b4e8cc1b907122-Paper-Datasets_and_Benchmarks_Track.pdf},
    volume = {38},
    year = {2025}
}
```

## Getting Started

### Install the Repository Utilities

We recommend creating a dedicated Conda environment named `influx` with Python 3.11:

```bash
conda create --name influx python=3.11
conda activate influx
```

From the repository root, install the package in editable mode:

```bash
pip install -e .
```

This installs the Python dependencies and command-line utilities used for downloading data, extracting files, and submitting benchmark predictions. Dataset-specific requirements and commands are documented in the guides linked below.

[Download Overview](docs/README_download.md) ·
[Evaluation and Submission](docs/README_evaluation.md)

### InFlux-Real — Real-World Benchmark

[InFlux-Real](https://huggingface.co/datasets/princeton-vl/InFlux-Real) is the unified real-world benchmark release for the project. It contains **657,648 annotated frames from 720 high-resolution videos** across two benchmark partitions:

- **`influx/`** contains the original InFlux benchmark.
- **`influx_pp_real/`** contains InFlux++ Real, a real-world benchmark extension of InFlux.

Ground truth camera intrinsics are released for the validation splits. Ground truth for the test splits is withheld for evaluation through the submission server.

See the dataset card, documentation, and live leaderboard linked below for download, extraction, annotation, evaluation, and submission information.

[Dataset Card](https://huggingface.co/datasets/princeton-vl/InFlux-Real) ·
[Download and Extraction](docs/README_download_real.md) ·
[Evaluation and Submission](docs/README_evaluation.md) ·
[Live Leaderboard](https://influx.cs.princeton.edu/leaderboard)

### InFlux-Synth — Synthetic Dataset

[InFlux-Synth](https://huggingface.co/datasets/princeton-vl/InFlux-Synth) is the large-scale synthetic dataset introduced as InFlux++ Synth. It contains **441,840 annotated frames from 1,841 procedurally generated videos**.

Every video includes per-frame ground truth camera intrinsics and camera pose. Selected scenes additionally include depth and surface normals. The released RGB images are undistorted, and the official data loader supports applying lens distortion during training as data augmentation.

InFlux-Synth is intended primarily for training and finetuning models before real-world validation and evaluation on InFlux-Real.

See the dataset card and documentation linked below for download, extraction, annotation, and data-loading information.

[Dataset Card](https://huggingface.co/datasets/princeton-vl/InFlux-Synth) ·
[Download and Extraction](docs/README_download_synth.md) ·
[Data Loader](docs/README_dataloader.md)

Detailed dataset structures, annotation schemas, coordinate conventions, and storage requirements are maintained in the corresponding Hugging Face dataset cards.

## Contact

For questions about the data, real-world benchmark, or evaluation server, contact:

`influxbenchmark@gmail.com`