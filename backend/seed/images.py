"""Parallel rendering of product images (kept out of __main__ so worker processes can import it)."""

import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from seed.generator import GenProduct
from seed.render import render_flatlay, render_swatch, save_webp
from seed.taxonomy import COLOURS


def _image_paths(media_root: Path, slug: str) -> tuple[Path, Path]:
    folder = media_root / "products"
    return folder / f"{slug}.webp", folder / f"{slug}-swatch.webp"


RenderJob = tuple[str, str, str, str, str, str, list[str], int]


def _render_one(job: RenderJob) -> None:
    media_root, slug, shape, colour_hex, pattern, material, secondary_hex, seed = job
    flat, swatch = _image_paths(Path(media_root), slug)
    if not flat.exists():
        save_webp(
            render_flatlay(
                shape,
                colour_hex,
                pattern=pattern,
                material=material,
                secondary_hex=secondary_hex,
                seed=seed,
            ),
            flat,
        )
    if not swatch.exists():
        save_webp(
            render_swatch(
                colour_hex,
                pattern=pattern,
                material=material,
                secondary_hex=secondary_hex,
                seed=seed,
            ),
            swatch,
        )


def render_images(products: list[GenProduct], media_root: Path, workers: int) -> None:
    jobs = [
        (
            str(media_root),
            p.slug,
            p.shape,
            p.colour_hex,
            p.pattern,
            p.material,
            [COLOURS[c][0] for c in p.secondary_colours],
            p.key,
        )
        for p in products
    ]
    pending = [j for j in jobs if not all(x.exists() for x in _image_paths(media_root, j[1]))]
    if not pending:
        print(f"images: all {len(jobs)} present")
        return
    start = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for i, _ in enumerate(pool.map(_render_one, pending, chunksize=8), 1):
            if i % 100 == 0 or i == len(pending):
                print(f"images: {i}/{len(pending)}", flush=True)
    print(f"images: rendered {len(pending)} in {time.perf_counter() - start:.1f}s")
