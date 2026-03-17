---
dataset_info:
  features:
  - name: image
    dtype: image
  splits:
  - name: train
    num_bytes: 86418717.13
    num_examples: 1362
  - name: test
    num_bytes: 481468.0
    num_examples: 3
  download_size: 84068700
  dataset_size: 86900185.13
configs:
- config_name: default
  data_files:
  - split: train
    path: data/train-*
  - split: test
    path: data/test-*
---
