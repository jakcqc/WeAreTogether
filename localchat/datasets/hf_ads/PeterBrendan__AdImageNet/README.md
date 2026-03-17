---
configs:
- config_name: default
  data_files:
  - split: train
    path: data/train-*
dataset_info:
  features:
  - name: image
    dtype: image
  - name: text
    dtype: string
  - name: dimensions
    dtype: string
  splits:
  - name: train
    num_bytes: 684595217.53
    num_examples: 9003
  download_size: 682372973
  dataset_size: 684595217.53
license: mit
language:
- en
pretty_name: AdImageNet - Programmatic Ad Creatives
---
# Dataset Summary

The AdImageNet dataset contains 9,003 samples of online programmatic ad creatives along with their ad sizes and extracted creative text. Just as ImageNet revolutionized computer vision, AdImageNet aims to serve as a transformative resource for the field of advertising creatives. The dataset includes various ad sizes, such as (300, 250), (728, 90), (970, 250), (300, 600), (160, 600), (970, 90), (336, 280), and (320, 50). This dataset was curated from a larger collection of programmatic creative images hosted by [Project300x250.com](https://www.project300x250.com). It is intended to support the development and evaluation of AI models for tasks related to ad creative generation and understanding.

# Supported Tasks

This dataset is suitable for a range of tasks, including text generation, language modeling, and text augmentation. Researchers and developers can use this dataset to train and fine-tune AI models for generating creative ad copy. Inspired by ImageNet, AdImageNet opens doors to exploring alternatives to proprietary advertising platforms like Google and Meta. By promoting open solutions in the advertising domain, this dataset supports the growth of independent advertising technologies.

# Languages

The dataset primarily consists of English language text.

# Dataset Structure

## Data Fields

The dataset contains the following fields:
- `file_name`: The name of the image file.
- `text`: The extracted text from the programmatic ad creative.
- `dimensions`: The dimensions (ad size) of the creative.

## Data Splits

The data is provided as a single whole dataset and is not split into separate subsets.

# Dataset Creation

## Curation Rationale

AdImageNet was meticulously curated to provide a valuable resource for researchers and developers in the field of advertising creatives. Drawing inspiration from ImageNet's impact on computer vision, AdImageNet aims to revolutionize the advertising domain by offering a diverse collection of advertising creatives. The dataset encourages the development of open-source alternatives to dominant advertising platforms like Google and Meta. By fostering open solutions, AdImageNet promotes creativity and innovation in advertising.

## Source Data

The data is derived from a comprehensive collection of programmatic creative images hosted by [Project300x250.com](https://www.project300x250.com). The creative text was extracted from each image using Google's Vision API.

# Dataset Use

## Use Cases

AdImageNet can serve a variety of purposes, including language understanding, natural language processing, machine learning model training, and performance evaluation. Researchers and practitioners can use this dataset to fine-tune AI models that generate unique ad copy based on programmatic ad text. These models offer a starting point for developing effective marketing content and encouraging creativity in advertising.

## Usage Caveats

As this dataset represents a sampled subset, it is advisable to regularly check for updates and improvements. The full data set is +19K creative images. Researchers can also reach out to the dataset author for access to the complete dataset available at [Project300x250.com](https://www.project300x250.com).