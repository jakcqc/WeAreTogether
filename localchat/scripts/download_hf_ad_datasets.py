from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pandas as pd
from huggingface_hub import snapshot_download
from huggingface_hub.errors import GatedRepoError
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = ROOT / "datasets" / "hf_ads"
STATIC_AD_ROOT = ROOT / "localchat" / "static" / "dataset-ads"

PUBLIC_DATASET = "superfine/advertising-banner-generation"
GATED_DATASET = "PeterBrendan/AdImageNet"


def main() -> None:
    DATASET_ROOT.mkdir(parents=True, exist_ok=True)
    STATIC_AD_ROOT.mkdir(parents=True, exist_ok=True)

    public_dir = download_dataset(PUBLIC_DATASET)
    gated_dir = DATASET_ROOT / GATED_DATASET.replace("/", "__")
    try:
        download_dataset(GATED_DATASET)
    except GatedRepoError as exc:
        gated_dir.mkdir(parents=True, exist_ok=True)
        (gated_dir / "ACCESS_REQUIRED.txt").write_text(
            "Access to PeterBrendan/AdImageNet is gated on Hugging Face.\n"
            "Log in with a Hugging Face token that has been approved for this dataset,\n"
            "then rerun scripts/download_hf_ad_datasets.py.\n"
            f"Last error: {exc}\n",
            encoding="utf-8",
        )

    extract_public_samples(public_dir)


def download_dataset(repo_id: str) -> Path:
    target = DATASET_ROOT / repo_id.replace("/", "__")
    snapshot_download(repo_id=repo_id, repo_type="dataset", local_dir=target)
    return target


def extract_public_samples(dataset_dir: Path) -> None:
    extract_image(
        dataset_dir / "data" / "train-00000-of-00001.parquet",
        row_index=0,
        output_name="superfine-train-hero.jpg",
    )
    extract_image(
        dataset_dir / "data" / "test-00000-of-00001.parquet",
        row_index=0,
        output_name="superfine-test-hero.jpg",
    )


def extract_image(parquet_path: Path, *, row_index: int, output_name: str) -> None:
    frame = pd.read_parquet(parquet_path)
    record = frame.iloc[row_index]["image"]
    image_bytes = record["bytes"]
    image = Image.open(BytesIO(image_bytes)).convert("RGB")
    image.save(STATIC_AD_ROOT / output_name, quality=92)


if __name__ == "__main__":
    main()
