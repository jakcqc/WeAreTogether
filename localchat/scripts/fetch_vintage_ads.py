from __future__ import annotations

import argparse
import json
import re
import socket
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

CDX_API = "https://web.archive.org/cdx/search/cdx"
WAYBACK_RAW = "https://web.archive.org/web/{timestamp}id_/{original}"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "downloads" / "vintage_ads"
USER_AGENT = "localchat-vintage-ads/1.0"
QUERY_TIMEOUT_SECONDS = 20
DOWNLOAD_TIMEOUT_SECONDS = 10

SEED_QUERIES = (
    {
        "category": "ad-network",
        "pattern": "*.fastclick.net/*",
        "mimetypes": ("image/gif", "image/jpeg", "image/png"),
    },
    {
        "category": "ad-network",
        "pattern": "*.tribalfusion.com/*",
        "mimetypes": ("image/gif", "image/jpeg", "image/png"),
    },
    {
        "category": "ad-network",
        "pattern": "*.valueclick.net/*",
        "mimetypes": ("image/gif", "image/jpeg", "image/png"),
    },
    {
        "category": "ad-network",
        "pattern": "*.advertising.com/*",
        "mimetypes": ("image/gif", "image/jpeg", "image/png"),
    },
    {
        "category": "ad-network",
        "pattern": "*.burstnet.com/*",
        "mimetypes": ("image/gif", "image/jpeg", "image/png"),
    },
    {
        "category": "ad-network",
        "pattern": "*.linkexchange.com/*",
        "mimetypes": ("image/gif", "image/jpeg", "image/png"),
    },
    {
        "category": "ad-network",
        "pattern": "*.websponsors.com/*",
        "mimetypes": ("image/gif", "image/jpeg", "image/png"),
    },
    {
        "category": "casino",
        "pattern": "*.partycasino.com/*",
        "mimetypes": ("image/gif", "image/jpeg", "image/png"),
    },
    {
        "category": "casino",
        "pattern": "*.888casino.com/*",
        "mimetypes": ("image/gif", "image/jpeg", "image/png"),
    },
    {
        "category": "casino",
        "pattern": "*.casino-on-net.com/*",
        "mimetypes": ("image/gif", "image/jpeg", "image/png"),
    },
    {
        "category": "casino",
        "pattern": "*.intercasino.com/*",
        "mimetypes": ("image/gif", "image/jpeg", "image/png"),
    },
    {
        "category": "spicy",
        "pattern": "*.adultfriendfinder.com/*",
        "mimetypes": ("image/gif", "image/jpeg", "image/png"),
    },
    {
        "category": "spicy",
        "pattern": "*.friendfinder.com/*",
        "mimetypes": ("image/gif", "image/jpeg", "image/png"),
    },
    {
        "category": "spicy",
        "pattern": "*.passion.com/*",
        "mimetypes": ("image/gif", "image/jpeg", "image/png"),
    },
    {
        "category": "ad-network",
        "pattern": "*.doubleclick.net/*",
        "mimetypes": ("image/gif", "image/jpeg", "image/png"),
    },
    {
        "category": "sweepstakes",
        "pattern": "*.cashfiesta.com/*",
        "mimetypes": ("image/gif", "image/jpeg", "image/png"),
    },
)

EXTENSIONS = {
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
}

CURATED_CAPTURES = (
    {"category": "ad-network", "timestamp": "20070424210532", "original": "http://www.fastclick.net/images/background.gif", "mimetype": "image/gif"},
    {"category": "ad-network", "timestamp": "20070424210707", "original": "http://www.fastclick.net/images/header.gif", "mimetype": "image/gif"},
    {"category": "ad-network", "timestamp": "20070424210532", "original": "http://www.fastclick.net/images/home/advertisers_lable.gif", "mimetype": "image/gif"},
    {"category": "ad-network", "timestamp": "20070424210532", "original": "http://www.fastclick.net/images/home/agencies_lable.gif", "mimetype": "image/gif"},
    {"category": "ad-network", "timestamp": "20070424210532", "original": "http://www.fastclick.net/images/home/create_account_lable.gif", "mimetype": "image/gif"},
    {"category": "ad-network", "timestamp": "20070424210531", "original": "http://www.fastclick.net/images/home/dot_line_right.gif", "mimetype": "image/gif"},
    {"category": "ad-network", "timestamp": "20070424210532", "original": "http://www.fastclick.net/images/home/news_lable.gif", "mimetype": "image/gif"},
    {"category": "ad-network", "timestamp": "20070424210532", "original": "http://www.fastclick.net/images/home/publishers_lable.gif", "mimetype": "image/gif"},
    {"category": "ad-network", "timestamp": "20070424210529", "original": "http://www.fastclick.net/images/home/signin_lable.gif", "mimetype": "image/gif"},
    {"category": "ad-network", "timestamp": "20070424210709", "original": "http://www.fastclick.net/images/increase_revenue.gif", "mimetype": "image/gif"},
    {"category": "ad-network", "timestamp": "20050819140456", "original": "http://www.burstnet.com/addesktop_logo_new.gif", "mimetype": "image/gif"},
    {"category": "ad-network", "timestamp": "20050819140439", "original": "http://www.burstnet.com/bg.gif", "mimetype": "image/gif"},
    {"category": "ad-network", "timestamp": "20050819140448", "original": "http://www.burstnet.com/bg_hm_purple.gif", "mimetype": "image/gif"},
    {"category": "ad-network", "timestamp": "20021006100702", "original": "http://www4.burstnet.com:80/bpa.gif", "mimetype": "image/gif"},
    {"category": "ad-network", "timestamp": "20041015203618", "original": "http://www.burstnet.com/bpa.gif", "mimetype": "image/gif"},
    {"category": "ad-network", "timestamp": "20060318043832", "original": "http://www.burstnet.com/burstnet.gif", "mimetype": "image/gif"},
    {"category": "ad-network", "timestamp": "19970711150708", "original": "http://www1.linkexchange.com:80/apache_pb.gif", "mimetype": "image/gif"},
    {"category": "ad-network", "timestamp": "19970314233458", "original": "http://www.linkexchange.com:80/buttons/x003875.gif", "mimetype": "image/gif"},
    {"category": "ad-network", "timestamp": "19970314233506", "original": "http://www.linkexchange.com:80/buttons/x006671.gif", "mimetype": "image/gif"},
    {"category": "ad-network", "timestamp": "19970314233517", "original": "http://www.linkexchange.com:80/buttons/x014712.gif", "mimetype": "image/gif"},
    {"category": "ad-network", "timestamp": "19970314233525", "original": "http://www.linkexchange.com:80/buttons/x020581.gif", "mimetype": "image/gif"},
    {"category": "ad-network", "timestamp": "19970314233532", "original": "http://www.linkexchange.com:80/buttons/x024150.gif", "mimetype": "image/gif"},
    {"category": "ad-network", "timestamp": "19970314233540", "original": "http://www.linkexchange.com:80/buttons/x025424.gif", "mimetype": "image/gif"},
    {"category": "ad-network", "timestamp": "19970314233546", "original": "http://www.linkexchange.com:80/buttons/x035987.gif", "mimetype": "image/gif"},
    {"category": "ad-network", "timestamp": "19970314233554", "original": "http://www.linkexchange.com:80/buttons/x036650.gif", "mimetype": "image/gif"},
    {"category": "ad-network", "timestamp": "19970314233603", "original": "http://www.linkexchange.com:80/buttons/x040307.gif", "mimetype": "image/gif"},
    {"category": "spicy", "timestamp": "20010804190621", "original": "http://friendfinder.com:80/affil/pix/5rules.gif", "mimetype": "image/gif"},
    {"category": "spicy", "timestamp": "20021219141511", "original": "http://friendfinder.com:80/affil/pix/affiliate.gif", "mimetype": "image/gif"},
    {"category": "spicy", "timestamp": "20010618030755", "original": "http://www.friendfinder.com:80/affil/pix/afflttop.gif", "mimetype": "image/gif"},
    {"category": "spicy", "timestamp": "20010618031432", "original": "http://www.friendfinder.com:80/affil/pix/broker.gif", "mimetype": "image/gif"},
    {"category": "spicy", "timestamp": "20010618032418", "original": "http://www.friendfinder.com:80/affil/pix/cashcow.gif", "mimetype": "image/gif"},
    {"category": "spicy", "timestamp": "20021219143330", "original": "http://friendfinder.com:80/affil/pix/checks.gif", "mimetype": "image/gif"},
    {"category": "spicy", "timestamp": "20010805000245", "original": "http://friendfinder.com:80/affil/pix/company.gif", "mimetype": "image/gif"},
    {"category": "spicy", "timestamp": "20010618033452", "original": "http://www.friendfinder.com:80/affil/pix/contact.gif", "mimetype": "image/gif"},
    {"category": "spicy", "timestamp": "20021219144046", "original": "http://friendfinder.com:80/affil/pix/contact_team.gif", "mimetype": "image/gif"},
    {"category": "spicy", "timestamp": "20010630220734", "original": "http://www.friendfinder.com:80/affil/pix/evolutn.gif", "mimetype": "image/gif"},
    {"category": "casino", "timestamp": "20030401143018", "original": "http://www.intercasino.com:80/banner/468x60tournamentv5_80.gif", "mimetype": "image/gif"},
    {"category": "casino", "timestamp": "20010702060202", "original": "http://www.intercasino.com:80/banner/gui_blue80.gif", "mimetype": "image/gif"},
    {"category": "casino", "timestamp": "19971113114605", "original": "http://www.intercasino.com:80/images/100hot.gif", "mimetype": "image/gif"},
    {"category": "casino", "timestamp": "19971113114955", "original": "http://www.intercasino.com:80/images/5rate.gif", "mimetype": "image/gif"},
    {"category": "casino", "timestamp": "20060425202623", "original": "http://www.partycasino.com:80/i/die_footer.gif", "mimetype": "image/gif"},
    {"category": "casino", "timestamp": "20060426005105", "original": "http://www.partycasino.com:80/i/downloadsm.gif", "mimetype": "image/gif"},
    {"category": "casino", "timestamp": "20060425202228", "original": "http://www.partycasino.com:80/i/hdrPGproduct.gif", "mimetype": "image/gif"},
    {"category": "casino", "timestamp": "20060426022400", "original": "http://www.partycasino.com:80/i/homesignup.gif", "mimetype": "image/gif"},
    {"category": "casino", "timestamp": "20060426022354", "original": "http://www.partycasino.com:80/i/homevisa.gif", "mimetype": "image/gif"},
    {"category": "sweepstakes", "timestamp": "20000815075126", "original": "http://www.cashfiesta.com:80/banners/banner.gif", "mimetype": "image/gif"},
    {"category": "sweepstakes", "timestamp": "20000815090233", "original": "http://www.cashfiesta.com:80/banners/banner234x60.gif", "mimetype": "image/gif"},
    {"category": "sweepstakes", "timestamp": "20000815084824", "original": "http://www.cashfiesta.com:80/banners/banner_1_120x60.gif", "mimetype": "image/gif"},
    {"category": "sweepstakes", "timestamp": "20000815084857", "original": "http://www.cashfiesta.com:80/banners/banner_1_234x60.gif", "mimetype": "image/gif"},
    {"category": "sweepstakes", "timestamp": "20000816005327", "original": "http://www.cashfiesta.com:80/banners/banner_1_468x60.gif", "mimetype": "image/gif"},
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download a starter set of archived 1990s/2000s web ads from the Wayback Machine."
    )
    parser.add_argument("--count", type=int, default=50, help="Target number of ads to download.")
    parser.add_argument("--per-query", type=int, default=20, help="Candidate snapshot count to request per seed query.")
    parser.add_argument("--from-year", type=int, default=1995, help="Earliest capture year.")
    parser.add_argument("--to-year", type=int, default=2009, help="Latest capture year.")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Folder where ads and the manifest should be stored.",
    )
    parser.add_argument("--pause-ms", type=int, default=300, help="Delay between downloads in milliseconds.")
    args = parser.parse_args()

    output_dir = args.output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = output_dir / "manifest.json"
    manifest = load_manifest(manifest_path)
    seen_keys = {
        f"{item.get('timestamp', '')}|{item.get('original', '')}"
        for item in manifest
    }

    candidates = collect_candidates(
        count=max(args.count * 3, args.per_query),
        per_query=args.per_query,
        from_year=args.from_year,
        to_year=args.to_year,
        seen_keys=seen_keys,
    )

    if not candidates:
        print("No archived ad candidates were found for the configured query set.")
        return

    downloaded = 0
    for candidate in candidates:
        if downloaded >= args.count:
            break

        target_dir = output_dir / candidate["category"]
        target_dir.mkdir(parents=True, exist_ok=True)

        destination = target_dir / build_filename(candidate)
        if destination.exists():
            continue

        if not download_capture(candidate["timestamp"], candidate["original"], destination):
            continue

        manifest.append(
            {
                "category": candidate["category"],
                "timestamp": candidate["timestamp"],
                "original": candidate["original"],
                "mimetype": candidate["mimetype"],
                "saved_to": str(destination.relative_to(output_dir)),
            }
        )
        write_manifest(manifest_path, manifest)
        downloaded += 1
        print(f"[{downloaded}/{args.count}] saved {destination}")
        time.sleep(max(args.pause_ms, 0) / 1000)

    print(f"Finished with {downloaded} downloads in {output_dir}")


def collect_candidates(
    *,
    count: int,
    per_query: int,
    from_year: int,
    to_year: int,
    seen_keys: set[str],
) -> list[dict[str, str]]:
    pool: list[dict[str, str]] = []

    for item in CURATED_CAPTURES:
        key = f"{item['timestamp']}|{item['original']}"
        if key in seen_keys:
            continue
        pool.append(
            {
                "category": item["category"],
                "timestamp": item["timestamp"],
                "original": item["original"],
                "mimetype": item["mimetype"],
                "score": str(score_candidate(item["original"], item["category"]) + 5),
            }
        )
        seen_keys.add(key)

    for seed in SEED_QUERIES:
        rows = query_cdx(seed["pattern"], per_query, from_year, to_year)
        for row in rows:
            timestamp = row.get("timestamp", "")
            original = row.get("original", "")
            mimetype = row.get("mimetype", "")
            key = f"{timestamp}|{original}"
            if not timestamp or not original or key in seen_keys:
                continue
            if mimetype not in seed["mimetypes"]:
                continue
            pool.append(
                {
                    "category": seed["category"],
                    "timestamp": timestamp,
                    "original": original,
                    "mimetype": mimetype,
                    "score": str(score_candidate(original, seed["category"])),
                }
            )
            seen_keys.add(key)

    pool.sort(key=lambda item: int(item["score"]), reverse=True)
    return pool[:count]


def query_cdx(pattern: str, limit: int, from_year: int, to_year: int) -> list[dict[str, str]]:
    params = {
        "url": pattern,
        "from": str(from_year),
        "to": str(to_year),
        "output": "json",
        "fl": "timestamp,original,mimetype,statuscode,digest",
        "filter": ["statuscode:200"],
        "collapse": "digest",
        "limit": str(limit),
    }
    url = f"{CDX_API}?{urlencode(params, doseq=True)}"
    payload = fetch_json(url)
    if not payload or not isinstance(payload, list) or len(payload) < 2:
        return []

    headers = payload[0]
    rows = []
    for item in payload[1:]:
        if not isinstance(item, list):
            continue
        row = {headers[index]: str(value) for index, value in enumerate(item) if index < len(headers)}
        rows.append(row)
    return rows


def download_capture(timestamp: str, original: str, destination: Path) -> bool:
    url = WAYBACK_RAW.format(timestamp=timestamp, original=original)
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            destination.write_bytes(response.read())
        return True
    except (HTTPError, URLError, TimeoutError, socket.timeout):
        return False


def build_filename(candidate: dict[str, str]) -> str:
    stem = sanitize_filename(urlparse(candidate["original"]).path.rsplit("/", 1)[-1] or "ad")
    extension = Path(stem).suffix.lower()
    if not extension:
        extension = EXTENSIONS.get(candidate["mimetype"], ".bin")
        stem = f"{stem}{extension}"
    timestamp = candidate["timestamp"]
    return f"{timestamp}_{stem}"


def score_candidate(original: str, category: str) -> int:
    lowered = original.lower()
    score = 0

    for token in ("banner", "ad", "ads", "promo", "affiliates", "creative", "468x60", "120x600", "728x90"):
        if token in lowered:
            score += 2

    if category == "casino" and any(token in lowered for token in ("casino", "poker", "blackjack", "slots")):
        score += 3
    if category == "spicy" and any(token in lowered for token in ("adult", "friendfinder", "passion", "sex")):
        score += 3
    if category == "sweepstakes" and any(token in lowered for token in ("cash", "sweep", "win", "prize")):
        score += 3

    filename = urlparse(original).path.rsplit("/", 1)[-1]
    if filename.endswith((".gif", ".jpg", ".jpeg", ".png")):
        score += 1

    return score


def sanitize_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return cleaned or "ad"


def load_manifest(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def write_manifest(path: Path, manifest: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def fetch_json(url: str) -> Any:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=QUERY_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, socket.timeout, json.JSONDecodeError):
        return None


if __name__ == "__main__":
    main()
