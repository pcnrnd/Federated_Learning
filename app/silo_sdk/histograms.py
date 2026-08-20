"""분포 통계 헬퍼 — 원시 데이터에서 히스토그램만 추출 (raw는 사일로 외부 유출 금지)"""
from __future__ import annotations

from typing import Iterable


def build_histogram(
    values: Iterable[float],
    bin_edges: list[float],
) -> list[int]:
    """주어진 bin_edges에 대해 카운트 히스토그램만 산출한다.

    bin_edges는 단조 증가하며 길이는 N+1. 반환 카운트 길이는 N.
    최좌측·최우측 범위 밖 값은 가장 가까운 빈에 포함된다 (clip 동작).
    """
    if len(bin_edges) < 2:
        raise ValueError("bin_edges 길이는 2 이상이어야 합니다")
    for i in range(1, len(bin_edges)):
        if bin_edges[i] <= bin_edges[i - 1]:
            raise ValueError("bin_edges는 엄격 증가여야 합니다")

    n_bins = len(bin_edges) - 1
    counts = [0] * n_bins
    for v in values:
        if v <= bin_edges[0]:
            counts[0] += 1
            continue
        if v >= bin_edges[-1]:
            counts[-1] += 1
            continue
        # 이진 탐색 대신 선형 (빈 수가 적은 일반 사용 가정)
        for i in range(n_bins):
            if bin_edges[i] <= v < bin_edges[i + 1]:
                counts[i] += 1
                break
    return counts
