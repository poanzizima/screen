"""Rect / coalesce 单元测试。"""
import pytest

from screan.util.rect import Rect, coalesce, merge_overlapping


class TestRect:
    def test_area(self):
        assert Rect(0, 0, 10, 20).area == 200
        assert Rect(0, 0, 0, 5).area == 0

    def test_empty(self):
        assert Rect(0, 0, 0, 5).empty
        assert Rect(0, 0, 5, 0).empty
        assert not Rect(0, 0, 1, 1).empty

    def test_intersects(self):
        a = Rect(0, 0, 10, 10)
        b = Rect(5, 5, 10, 10)
        c = Rect(20, 20, 5, 5)
        assert a.intersects(b)
        assert not a.intersects(c)

    def test_touches_gap(self):
        a = Rect(0, 0, 10, 10)
        b = Rect(15, 0, 5, 5)   # 距离 5 像素
        assert not a.touches(b, gap=0)
        assert a.touches(b, gap=5)
        assert a.touches(b, gap=10)

    def test_union(self):
        a = Rect(0, 0, 10, 10)
        b = Rect(20, 20, 5, 5)
        u = a.union(b)
        assert u == Rect(0, 0, 25, 25)

    def test_clip(self):
        bounds = Rect(0, 0, 100, 100)
        r = Rect(-10, 50, 30, 200)
        c = r.clip(bounds)
        assert c == Rect(0, 50, 20, 50)

    def test_align_expands_outward(self):
        # 起点 3 → 2, 终点 13 → 14, 高度 5+7=12 → 终点 12, 起点 5→4, h=12-4=8
        r = Rect(3, 5, 10, 7).align(2)
        assert r == Rect(2, 4, 12, 8)

    def test_align_n1_noop(self):
        r = Rect(3, 5, 10, 7)
        assert r.align(1) == r


class TestMergeOverlapping:
    def test_no_overlap(self):
        rects = [Rect(0, 0, 5, 5), Rect(100, 100, 5, 5)]
        out = merge_overlapping(rects, gap=0)
        assert len(out) == 2

    def test_transitive(self):
        """A-B 相交, B-C 相交, 三者应合成一个"""
        a = Rect(0, 0, 10, 10)
        b = Rect(8, 0, 10, 10)
        c = Rect(16, 0, 10, 10)
        out = merge_overlapping([a, b, c])
        assert len(out) == 1
        assert out[0] == Rect(0, 0, 26, 10)

    def test_gap_merges_neighbors(self):
        a = Rect(0, 0, 10, 10)
        b = Rect(15, 0, 10, 10)
        # gap=5 应合并
        out = merge_overlapping([a, b], gap=5)
        assert len(out) == 1


class TestCoalesce:
    def test_clips_to_bounds(self):
        bounds = Rect(0, 0, 100, 100)
        out = coalesce([Rect(-10, -10, 200, 200)], bounds=bounds)
        assert len(out) == 1
        assert out[0] == bounds

    def test_drops_empty(self):
        bounds = Rect(0, 0, 100, 100)
        out = coalesce([Rect(0, 0, 0, 0), Rect(10, 10, 20, 20)], bounds=bounds)
        assert len(out) == 1

    def test_alignment(self):
        bounds = Rect(0, 0, 100, 100)
        out = coalesce([Rect(3, 5, 11, 7)], bounds=bounds, align=2)
        # 2 对齐: 3→2, 14→14, 5→4, 12→12
        assert out[0].x % 2 == 0 and out[0].y % 2 == 0
        assert out[0].w % 2 == 0 and out[0].h % 2 == 0

    def test_max_rects_caps(self):
        """4 个非相邻矩形,max_rects=2 时合并为 2 个"""
        bounds = Rect(0, 0, 200, 200)
        rects = [
            Rect(0, 0, 10, 10),
            Rect(50, 0, 10, 10),
            Rect(0, 50, 10, 10),
            Rect(50, 50, 10, 10),
        ]
        out = coalesce(rects, bounds=bounds, max_rects=2, align=1, gap=0)
        assert len(out) <= 2

    def test_max_rects_no_op_when_under(self):
        bounds = Rect(0, 0, 200, 200)
        rects = [Rect(0, 0, 10, 10), Rect(50, 50, 10, 10)]
        out = coalesce(rects, bounds=bounds, max_rects=4, align=1, gap=0)
        assert len(out) == 2
