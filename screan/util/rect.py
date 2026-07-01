"""矩形工具:对齐、裁剪、合并、贪心聚类。

合成器用它把多个 widget 的脏区合并到 ≤ N 个矩形,降低 SPI 命令开销。
脏区合并是本项目的性能命脉:每个矩形发一次 set_window + RAMWR 有固定开销,
碎片化矩形数过多反而比合并成一个大框慢。
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def x2(self) -> int:
        return self.x + self.w

    @property
    def y2(self) -> int:
        return self.y + self.h

    @property
    def area(self) -> int:
        return self.w * self.h

    @property
    def empty(self) -> bool:
        return self.w <= 0 or self.h <= 0

    def intersects(self, other: "Rect") -> bool:
        return not (self.x2 <= other.x or other.x2 <= self.x
                    or self.y2 <= other.y or other.y2 <= self.y)

    def touches(self, other: "Rect", gap: int = 0) -> bool:
        """相邻(含 gap 像素空隙)或相交都返回 True。
        当两个矩形之间距离恰好 == gap 时,算"刚好接触",返回 True。"""
        return not (self.x2 + gap < other.x or other.x2 + gap < self.x
                    or self.y2 + gap < other.y or other.y2 + gap < self.y)

    def union(self, other: "Rect") -> "Rect":
        x = min(self.x, other.x)
        y = min(self.y, other.y)
        x2 = max(self.x2, other.x2)
        y2 = max(self.y2, other.y2)
        return Rect(x, y, x2 - x, y2 - y)

    def clip(self, bounds: "Rect") -> "Rect":
        x = max(self.x, bounds.x)
        y = max(self.y, bounds.y)
        x2 = min(self.x2, bounds.x2)
        y2 = min(self.y2, bounds.y2)
        return Rect(x, y, max(0, x2 - x), max(0, y2 - y))

    def align(self, n: int) -> "Rect":
        """把矩形按 n 像素对齐到外侧(扩大),保证 ILI9488 set_window 边界稳定。"""
        if n <= 1:
            return self
        x = (self.x // n) * n
        y = (self.y // n) * n
        x2 = ((self.x2 + n - 1) // n) * n
        y2 = ((self.y2 + n - 1) // n) * n
        return Rect(x, y, x2 - x, y2 - y)


def merge_overlapping(rects: list[Rect], gap: int = 0) -> list[Rect]:
    """传递闭包:把相交/相邻的矩形合并成连通分量的 bbox。"""
    rects = [r for r in rects if not r.empty]
    if len(rects) <= 1:
        return list(rects)
    # 并查集
    parent = list(range(len(rects)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            if rects[i].touches(rects[j], gap):
                union(i, j)

    groups: dict[int, Rect] = {}
    for i, r in enumerate(rects):
        root = find(i)
        groups[root] = groups[root].union(r) if root in groups else r
    return list(groups.values())


def _waste(a: Rect, b: Rect) -> int:
    """合并后浪费面积 = bbox(a,b).area - a.area - b.area。越小越值得合并。"""
    return a.union(b).area - a.area - b.area


def coalesce(
    rects: list[Rect],
    *,
    bounds: Rect,
    max_rects: int = 4,
    align: int = 2,
    gap: int = 16,
) -> list[Rect]:
    """脏矩形合并主流程:
    1) 裁剪 + 对齐
    2) 合并相交/相邻(gap 像素以内)
    3) 若矩形数仍 > max_rects,贪心合并"浪费最小"的对
    4) 二次对齐 + 裁剪
    """
    work = [r.clip(bounds).align(align) for r in rects]
    work = [r for r in work if not r.empty]
    if not work:
        return []
    work = merge_overlapping(work, gap=gap)

    while len(work) > max_rects:
        # O(n²) 找最小浪费对;n ≤ 几十,可接受
        best = (0, 1, _waste(work[0], work[1]))
        for i in range(len(work)):
            for j in range(i + 1, len(work)):
                w = _waste(work[i], work[j])
                if w < best[2]:
                    best = (i, j, w)
        i, j, _ = best
        merged = work[i].union(work[j])
        work = [r for k, r in enumerate(work) if k != i and k != j] + [merged]

    return [r.clip(bounds).align(align) for r in work if not r.empty]
