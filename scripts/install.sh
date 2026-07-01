#!/usr/bin/env bash
# Screan 安装/更新脚本。幂等可重跑。
#
# 用法:
#   sudo bash scripts/install.sh         # 全量:复制代码 + 装依赖 + 安装 unit + enable
#   sudo bash scripts/install.sh sync    # 只同步代码 + restart(开发迭代用)
#
# 安装位置:/opt/screan
# 服务名:screan.service

set -euo pipefail

INSTALL_DIR="/opt/screan"
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_NAME="screan.service"

require_root() {
    if [ "$(id -u)" -ne 0 ]; then
        echo "需要 root,请用 sudo 运行" >&2
        exit 1
    fi
}

sync_code() {
    echo "[1/2] 同步代码 $SRC_DIR → $INSTALL_DIR"
    mkdir -p "$INSTALL_DIR"
    # 复制源(排除临时文件/已有 venv/已有 config)
    # 注意:--exclude '_*.py' 用大写 [^_] 起始更安全,这里改成只排开发期临时单文件 spike
    rsync -a --delete \
        --exclude '.git' \
        --exclude '__pycache__' \
        --exclude '*.pyc' \
        --exclude 'venv' \
        --exclude '.claude' \
        --exclude '/_*.py' \
        --exclude 'tests/__pycache__' \
        "$SRC_DIR/screan" "$SRC_DIR/systemd" "$SRC_DIR/scripts" \
        "$SRC_DIR/README.md" "$SRC_DIR/pyproject.toml" \
        "$INSTALL_DIR/"
    # 配置文件:首次复制,之后保留生产侧
    if [ ! -f "$INSTALL_DIR/config.toml" ]; then
        cp "$SRC_DIR/config.toml" "$INSTALL_DIR/config.toml"
        echo "    已写入默认 config.toml"
    else
        echo "    保留已存在的 config.toml(参考新版:$SRC_DIR/config.toml)"
    fi
}

setup_venv() {
    echo "[2/2] 准备 venv 并安装依赖"
    if [ ! -d "$INSTALL_DIR/venv" ]; then
        python3 -m venv --system-site-packages "$INSTALL_DIR/venv"
    fi
    "$INSTALL_DIR/venv/bin/pip" install --upgrade pip --quiet
    # skia-python 是唯一非 apt 的依赖;其它直接用 system-site-packages
    "$INSTALL_DIR/venv/bin/pip" install --quiet 'skia-python~=144.0'
}

install_unit() {
    echo "安装 systemd unit"
    install -m 0644 "$SRC_DIR/systemd/$UNIT_NAME" "/etc/systemd/system/$UNIT_NAME"
    systemctl daemon-reload
}

enable_and_start() {
    echo "启用并启动 $UNIT_NAME"
    systemctl enable "$UNIT_NAME"
    systemctl restart "$UNIT_NAME"
    sleep 1
    systemctl --no-pager --full status "$UNIT_NAME" || true
}

require_root
case "${1:-full}" in
    full)
        sync_code
        setup_venv
        install_unit
        enable_and_start
        echo
        echo "完成。查看日志:journalctl -u $UNIT_NAME -f"
        ;;
    sync)
        sync_code
        systemctl restart "$UNIT_NAME"
        echo "已 sync + restart。查看日志:journalctl -u $UNIT_NAME -f"
        ;;
    *)
        echo "未知子命令: $1" >&2
        exit 2
        ;;
esac
