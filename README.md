# Screan — 树莓派 ILI9488 工业级监控副屏

为 Raspberry Pi 4B + 3.5″ ILI9488 SPI TFT(320×480)打造的常驻系统监控副屏。
显示 CPU / 内存 / 温度 / 网络等指标,**苹果克制风视觉**、**脏矩形局部刷新**、**Skia 渲染**、systemd 自启动。

## 设计亮点

- **Skia 渲染引擎**(`skia-python`,Flutter / Chrome 同款 2D 引擎,C++ + NEON 加速)。抗锯齿、亚像素、渐变、圆角全免费。
- **脏矩形局部刷新**:每个 widget 自己判断"视觉是否变化",compositor 合并脏区,只发改变部分的字节。**数据变化区域可达 100 + FPS**,静态区零 SPI 流量。
- **lgpio + spidev**(放弃 RPi.GPIO,后者在内核 6.x 已弃用)。
- **24 MHz SPI、RGB666**(经实测 lgpio + 24 MHz + RGB666 在该模组完全稳定;**RGB565 在 ILI9488 4-line SPI 下硬件不支持**,会黑屏/白屏)。
- **systemd Type=notify + WatchdogSec**:首帧后 `READY=1`,周期喂狗,卡死自动重启。`MemoryMax=128M` + `Restart=always` 工业级护栏。
- **TOML 配置外置**:不改代码就能改主题、布局、采样频率、SPI 速率。
- **优雅退出 < 200ms**:SIGTERM → 关背光 + DISPOFF + 释放 GPIO/SPI(实测 101 ms)。
- **单 widget 异常隔离**,不拖垮主循环。

## 硬件接线(BCM 编号)

| ILI9488 | Pi 4B BCM | 物理脚 | 说明 |
|---|---|---|---|
| VCC | 3.3V | 1 | |
| GND | GND | 6 | |
| CLK | GPIO 11 (SCLK) | 23 | |
| MOSI | GPIO 10 (MOSI) | 19 | |
| CS | GPIO 7 (CE1) | 26 | 对应 `spidev0.1` |
| DC/RS | GPIO 25 | 22 | |
| RESET | GPIO 24 | 18 | |
| BLK | GPIO 18 | 12 | 背光,GPIO HIGH 常亮 |

触摸(CTP_SDA/SCL/INT/RST)目前**未启用**——本项目作为常驻监控副屏,不依赖触摸。后续可加。

## 性能(实测,Pi 4B,24 MHz SPI,RGB666)

| 操作 | 耗时 | 等效带宽/FPS |
|---|---|---|
| 整屏 480×320 RGB666 (450 KB) | 174 ms | 2.6 MB/s → 5.7 FPS |
| 100×80 局部 (24 KB) | 9.3 ms | 107 FPS |
| Skia 渲染(整屏 4 widget) | ~10 ms | 远低于 SPI |
| RGBA8888 → RGB666 (整屏) | 4 ms | numpy 向量化 |
| 首帧总耗时(冷启动到上屏) | **211 ms** | 含 ILI9488 init |
| 接 SIGTERM 到清屏退出 | **101 ms** | 远低于 200ms 预算 |
| CPU 占用(空载,1 Hz 更新) | < 2 % | |

## 安装(生产部署)

```bash
sudo bash scripts/install.sh
```

该脚本会:
1. 把代码 rsync 到 `/opt/screan/`
2. 在 `/opt/screan/venv` 建 venv 并 `pip install skia-python~=144.0`
3. 安装 `systemd/screan.service` → `/etc/systemd/system/`
4. `systemctl enable --now screan`

重启后会自动启动。

### 仅同步代码(开发迭代)

```bash
sudo bash scripts/install.sh sync     # rsync 代码 + systemctl restart screan
```

### 查看状态/日志

```bash
sudo systemctl status screan
sudo journalctl -u screan -f
sudo journalctl -u screan --since '1 hour ago'
```

### 常用运维命令

```bash
# 状态
sudo systemctl status screan        # 详细状态
sudo systemctl is-enabled screan    # 是否开机自启
sudo systemctl is-active screan     # 是否正在运行

# 启停
sudo systemctl stop screan
sudo systemctl start screan
sudo systemctl restart screan       # 改完 config.toml 后用这个

# 开机自启
sudo systemctl enable screan        # 启用
sudo systemctl disable screan       # 取消

# 日志
sudo journalctl -u screan -f                    # 实时跟踪
sudo journalctl -u screan -n 100 --no-pager     # 最近 100 行
sudo journalctl -u screan --since '10 min ago'  # 时间范围
sudo journalctl -u screan -p err                # 仅 ERROR
sudo journalctl -u screan --since today         # 今天的全部

# 改配置
sudo nano /opt/screan/config.toml
sudo systemctl restart screan

# 开发迭代:改完源码同步到 /opt/screan 并重启
cd /home/respi/Desktop/screan
sudo bash scripts/install.sh sync

# 临时手动跑(不通过 systemd,Ctrl+C 退出)
sudo systemctl stop screan          # 先停服务,避免抢 SPI
sudo /opt/screan/venv/bin/python -m screan --no-journal
```

### 卸载

```bash
sudo systemctl disable --now screan
sudo rm /etc/systemd/system/screan.service
sudo systemctl daemon-reload
sudo rm -rf /opt/screan
```

## 配置

部署后改 `/opt/screan/config.toml`,然后 `sudo systemctl restart screan`。

主要配置项:
- `[display]` — SPI 速率、引脚、方向(0=竖, 1=横 90°, 2=竖 180°, 3=横 270°)、背光
- `[render]` — 脏区合并上限、帧率上限
- `[sampling]` — 各项指标的采样周期(秒)
- `[[widgets]]` — 数组形式,每个 widget 一个表项,指定 `type` 和 `rect = [x, y, w, h]`

可用 widget 类型:`cpu` / `memory` / `temperature` / `network`。

布局完全自定义,只要 `rect` 不超出屏幕边界(横屏 480×320,竖屏 320×480)。

## 开发

不部署也可以本地运行:

```bash
# 假设依赖已通过 apt 装:python3-psutil python3-pil python3-numpy python3-spidev python3-lgpio
python3 -m venv --system-site-packages venv
venv/bin/pip install 'skia-python~=144.0' pytest

# 运行
sudo venv/bin/python -m screan --config config.toml --no-journal

# 测试(纯算法,无硬件依赖)
venv/bin/python -m pytest tests/ -v
```

## 故障排除

| 现象 | 原因 / 修复 |
|---|---|
| 黑屏 | 背光没接 / GPIO 18 接错 / 电源不足 |
| 全白 | COLMOD 设到了 RGB565 (`0x55`),但 ILI9488 4-line SPI 不支持。**只能用 RGB666 (`0x66`)** |
| 上下有颜色、中间黑 / 灰 | 数据传输被切;升级到 `writebytes2(整 bytes)` 已修。详见 git 历史 |
| 文字镜像 | MADCTL 的 MX 位反了。横屏用 `0x28`,竖屏 `0x48`(已默认) |
| 背光闪烁/脉动 | `pwm_hz > 0` 时 lgpio 软 PWM 有抖动。**默认 `pwm_hz=0` 用纯 GPIO HIGH** 完全稳定 |
| 24 MHz 有花屏 | 杜邦线太长 / 信号完整性差。降到 `spi_speed_hz = 16_000_000` 或 `12_000_000` |
| 启动后无显示 | `sudo journalctl -u screan -e` 看错误;检查 `/dev/spidev0.1` 是否存在(`dtparam=spi=on`) |
| systemd 反复重启 | `WatchdogSec` 触发。看 `journalctl` 找原因(通常是渲染异常);临时可注释 unit 里 `WatchdogSec` |

## 包结构

```
screan/
├── __main__.py           # python -m screan 入口
├── app.py                # asyncio 主循环 + 信号 + sd_notify
├── config.py             # TOML 加载/校验
├── driver/
│   ├── ili9488.py        # lgpio + spidev + update_region
│   └── colorconv.py      # numpy RGBA → RGB666
├── render/
│   ├── theme.py          # 颜色/字体/尺寸常量
│   ├── surface.py        # Skia surface 持有
│   └── compositor.py     # 脏区合并 + 帧调度
├── widgets/
│   ├── base.py           # ABC: update() / render() / dirty
│   ├── cpu.py memory.py temperature.py network.py
│   ├── _draw.py          # 通用绘制(进度条/对齐文字/格式化)
│   └── registry.py       # type → class 映射
├── collect/
│   ├── state.py          # Metrics 不可变快照
│   ├── sources.py        # psutil / /sys 读取
│   └── sampler.py        # 异步分频调度
└── util/
    ├── rect.py           # Rect + 脏区合并算法
    ├── sdnotify.py       # 无依赖 systemd 通知
    └── log.py            # journald 友好日志

systemd/screan.service
scripts/install.sh
config.toml
pyproject.toml
tests/                    # 纯算法,无硬件依赖,任意机器可跑
```

## 历史 / 回退

- `ili9488_display.py`、`ili9488_probe.py` 是原始单文件实现 + 灰屏排障脚本,**保留作为回退基准**。新代码不依赖它们。

## 关键技术决策

| 决定 | 备选 | 选择理由 |
|---|---|---|
| Skia | Pillow / LVGL / Qt | aarch64 wheel 现成,视觉效果最强,C++ 加速,CPU 占用低 |
| RGB666 | RGB565 | ILI9488 4-line SPI 硬件限制,RGB565 实测黑屏 |
| 24 MHz | 8 / 16 / 40 MHz | 实测稳定最高速率;再高 SPI 时钟源整数分频不友好 |
| lgpio | RPi.GPIO / gpiozero | 内核 6.x 上 RPi.GPIO 已弃用;lgpio 是 Pi 官方现代栈 |
| 纯 GPIO HIGH 背光 | 软件 PWM / 硬件 PWM | lgpio 软 PWM 有可感知抖动;硬件 PWM 需要重启加 overlay,常驻副屏无需调光 |
| 脏矩形 | 全屏满刷 | SPI 带宽 2.6 MB/s,整屏 174ms ≈ 5.7 FPS。脏区策略下数据变化区可 60+ FPS |
| asyncio | 多线程 / 多进程 | 采样 + 渲染均轻量,单事件循环最简单,无锁 |
| TOML | YAML / JSON | Python 3.11+ 内置 tomllib,无依赖,工业配置标准 |
| systemd Type=notify | Type=simple | 显式 READY=1 让 systemd 知道首帧完成才算"启动";WatchdogSec 工业刚需 |

## License

本项目自用。如有引用价值,采用 MIT。
