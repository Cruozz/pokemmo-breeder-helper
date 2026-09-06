"""Coordinate conversions shared by embedded and detached previews."""
from __future__ import annotations

ROI = tuple[int, int, int, int]


def normalized_roi(start, end, size) -> ROI:
    width, height = size
    return (
        round(max(0, min(width, min(start[0], end[0])))),
        round(max(0, min(height, min(start[1], end[1])))),
        round(max(0, min(width, max(start[0], end[0])))),
        round(max(0, min(height, max(start[1], end[1])))),
    )


def rescale_roi(roi: ROI | None, old_size, new_size) -> ROI | None:
    if roi is None or old_size == new_size:
        return roi
    sx, sy = new_size[0] / old_size[0], new_size[1] / old_size[1]
    return normalized_roi((roi[0] * sx, roi[1] * sy), (roi[2] * sx, roi[3] * sy), new_size)


def fit_scale(image_size, viewport_size) -> float:
    return min(max(1, viewport_size[0]) / image_size[0], max(1, viewport_size[1]) / image_size[1])


def image_point(point, offset, rendered_size, image_size):
    # Use the actual rounded bitmap dimensions, not an approximate scale.
    return tuple((point[i] - offset[i]) * image_size[i] / max(1, rendered_size[i]) for i in (0, 1))
