# SysMon

> 系统资源监控工具 -- CLI 彩色终端 + HTML 可视化报告，纯 Python 标准库零依赖

[![Python](https://img.shields.io/badge/Python-3.8+-blue)](https://www.python.org/)
[![No Dependencies](https://img.shields.io/badge/Dependencies-None-brightgreen)]()
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## 功能特性

| 特性 | 说明 |
|------|------|
| CPU 监控 | 实时 CPU 使用率（Windows / Linux 跨平台） |
| 内存监控 | 物理内存使用量、使用率 |
| 磁盘监控 | 磁盘使用量、使用率 |
| 网络监控 | 上传/下载速率、累计流量 |
| 进程统计 | 系统进程总数 |
| CLI 彩色输出 | 终端实时刷新，进度条颜色随负载变化 |
| HTML 报告 | SVG 图表可视化，零外部依赖 |
| JSON 导出 | 结构化数据导出，便于二次分析 |
| 零依赖 | 纯 Python 标准库实现，无需 pip install |

## 快速开始

```bash
# 持续监控（Ctrl+C 停止）
python sysmon.py

# 监控 60 个采样点
python sysmon.py -n 60

# 每 2 秒采样，共 30 次
python sysmon.py -i 2 -n 30

# 后台模式，只生成报告
python sysmon.py --no-cli -n 100

# 自定义输出文件
python sysmon.py -o my_report.html
```

## 输出示例

### CLI 终端

```
  ╔══════════════════════════════════════════════╗
  ║        SysMon - System Resource Monitor      ║
  ╚══════════════════════════════════════════════╝
  Host: DESKTOP-ABC  |  OS: Windows 10  |  CPUs: 8
  Started: 2026-05-07 23:00:00  |  Samples: 15

  CPU      [████████░░░░░░░░░░░░]  32.5%  186 processes
  Memory   [██████████░░░░░░░░░░]  51.2%  8.1GB / 16.0GB
  Disk     [██████████████░░░░░░]  68.3%  180.2GB / 256.0GB

  Network  ↑ 12.3KB/s   ↓ 45.6KB/s   (cumulative: ↑1.2MB ↓5.8MB)
```

### HTML 报告

自动生成包含以下内容的 HTML 文件：
- 汇总统计卡片（平均/峰值 CPU、平均/峰值内存）
- CPU 使用率趋势图（SVG）
- 内存使用率趋势图（SVG）
- 磁盘使用率趋势图（SVG）
- 采样数据明细表

## 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `-i, --interval` | 采样间隔（秒） | 1.0 |
| `-n, --count` | 采样次数（不指定则无限） | 无限 |
| `-o, --output` | HTML 报告输出路径 | report.html |
| `--no-cli` | 禁用终端显示，只生成报告 | 否 |
| `--json-only` | 只输出 JSON | 否 |

## 跨平台支持

| 平台 | CPU | 内存 | 磁盘 | 网络 |
|------|-----|------|------|------|
| Windows | GetSystemTimes API | GlobalMemoryStatusEx | GetDiskFreeSpaceEx | netstat |
| Linux | /proc/stat | /proc/meminfo | statvfs | /proc/net/dev |

## 项目结构

```
sysmon/
├── sysmon.py       # 主程序（全部逻辑在一个文件）
├── README.md       # 项目文档
└── LICENSE         # MIT 许可证
```

## 设计亮点

1. **零依赖**: 不需要 `pip install psutil` 或任何第三方库，纯标准库实现
2. **跨平台**: Windows 和 Linux 使用不同系统 API，统一接口
3. **实时 CLI**: 终端刷新显示，进度条颜色随负载自动变化（绿/黄/红）
4. **SVG 图表**: HTML 报告内嵌 SVG 趋势图，无外部依赖
5. **数据导出**: JSON 格式导出原始数据，便于用 pandas/Excel 二次分析

## License

MIT
