#!/usr/bin/env python3
"""
SysMon - 系统资源监控工具
实时监控 CPU / 内存 / 磁盘 / 网络，CLI 彩色终端输出 + HTML 可视化报告。
纯 Python 标准库实现，零外部依赖。
"""

import os
import sys
import time
import json
import argparse
import platform
import threading
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import List, Optional

# ============================================================
# Windows compatibility: psutil-like functions using ctypes
# ============================================================

if sys.platform == "win32":
    import ctypes
    import ctypes.wintypes as wintypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", wintypes.DWORD),
            ("dwMemoryLoad", wintypes.DWORD),
            ("ullTotalPhys", ctypes.c_uint64),
            ("ullAvailPhys", ctypes.c_uint64),
            ("ullTotalPageFile", ctypes.c_uint64),
            ("ullAvailPageFile", ctypes.c_uint64),
            ("ullTotalVirtual", ctypes.c_uint64),
            ("ullAvailVirtual", ctypes.c_uint64),
            ("ullAvailExtendedVirtual", ctypes.c_uint64),
        ]

    def _get_memory():
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(stat)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        total = stat.ullTotalPhys
        avail = stat.ullAvailPhys
        used = total - avail
        percent = stat.dwMemoryLoad
        return {"total": total, "used": used, "available": avail, "percent": percent}

    def _get_cpu_times():
        """Get CPU times using GetSystemTimes (Windows)."""
        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

        idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
        ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))

        def ft_to_int(ft):
            return (ft.dwHighDateTime << 32) | ft.dwLowDateTime

        idle_t = ft_to_int(idle)
        kernel_t = ft_to_int(kernel)
        user_t = ft_to_int(user)
        # kernel includes idle on Windows
        busy = kernel_t - idle_t + user_t
        total = kernel_t + user_t
        return idle_t, total, busy

    def get_cpu_percent(interval=0.5):
        _, t1_total, t1_busy = _get_cpu_times()
        time.sleep(interval)
        _, t2_total, t2_busy = _get_cpu_times()
        d_total = t2_total - t1_total
        d_busy = t2_busy - t1_busy
        if d_total == 0:
            return 0.0
        return round(d_busy / d_total * 100, 1)

    def get_memory():
        return _get_memory()

    def get_disk_usage(path="C:\\"):
        total, used, free = ctypes.c_uint64(), ctypes.c_uint64(), ctypes.c_uint64()
        ctypes.windll.kernel32.GetDiskFreeSpaceExW(
            path, None, ctypes.byref(total), ctypes.byref(free)
        )
        t = total.value
        f = free.value
        u = t - f
        pct = round(u / t * 100, 1) if t > 0 else 0
        return {"total": t, "used": u, "free": f, "percent": pct}

    def get_net_io():
        """Parse ipconfig to get basic network info, or use GetIfTable."""
        # Fallback: read /proc/net equivalent via iphlpapi
        # For simplicity, use a simple counter approach
        try:
            import subprocess
            result = subprocess.run(
                ["netstat", "-e"],
                capture_output=True, text=True, timeout=5,
                creationflags=0x08000000  # CREATE_NO_WINDOW
            )
            lines = result.stdout.strip().split("\n")
            recv, sent = 0, 0
            for i, line in enumerate(lines):
                if "Bytes" in line and i < len(lines) - 1:
                    parts = lines[i + 1].split()
                    if len(parts) >= 2:
                        recv = int(parts[0])
                        sent = int(parts[1])
                    break
            return {"bytes_sent": sent, "bytes_recv": recv}
        except Exception:
            return {"bytes_sent": 0, "bytes_recv": 0}

    def get_cpu_count():
        return os.cpu_count() or 1

    def get_process_count():
        try:
            import subprocess
            result = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5,
                creationflags=0x08000000
            )
            return len([l for l in result.stdout.strip().split("\n") if l.strip()])
        except Exception:
            return 0

    def get_uptime():
        millis = ctypes.windll.kernel32.GetTickCount64()
        return timedelta(milliseconds=millis)

else:
    # Linux / macOS
    def get_cpu_percent(interval=0.5):
        try:
            with open("/proc/stat") as f:
                line1 = f.readline()
            vals1 = [int(x) for x in line1.split()[1:]]
            time.sleep(interval)
            with open("/proc/stat") as f:
                line2 = f.readline()
            vals2 = [int(x) for x in line2.split()[1:]]
            d_idle = vals2[3] - vals1[3]
            d_total = sum(vals2) - sum(vals1)
            if d_total == 0:
                return 0.0
            return round((1 - d_idle / d_total) * 100, 1)
        except Exception:
            return 0.0

    def get_memory():
        try:
            with open("/proc/meminfo") as f:
                lines = f.readlines()
            info = {}
            for line in lines:
                parts = line.split(":")
                if len(parts) == 2:
                    key = parts[0].strip()
                    val = int(parts[1].strip().split()[0]) * 1024  # kB -> bytes
                    info[key] = val
            total = info.get("MemTotal", 0)
            avail = info.get("MemAvailable", info.get("MemFree", 0))
            used = total - avail
            pct = round(used / total * 100, 1) if total > 0 else 0
            return {"total": total, "used": used, "available": avail, "percent": pct}
        except Exception:
            return {"total": 0, "used": 0, "available": 0, "percent": 0}

    def get_disk_usage(path="/"):
        try:
            st = os.statvfs(path)
            total = st.f_blocks * st.f_frsize
            free = st.f_bavail * st.f_frsize
            used = total - free
            pct = round(used / total * 100, 1) if total > 0 else 0
            return {"total": total, "used": used, "free": free, "percent": pct}
        except Exception:
            return {"total": 0, "used": 0, "free": 0, "percent": 0}

    def get_net_io():
        try:
            with open("/proc/net/dev") as f:
                lines = f.readlines()[2:]  # skip headers
            recv, sent = 0, 0
            for line in lines:
                parts = line.split()
                if len(parts) >= 10:
                    recv += int(parts[1])
                    sent += int(parts[9])
            return {"bytes_sent": sent, "bytes_recv": recv}
        except Exception:
            return {"bytes_sent": 0, "bytes_recv": 0}

    def get_cpu_count():
        return os.cpu_count() or 1

    def get_process_count():
        try:
            return len([d for d in os.listdir("/proc") if d.isdigit()])
        except Exception:
            return 0

    def get_uptime():
        try:
            with open("/proc/uptime") as f:
                secs = float(f.read().split()[0])
            return timedelta(seconds=secs)
        except Exception:
            return timedelta(0)


# ============================================================
# Data Models
# ============================================================

@dataclass
class Snapshot:
    timestamp: str
    cpu_percent: float
    mem_total: int
    mem_used: int
    mem_percent: float
    disk_total: int
    disk_used: int
    disk_percent: float
    net_sent: int
    net_recv: int
    process_count: int


@dataclass
class MonitorSession:
    start_time: str
    end_time: str = ""
    hostname: str = ""
    os_info: str = ""
    cpu_count: int = 0
    snapshots: List[dict] = field(default_factory=list)


# ============================================================
# Formatting Helpers
# ============================================================

def fmt_bytes(b: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(b) < 1024:
            return f"{b:.1f}{unit}"
        b /= 1024
    return f"{b:.1f}PB"


def bar(percent: float, width: int = 20) -> str:
    filled = int(width * percent / 100)
    empty = width - filled
    return "[" + "█" * filled + "░" * empty + "]"


# ============================================================
# ANSI Colors
# ============================================================

class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    BG_BLACK = "\033[40m"

    @staticmethod
    def colorize(text: str, color: str) -> str:
        return f"{color}{text}{C.RESET}"

    @staticmethod
    def percent_color(pct: float) -> str:
        if pct < 50:
            return C.GREEN
        elif pct < 80:
            return C.YELLOW
        return C.RED


# ============================================================
# CLI Monitor
# ============================================================

def clear_screen():
    os.system("cls" if sys.platform == "win32" else "clear")


def print_header(session: MonitorSession):
    print(f"{C.BOLD}{C.CYAN}  ╔══════════════════════════════════════════════╗{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}  ║        SysMon - System Resource Monitor      ║{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}  ╚══════════════════════════════════════════════╝{C.RESET}")
    print(f"  {C.DIM}Host: {session.hostname}  |  OS: {session.os_info}  |  CPUs: {session.cpu_count}{C.RESET}")
    print(f"  {C.DIM}Started: {session.start_time}  |  Samples: {len(session.snapshots)}{C.RESET}")
    print()


def print_metric(label: str, percent: float, detail: str):
    color = C.percent_color(percent)
    bar_str = bar(percent, 25)
    print(f"  {C.BOLD}{label:<8}{C.RESET}  {C.colorize(bar_str, color)}  {C.colorize(f'{percent:5.1f}%', color)}  {C.DIM}{detail}{C.RESET}")


def print_snapshot(snap: Snapshot, net_delta_sent: int, net_delta_recv: int):
    print_metric("CPU", snap.cpu_percent, f"{snap.process_count} processes")
    print_metric("Memory", snap.mem_percent, f"{fmt_bytes(snap.mem_used)} / {fmt_bytes(snap.mem_total)}")
    print_metric("Disk", snap.disk_percent, f"{fmt_bytes(snap.disk_used)} / {fmt_bytes(snap.disk_total)}")

    # Network
    print()
    print(f"  {C.BOLD}Network{C.RESET}  ↑ {C.CYAN}{fmt_bytes(net_delta_sent)}/s{C.RESET}   ↓ {C.GREEN}{fmt_bytes(net_delta_recv)}/s{C.RESET}   {C.DIM}(cumulative: ↑{fmt_bytes(snap.net_sent)} ↓{fmt_bytes(snap.net_recv)}){C.RESET}")
    print()
    print(f"  {C.DIM}Press Ctrl+C to stop monitoring and generate report{C.RESET}")


# ============================================================
# HTML Report Generator (SVG charts, zero dependencies)
# ============================================================

def generate_svg_line(data: List[float], width: int = 600, height: int = 200, color: str = "#58a6ff", label: str = "") -> str:
    if not data or len(data) < 2:
        return ""
    max_val = max(max(data), 1)
    min_val = min(data)
    padding = 40
    chart_w = width - padding * 2
    chart_h = height - padding * 2

    points = []
    for i, v in enumerate(data):
        x = padding + (i / (len(data) - 1)) * chart_w
        y = padding + chart_h - (v / max_val) * chart_h if max_val > 0 else padding + chart_h / 2
        points.append(f"{x:.1f},{y:.1f}")

    polyline = " ".join(points)

    # Grid lines
    grid = ""
    for i in range(5):
        y = padding + (i / 4) * chart_h
        val = max_val * (1 - i / 4)
        grid += f'<line x1="{padding}" y1="{y:.0f}" x2="{width - padding}" y2="{y:.0f}" stroke="rgba(255,255,255,0.06)" stroke-width="0.5"/>\n'
        grid += f'<text x="{padding - 5}" y="{y + 4:.0f}" fill="rgba(255,255,255,0.3)" font-size="10" text-anchor="end">{val:.0f}</text>\n'

    return f'''<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg" style="background:transparent">
  <text x="{width/2}" y="18" fill="rgba(255,255,255,0.5)" font-size="12" text-anchor="middle" font-family="monospace">{label}</text>
  {grid}
  <polyline points="{polyline}" fill="none" stroke="{color}" stroke-width="1.5"/>
</svg>'''


def generate_html_report(session: MonitorSession) -> str:
    cpu_data = [s["cpu_percent"] for s in session.snapshots]
    mem_data = [s["mem_percent"] for s in session.snapshots]
    disk_data = [s["disk_percent"] for s in session.snapshots]
    net_sent = [s["net_sent"] for s in session.snapshots]
    net_recv = [s["net_recv"] for s in session.snapshots]

    # Delta for net
    net_sent_d = [max(0, net_sent[i] - net_sent[i-1]) for i in range(1, len(net_sent))]
    net_recv_d = [max(0, net_recv[i] - net_recv[i-1]) for i in range(1, len(net_recv))]

    avg_cpu = sum(cpu_data) / len(cpu_data) if cpu_data else 0
    max_cpu = max(cpu_data) if cpu_data else 0
    avg_mem = sum(mem_data) / len(mem_data) if mem_data else 0
    max_mem = max(mem_data) if mem_data else 0

    cpu_svg = generate_svg_line(cpu_data, color="#58a6ff", label="CPU Usage %")
    mem_svg = generate_svg_line(mem_data, color="#3fb950", label="Memory Usage %")
    disk_svg = generate_svg_line(disk_data, color="#f0883e", label="Disk Usage %")

    snapshots_json = json.dumps(session.snapshots)

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>SysMon Report - {session.hostname}</title>
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{background:#0d1117;color:#e6edf3;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',monospace;line-height:1.6;padding:40px 20px}}
  .container{{max-width:800px;margin:0 auto}}
  h1{{font-size:1.5rem;font-weight:300;letter-spacing:.1em;margin-bottom:8px}}
  .meta{{color:rgba(255,255,255,0.4);font-size:.8rem;margin-bottom:40px;letter-spacing:.05em}}
  .stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:0;border:1px solid rgba(255,255,255,0.08);margin-bottom:40px}}
  .stat{{padding:24px 16px;text-align:center;border-right:1px solid rgba(255,255,255,0.08)}}
  .stat:last-child{{border-right:none}}
  .stat .num{{font-size:1.8rem;font-weight:200;color:#58a6ff}}
  .stat .label{{font-size:.65rem;color:rgba(255,255,255,0.4);letter-spacing:.15em;text-transform:uppercase;margin-top:4px}}
  .chart{{margin-bottom:30px;padding:20px;border:1px solid rgba(255,255,255,0.06)}}
  .chart svg{{width:100%;height:auto}}
  table{{width:100%;border-collapse:collapse;font-size:.8rem;margin-top:40px}}
  th{{color:rgba(255,255,255,0.4);font-weight:400;text-align:left;padding:8px 12px;border-bottom:1px solid rgba(255,255,255,0.08);letter-spacing:.1em;text-transform:uppercase;font-size:.65rem}}
  td{{padding:8px 12px;border-bottom:1px solid rgba(255,255,255,0.04);color:rgba(255,255,255,0.7)}}
  tr:hover td{{background:rgba(255,255,255,0.02)}}
  .pct{{font-family:monospace}}
  .pct-low{{color:#3fb950}}.pct-mid{{color:#f0883e}}.pct-high{{color:#f85149}}
  .footer{{text-align:center;margin-top:60px;padding-top:20px;border-top:1px solid rgba(255,255,255,0.06);color:rgba(255,255,255,0.3);font-size:.7rem;letter-spacing:.1em}}
</style>
</head>
<body>
<div class="container">
  <h1>SysMon Report</h1>
  <p class="meta">
    {session.hostname} &middot; {session.os_info} &middot; {session.cpu_count} CPUs &middot;
    {session.start_time} → {session.end_time} &middot; {len(session.snapshots)} samples
  </p>

  <div class="stats">
    <div class="stat"><div class="num">{avg_cpu:.1f}%</div><div class="label">Avg CPU</div></div>
    <div class="stat"><div class="num">{max_cpu:.1f}%</div><div class="label">Peak CPU</div></div>
    <div class="stat"><div class="num">{avg_mem:.1f}%</div><div class="label">Avg Memory</div></div>
    <div class="stat"><div class="num">{max_mem:.1f}%</div><div class="label">Peak Memory</div></div>
  </div>

  <div class="chart">{cpu_svg}</div>
  <div class="chart">{mem_svg}</div>
  <div class="chart">{disk_svg}</div>

  <h2 style="font-size:.9rem;font-weight:400;letter-spacing:.1em;margin-top:50px;margin-bottom:16px">SAMPLE DATA</h2>
  <table>
    <tr><th>#</th><th>Time</th><th>CPU</th><th>Memory</th><th>Disk</th><th>Net Sent</th><th>Net Recv</th></tr>
    {"".join(f'<tr><td>{i+1}</td><td>{s["timestamp"]}</td><td class="pct">{s["cpu_percent"]}%</td><td class="pct">{s["mem_percent"]}%</td><td class="pct">{s["disk_percent"]}%</td><td>{fmt_bytes(s["net_sent"])}</td><td>{fmt_bytes(s["net_recv"])}</td></tr>' for i, s in enumerate(session.snapshots) if i % max(1, len(session.snapshots) // 50) == 0 or i == len(session.snapshots) - 1)}
  </table>

  <p class="footer">Generated by SysMon &middot; {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
</div>
</body>
</html>'''


# ============================================================
# Main Monitor Loop
# ============================================================

def monitor(interval: float = 1.0, count: Optional[int] = None, output: str = "report.html", cli: bool = True):
    session = MonitorSession(
        start_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        hostname=platform.node(),
        os_info=f"{platform.system()} {platform.release()}",
        cpu_count=get_cpu_count(),
    )

    snapshots: List[Snapshot] = []
    prev_net = get_net_io()
    sample = 0

    print(f"\n  {C.CYAN}SysMon starting... interval={interval}s, count={'unlimited' if count is None else count}{C.RESET}\n")

    try:
        while True:
            sample += 1
            if count and sample > count:
                break

            cpu = get_cpu_percent(interval=max(0.1, interval * 0.4))
            mem = get_memory()
            disk = get_disk_usage()
            net = get_net_io()
            procs = get_process_count()

            snap = Snapshot(
                timestamp=datetime.now().strftime("%H:%M:%S"),
                cpu_percent=cpu,
                mem_total=mem["total"],
                mem_used=mem["used"],
                mem_percent=mem["percent"],
                disk_total=disk["total"],
                disk_used=disk["used"],
                disk_percent=disk["percent"],
                net_sent=net["bytes_sent"],
                net_recv=net["bytes_recv"],
                process_count=procs,
            )
            snapshots.append(snap)

            net_delta_sent = net["bytes_sent"] - prev_net["bytes_sent"]
            net_delta_recv = net["bytes_recv"] - prev_net["bytes_recv"]
            prev_net = net

            if cli:
                clear_screen()
                print_header(session)
                print_snapshot(snap, net_delta_sent, net_delta_recv)

            # Store for report
            session.snapshots.append(asdict(snap))

            # Sleep remaining interval
            elapsed = interval * 0.4  # already slept during cpu measurement
            remaining = max(0, interval - elapsed)
            if remaining > 0:
                time.sleep(remaining)

    except KeyboardInterrupt:
        pass

    session.end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not snapshots:
        print(f"\n  {C.YELLOW}No data collected.{C.RESET}")
        return

    # Save JSON
    json_path = output.replace(".html", ".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(asdict(session), f, ensure_ascii=False, indent=2)

    # Save HTML
    html = generate_html_report(session)
    with open(output, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n  {C.GREEN}Monitoring complete!{C.RESET}")
    print(f"  {C.DIM}Samples: {len(snapshots)} | Duration: {session.start_time} → {session.end_time}{C.RESET}")
    print(f"  {C.CYAN}HTML Report: {os.path.abspath(output)}{C.RESET}")
    print(f"  {C.CYAN}JSON Data:   {os.path.abspath(json_path)}{C.RESET}\n")


# ============================================================
# CLI Entry Point
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="SysMon - System Resource Monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python sysmon.py                      # Monitor indefinitely
  python sysmon.py -n 60                # Monitor for 60 samples
  python sysmon.py -i 2 -n 30           # Every 2s, 30 samples
  python sysmon.py --no-cli -n 100      # Background mode, generate report
  python sysmon.py -o my_report.html    # Custom output file
        """
    )
    parser.add_argument("-i", "--interval", type=float, default=1.0, help="Sampling interval in seconds (default: 1.0)")
    parser.add_argument("-n", "--count", type=int, default=None, help="Number of samples (default: unlimited)")
    parser.add_argument("-o", "--output", default="report.html", help="Output HTML report path (default: report.html)")
    parser.add_argument("--no-cli", action="store_true", help="Disable CLI display, only generate report")
    parser.add_argument("--json-only", action="store_true", help="Only output JSON, skip HTML")

    args = parser.parse_args()

    monitor(
        interval=args.interval,
        count=args.count,
        output=args.output,
        cli=not args.no_cli,
    )


if __name__ == "__main__":
    main()
