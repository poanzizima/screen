"""colorconv 单元测试。
纯 numpy 运算,任何机器都可跑(不需要树莓派 / SPI)。"""
import numpy as np
import pytest

from screan.driver.colorconv import rgba_to_rgb666, solid_rgb666


class TestRgbaToRgb666:
    def test_shape(self):
        arr = np.zeros((10, 20, 4), dtype=np.uint8)
        out = rgba_to_rgb666(arr)
        assert isinstance(out, (bytes, bytearray))
        assert len(out) == 10 * 20 * 3

    def test_pixel_order_RGB(self):
        """单像素红 → 字节 (255, 0, 0)"""
        arr = np.zeros((1, 1, 4), dtype=np.uint8)
        arr[0, 0] = [255, 0, 0, 255]
        assert bytes(rgba_to_rgb666(arr)) == bytes([255, 0, 0])

    def test_pixel_order_BGR_dropped(self):
        """Alpha 通道丢弃"""
        arr = np.zeros((1, 1, 4), dtype=np.uint8)
        arr[0, 0] = [10, 20, 30, 99]
        assert bytes(rgba_to_rgb666(arr)) == bytes([10, 20, 30])

    def test_row_order(self):
        """多像素行优先(row-major)"""
        arr = np.zeros((2, 2, 4), dtype=np.uint8)
        arr[0, 0] = [1, 2, 3, 0]
        arr[0, 1] = [4, 5, 6, 0]
        arr[1, 0] = [7, 8, 9, 0]
        arr[1, 1] = [10, 11, 12, 0]
        assert bytes(rgba_to_rgb666(arr)) == bytes(
            [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
        )

    def test_rejects_wrong_dtype(self):
        with pytest.raises(ValueError):
            rgba_to_rgb666(np.zeros((1, 1, 4), dtype=np.uint16))

    def test_rejects_wrong_shape(self):
        with pytest.raises(ValueError):
            rgba_to_rgb666(np.zeros((1, 1, 2), dtype=np.uint8))

    def test_non_contiguous_input(self):
        """切片产生非连续视图,转换函数应自己处理"""
        big = np.zeros((10, 10, 4), dtype=np.uint8)
        big[2:5, 3:6] = [50, 100, 150, 0]
        sub = big[2:5, 3:6]
        out = rgba_to_rgb666(sub)
        assert len(out) == 3 * 3 * 3
        # 验证每个像素正确
        assert bytes(out[:3]) == bytes([50, 100, 150])


class TestSolid:
    def test_size(self):
        buf = solid_rgb666(4, 3, 1, 2, 3)
        assert len(buf) == 4 * 3 * 3

    def test_uniform(self):
        buf = solid_rgb666(2, 2, 10, 20, 30)
        for i in range(0, len(buf), 3):
            assert buf[i] == 10
            assert buf[i + 1] == 20
            assert buf[i + 2] == 30
