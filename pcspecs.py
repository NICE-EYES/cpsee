#!/usr/bin/env python3
"""PC Specs — минималистичная утилита сведений о железе в духе CPU-Z.

Вкладки: Процессор · Плата · Память (слоты) · Диски · Видеокарта · Оверлей.
Windows: PowerShell/CIM + nvidia-smi. Linux: /sys, lscpu, lsblk, dmidecode.
Зависимость: psutil.
"""
import atexit
import ctypes
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time

try:
    import tkinter as tk
    from tkinter import colorchooser, filedialog, messagebox
except ImportError:  # без tkinter работает только --dump
    tk = None

try:
    import psutil
except ImportError:
    sys.exit("Установите зависимости:  pip install psutil")

IS_WIN = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"
NA = "—"
APP_NAME = "PC Specs"


# ───────────────────────────── утилиты ─────────────────────────────
def resource(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def run(cmd, timeout=20):
    flags = subprocess.CREATE_NO_WINDOW if IS_WIN else 0
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                           creationflags=flags, errors="replace", encoding="utf-8" if IS_WIN else None)
        return p.stdout.strip()
    except Exception:
        return ""


def ps_json(script):
    out = run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
               "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + script], timeout=40)
    try:
        return json.loads(out)
    except Exception:
        return None


def as_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def fmt_bytes(n):
    if n is None:
        return NA
    n = float(n)
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if n < 1024 or unit == "ТБ":
            return f"{n:.0f} {unit}" if unit in ("Б", "КБ", "МБ") else f"{n:.1f} {unit}".replace(".0 ", " ")
        n /= 1024


def read(path):
    try:
        with open(path, "r", errors="replace") as f:
            return f.read().strip()
    except Exception:
        return ""


def s(v):
    v = "" if v is None else str(v).strip()
    return v if v and v.lower() not in ("none", "null", "[n/a]", "n/a", "[not supported]", "to be filled by o.e.m.",
                                         "default string", "not specified") else NA


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ───────────────────────────── процессор ─────────────────────────────
def cpu_flags():
    fl = set()
    if IS_WIN:
        try:
            k = ctypes.windll.kernel32.IsProcessorFeaturePresent
            for pf, name in ((38, "sse4_2"), (39, "avx"), (40, "avx2"), (41, "avx512f")):
                if k(pf):
                    fl.add(name)
        except Exception:
            pass
    elif IS_LINUX:
        m = re.search(r"^flags\s*:\s*(.*)$", read("/proc/cpuinfo"), re.M)
        fl = set(m.group(1).split()) if m else set()
    names = [("sse4_2", "SSE4.2"), ("avx", "AVX"), ("avx2", "AVX2"), ("avx512f", "AVX-512"), ("fma", "FMA3"),
             ("aes", "AES"), ("sha_ni", "SHA"), ("vmx", "VT-x"), ("svm", "AMD-V"), ("amx_tile", "AMX")]
    return ", ".join(n for k, n in names if k in fl) or NA


def collect_cpu():
    d = {"name": platform.processor() or NA, "vendor": NA, "socket": NA, "family": NA, "arch": platform.machine(),
         "cores": psutil.cpu_count(logical=False), "threads": psutil.cpu_count(logical=True),
         "base_mhz": None, "max_mhz": None, "min_mhz": None, "bus_mhz": None, "multiplier": None,
         "volt": None, "l1": NA, "l2": NA, "l3": NA, "virt": NA, "flags": cpu_flags(), "stepping": NA,
         "packages": 1}
    if IS_WIN:
        r = ps_json("$p=@(Get-CimInstance Win32_Processor|Select Name,Manufacturer,SocketDesignation,NumberOfCores,"
                    "NumberOfLogicalProcessors,MaxClockSpeed,ExtClock,L2CacheSize,L3CacheSize,Caption,"
                    "VirtualizationFirmwareEnabled,CurrentVoltage,Revision,Stepping);"
                    "$c=@(Get-CimInstance Win32_CacheMemory|Select Level,InstalledSize);"
                    "@{p=$p;c=$c}|ConvertTo-Json -Compress -Depth 4") or {}
        p = as_list(r.get("p"))
        if p:
            c = p[0]
            kb = lambda v: f"{v / 1024:g} МБ" if v else NA
            l1 = sum(x.get("InstalledSize") or 0 for x in as_list(r.get("c")) if x.get("Level") == 3)
            base, ext = c.get("MaxClockSpeed"), c.get("ExtClock")
            volt = c.get("CurrentVoltage")
            d.update(name=s(c.get("Name")), vendor=s(c.get("Manufacturer")), socket=s(c.get("SocketDesignation")),
                     family=s(c.get("Caption")), cores=sum(x.get("NumberOfCores") or 0 for x in p),
                     threads=sum(x.get("NumberOfLogicalProcessors") or 0 for x in p), base_mhz=base,
                     bus_mhz=ext or None, multiplier=(base / ext) if base and ext else None,
                     volt=(volt & 0x7F) / 10 if isinstance(volt, int) and volt & 0x80 else None,
                     l1=f"{l1} КБ (всего)" if l1 else NA, l2=kb(c.get("L2CacheSize")), l3=kb(c.get("L3CacheSize")),
                     stepping=s(c.get("Stepping")), packages=len(p),
                     virt="Включена" if c.get("VirtualizationFirmwareEnabled") else "Выключена")
    elif IS_LINUX:
        lc = {}
        for line in run(["lscpu"]).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                lc[k.strip()] = v.strip()
        d.update(name=s(lc.get("Model name")), vendor=s(lc.get("Vendor ID")), stepping=s(lc.get("Stepping")),
                 family=f'Family {lc.get("CPU family", "?")}, Model {lc.get("Model", "?")}',
                 l1=(lc.get("L1d cache", NA) + " (данные)") if lc.get("L1d cache") else NA,
                 l2=s(lc.get("L2 cache")), l3=s(lc.get("L3 cache")), virt=s(lc.get("Virtualization")),
                 max_mhz=num(lc.get("CPU max MHz")), min_mhz=num(lc.get("CPU min MHz")))
        dmi = run(["dmidecode", "-t", "processor"]) if os.geteuid() == 0 else ""
        m = re.search(r"Upgrade:\s*(.+)", dmi)
        d["socket"] = m.group(1).strip() if m else "нужен root (sudo)"
        m = re.search(r"External Clock:\s*(\d+)", dmi)
        d["bus_mhz"] = float(m.group(1)) if m else None
        m = re.search(r"Current Speed:\s*(\d+)", dmi)
        d["base_mhz"] = float(m.group(1)) if m else None
    f = psutil.cpu_freq()
    if f and not d["max_mhz"]:
        d["max_mhz"] = f.max or None
    return d


# ───────────────────────────── плата, ОЗУ, диски ─────────────────────────────
def collect_board():
    d = {"os": f"{platform.system()} {platform.release()}", "host": platform.node(), "maker": NA, "model": NA,
         "serial": NA, "bios_vendor": NA, "bios_ver": NA, "bios_date": NA}
    if IS_WIN:
        r = ps_json("$b=Get-CimInstance Win32_BaseBoard|Select Manufacturer,Product,SerialNumber;"
                    "$i=Get-CimInstance Win32_BIOS|Select Manufacturer,SMBIOSBIOSVersion,ReleaseDate;"
                    "$o=Get-CimInstance Win32_OperatingSystem|Select Caption,OSArchitecture,BuildNumber;"
                    "@{b=$b;i=$i;o=$o}|ConvertTo-Json -Compress -Depth 3")
        if r:
            b, i, o = r.get("b") or {}, r.get("i") or {}, r.get("o") or {}
            raw = str(i.get("ReleaseDate") or "")
            m = re.search(r"(\d{4})(\d{2})(\d{2})", raw)
            if not m:  # формат /Date(…)/
                ms = re.search(r"\d{10,}", raw)
                date = time.strftime("%d.%m.%Y", time.gmtime(int(ms.group()) / 1000)) if ms else NA
            else:
                date = f"{m[3]}.{m[2]}.{m[1]}"
            d.update(maker=s(b.get("Manufacturer")), model=s(b.get("Product")), serial=s(b.get("SerialNumber")),
                     bios_vendor=s(i.get("Manufacturer")), bios_ver=s(i.get("SMBIOSBIOSVersion")), bios_date=date,
                     os=f'{s(o.get("Caption"))} {s(o.get("OSArchitecture"))} (сборка {s(o.get("BuildNumber"))})')
    elif IS_LINUX:
        g = lambda n: s(read(f"/sys/class/dmi/id/{n}"))
        d.update(maker=g("board_vendor"), model=g("board_name"), serial=g("board_serial"),
                 bios_vendor=g("bios_vendor"), bios_ver=g("bios_version"), bios_date=g("bios_date"))
        osr = {k: v.strip('"') for k, v in (l.split("=", 1) for l in read("/etc/os-release").splitlines() if "=" in l)}
        d["os"] = f'{osr.get("PRETTY_NAME", "Linux")} (ядро {platform.release()})'
    return d


MEM_TYPES = {20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4", 34: "DDR5", 35: "LPDDR5"}
MEM_FORMS = {8: "DIMM", 12: "SO-DIMM"}
ECC = {3: "Нет", 4: "Контроль чётности", 5: "Single-bit ECC", 6: "Multi-bit ECC", 7: "CRC"}
JEDEC_TOP = {"DDR3": 1600, "DDR4": 3200, "DDR5": 4800}


def place_modules(mods, n):
    """Разложить модули по слотам: по номеру в имени слота (DIMM1/ChannelA-DIMM0), иначе по порядку."""
    slots = [None] * n
    nums = [re.findall(r"(\d+)\D*$", m["slot"]) for m in mods]
    if mods and all(nums):
        idx = [int(x[0]) for x in nums]
        base = 0 if min(idx) == 0 else 1
        pos = [i - base for i in idx]
        if len(set(pos)) == len(pos) and all(0 <= p < n for p in pos):
            for m, p in zip(mods, pos):
                slots[p] = m
            return slots
    for i, m in enumerate(mods[:n]):
        slots[i] = m
    return slots


def ram_profile(m):
    """Оценка: работает ли память на профиле XMP/EXPO или разогнана."""
    rated, cur, t = m.get("rated"), m.get("current"), m.get("type")
    if not rated or not cur:
        return NA
    if cur < rated * 0.97:
        return f"Работает на {cur} из {rated} МТ/с — XMP/EXPO, вероятно, не включён"
    if cur > rated * 1.03:
        return f"Разгон: +{(cur / rated - 1) * 100:.0f} % к номиналу ({rated} МТ/с)"
    if cur > JEDEC_TOP.get(t, 10 ** 9):
        return "Профиль XMP/EXPO активен (вероятно)"
    return "Штатный режим (JEDEC)"


def collect_ram():
    vm = psutil.virtual_memory()
    d = {"total": vm.total, "modules": [], "slots": [], "slots_total": None, "max_cap": None, "ecc": NA}
    if IS_WIN:
        r = ps_json("$m=@(Get-CimInstance Win32_PhysicalMemory|Select BankLabel,DeviceLocator,Capacity,Speed,"
                    "ConfiguredClockSpeed,Manufacturer,PartNumber,SMBIOSMemoryType,FormFactor,ConfiguredVoltage,"
                    "MinVoltage,MaxVoltage,DataWidth,TotalWidth,Attributes,SerialNumber);"
                    "$a=@(Get-CimInstance Win32_PhysicalMemoryArray|Select MemoryDevices,MaxCapacityEx,MaxCapacity,"
                    "MemoryErrorCorrection);@{m=$m;a=$a}|ConvertTo-Json -Compress -Depth 4") or {}
        arr = as_list(r.get("a"))
        if arr:
            d["slots_total"] = sum(a.get("MemoryDevices") or 0 for a in arr) or None
            cap = sum((a.get("MaxCapacityEx") or (a.get("MaxCapacity") or 0)) for a in arr)
            d["max_cap"] = cap * 1024 if cap else None
            d["ecc"] = ECC.get(arr[0].get("MemoryErrorCorrection"), NA)
        for m in as_list(r.get("m")):
            v = lambda k: (m.get(k) or 0) / 1000 or None
            d["modules"].append({
                "slot": s(m.get("DeviceLocator")), "bank": s(m.get("BankLabel")), "size": m.get("Capacity"),
                "type": MEM_TYPES.get(m.get("SMBIOSMemoryType"), NA), "form": MEM_FORMS.get(m.get("FormFactor"), NA),
                "rated": m.get("Speed"), "current": m.get("ConfiguredClockSpeed"), "maker": s(m.get("Manufacturer")),
                "part": s(m.get("PartNumber")), "serial": s(m.get("SerialNumber")), "volt": v("ConfiguredVoltage"),
                "vmin": v("MinVoltage"), "vmax": v("MaxVoltage"),
                "width": f'{m.get("DataWidth")} бит' + (f' (шина {m.get("TotalWidth")})' if m.get("TotalWidth") != m.get("DataWidth") else "") if m.get("DataWidth") else NA,
                "rank": (m.get("Attributes") or 0) & 0xF or None})
        n = d["slots_total"] or len(d["modules"])
        d["slots"] = place_modules(d["modules"], n)
    elif IS_LINUX and os.geteuid() == 0:
        out = run(["dmidecode", "-t", "memory"])
        mc = re.search(r"Maximum Capacity:\s*(\d+)\s*(GB|MB|TB)", out)
        if mc:
            d["max_cap"] = int(mc[1]) * {"MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}[mc[2]]
        ec = re.search(r"Error Correction Type:\s*(.+)", out)
        d["ecc"] = ec[1].strip() if ec else NA
        for blk in out.split("\n\n"):
            if "Memory Device" not in blk:
                continue
            kv = dict(re.findall(r"^\s*([\w ]+):\s*(.+)$", blk, re.M))
            if kv.get("Size", "").startswith("No Module"):
                d["slots"].append(None)
                continue
            sz = re.match(r"(\d+)\s*(MB|GB)", kv.get("Size", ""))
            size = int(sz[1]) * (1024 ** 3 if sz[2] == "GB" else 1024 ** 2) if sz else None
            sp = re.match(r"(\d+)", kv.get("Speed", ""))
            cs = re.match(r"(\d+)", kv.get("Configured Memory Speed", kv.get("Configured Clock Speed", "")))
            vv = lambda k: num(re.sub(r"[^\d.]", "", kv.get(k, "")))
            m = {"slot": s(kv.get("Locator")), "bank": s(kv.get("Bank Locator")), "size": size,
                 "type": s(kv.get("Type")), "form": s(kv.get("Form Factor")), "rated": int(sp[1]) if sp else None,
                 "current": int(cs[1]) if cs else None, "maker": s(kv.get("Manufacturer")),
                 "part": s(kv.get("Part Number")), "serial": s(kv.get("Serial Number")),
                 "volt": vv("Configured Voltage"), "vmin": vv("Minimum Voltage"), "vmax": vv("Maximum Voltage"),
                 "width": s(kv.get("Data Width")), "rank": int(kv["Rank"]) if kv.get("Rank", "").isdigit() else None}
            d["modules"].append(m)
            d["slots"].append(m)
        d["slots_total"] = len(d["slots"]) or None
    return d


def collect_disks():
    disks = []
    if IS_WIN:
        pd = as_list(ps_json("Get-PhysicalDisk | Select FriendlyName,MediaType,BusType,Size,HealthStatus,"
                             "SerialNumber,FirmwareVersion,SpindleSpeed | ConvertTo-Json -Compress"))
        for x in pd:
            media, bus = s(x.get("MediaType")), s(x.get("BusType"))
            kind = "NVMe SSD" if bus == "NVMe" else "SSD" if media == "SSD" else "HDD" if media == "HDD" else media
            disks.append({"name": s(x.get("FriendlyName")), "kind": kind, "bus": bus, "size": x.get("Size"),
                          "health": s(x.get("HealthStatus")), "serial": s(x.get("SerialNumber")),
                          "fw": s(x.get("FirmwareVersion")),
                          "rpm": x.get("SpindleSpeed") if x.get("SpindleSpeed") not in (None, 0, 4294967295) else None})
    elif IS_LINUX:
        try:
            data = json.loads(run(["lsblk", "-J", "-b", "-d", "-o", "NAME,MODEL,SIZE,ROTA,TRAN,TYPE,SERIAL,REV"]))
        except Exception:
            data = {}
        for x in data.get("blockdevices", []):
            if x.get("type") != "disk" or x["name"].startswith(("loop", "zram", "ram")):
                continue
            tran = s(x.get("tran"))
            rota = x.get("rota") in (True, 1, "1")
            kind = "NVMe SSD" if x["name"].startswith("nvme") else "HDD" if rota else "SSD"
            disks.append({"name": s(x.get("model")) if s(x.get("model")) != NA else x["name"], "kind": kind,
                          "bus": tran.upper() if tran != NA else NA, "size": int(x.get("size") or 0),
                          "health": NA, "serial": s(x.get("serial")), "fw": s(x.get("rev")), "rpm": None})
    parts = []
    for p in psutil.disk_partitions(all=False):
        if IS_WIN and ("cdrom" in p.opts or not p.fstype):
            continue
        try:
            u = psutil.disk_usage(p.mountpoint)
        except Exception:
            continue
        parts.append({"mount": p.mountpoint, "fs": p.fstype, "total": u.total, "used": u.used, "pct": u.percent})
    return disks, parts


# ───────────────────────────── видеокарта ─────────────────────────────
NV_FIELDS = ["name", "driver_version", "memory.total", "memory.used", "temperature.gpu", "utilization.gpu",
             "clocks.gr", "clocks.max.gr", "clocks.mem", "clocks.max.mem", "power.draw", "power.limit",
             "pcie.link.gen.current", "pcie.link.gen.max", "pcie.link.width.current", "vbios_version",
             "fan.speed", "pci.bus_id"]
NV_EXTRA = ["compute_cap", "driver_model.current", "power.default_limit", "power.max_limit",
            "clocks.default_applications.graphics", "clocks.default_applications.memory"]


def nvidia_exe():
    exe = shutil.which("nvidia-smi")
    if not exe and IS_WIN:
        for p in (r"C:\Windows\System32\nvidia-smi.exe",
                  r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"):
            if os.path.exists(p):
                return p
    return exe


def nvidia_query(fields=NV_FIELDS):
    exe = nvidia_exe()
    if not exe:
        return []
    out = run([exe, f"--query-gpu={','.join(fields)}", "--format=csv,noheader,nounits"], timeout=8)
    res = []
    for line in out.splitlines():
        vals = [v.strip() for v in line.split(",")]
        if len(vals) == len(fields):
            res.append(dict(zip(fields, vals)))
    return res


def collect_gpus():
    gpus = []
    nv = nvidia_query()
    extras = [{} for _ in nv]
    for f in NV_EXTRA:  # по одному: неизвестное поле не должно ломать остальные
        for i, row in enumerate(nvidia_query([f])[:len(nv)]):
            extras[i][f] = row[f]
    for i, g in enumerate(nv):
        e = extras[i]
        gpus.append({"vendor": "NVIDIA", "nv_index": i, "name": g["name"], "driver": g["driver_version"],
                     "vram": float(g["memory.total"]) * 1024 ** 2 if num(g["memory.total"]) else None,
                     "vbios": s(g["vbios_version"]), "bus": s(g["pci.bus_id"]),
                     "pcie": f'PCIe Gen{s(g["pcie.link.gen.max"])} x{s(g["pcie.link.width.current"])} '
                             f'(сейчас Gen{s(g["pcie.link.gen.current"])})',
                     "compute": s(e.get("compute_cap")), "drv_model": s(e.get("driver_model.current")),
                     "tdp": s(g["power.limit"]), "tdp_def": s(e.get("power.default_limit")),
                     "tdp_max": s(e.get("power.max_limit")), "max_core": s(g["clocks.max.gr"]),
                     "max_mem": s(g["clocks.max.mem"]), "def_core": s(e.get("clocks.default_applications.graphics")),
                     "def_mem": s(e.get("clocks.default_applications.memory"))})
    if IS_WIN:
        raw = ps_json(
            "$vc=@(Get-CimInstance Win32_VideoController|Select Name,AdapterCompatibility,DriverVersion,DriverDate,"
            "VideoProcessor,CurrentHorizontalResolution,CurrentVerticalResolution,CurrentRefreshRate,AdapterRAM);"
            "$k='HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Class\\{4d36e968-e325-11ce-bfc1-08002be10318}\\0*';"
            "$m=@(Get-ItemProperty $k -ErrorAction SilentlyContinue|Where-Object{$_.'HardwareInformation.qwMemorySize'}|"
            "ForEach-Object{@{n=$_.DriverDesc;m=[uint64]$_.'HardwareInformation.qwMemorySize'}});"
            "@{vc=$vc;m=$m}|ConvertTo-Json -Compress -Depth 4") or {}
        vram_by_name = {x["n"]: x["m"] for x in as_list(raw.get("m"))}
        for v in as_list(raw.get("vc")):
            name = s(v.get("Name"))
            res = (f'{v.get("CurrentHorizontalResolution")}×{v.get("CurrentVerticalResolution")} '
                   f'@ {v.get("CurrentRefreshRate")} Гц') if v.get("CurrentHorizontalResolution") else None
            known = next((g for g in gpus if g["name"] == name), None)
            if known:
                known["res"] = res
                known["chip"] = s(v.get("VideoProcessor"))
                continue
            gpus.append({"vendor": s(v.get("AdapterCompatibility")), "name": name, "driver": s(v.get("DriverVersion")),
                         "vram": vram_by_name.get(name) or v.get("AdapterRAM"), "chip": s(v.get("VideoProcessor")),
                         "res": res})
    elif IS_LINUX:
        for line in run(["lspci", "-mm"]).splitlines():
            if re.search(r'"(VGA compatible|3D|Display) controller"', line):
                parts = re.findall(r'"([^"]*)"', line)
                if len(parts) >= 4 and not any(g["name"] in parts[2] + parts[3] for g in gpus):
                    gpu = {"vendor": parts[1], "name": f"{parts[1]} {parts[2]}", "bus": line.split()[0], "driver": NA}
                    for card in sorted(os.listdir("/sys/class/drm")) if os.path.isdir("/sys/class/drm") else []:
                        t = read(f"/sys/class/drm/{card}/device/mem_info_vram_total")
                        if t.isdigit():
                            gpu["vram"] = int(t)
                            break
                    gpus.append(gpu)
    return gpus


# ───────────────────────────── живые показатели ─────────────────────────────
class WinPerf:
    """Постоянный PowerShell: реальная частота (% Processor Performance) и температура ACPI."""
    SCRIPT = (
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
        "while($true){$p=$null;$t=$null;"
        "try{$p=(Get-CimInstance Win32_PerfFormattedData_Counters_ProcessorInformation -Filter \"Name='_Total'\")"
        ".PercentProcessorPerformance}catch{};"
        "try{$t=((Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction Stop|"
        "Select -First 1).CurrentTemperature/10)-273.15}catch{};"
        "[Console]::WriteLine((@{perf=$p;temp=$t}|ConvertTo-Json -Compress));Start-Sleep -Milliseconds 600}")

    def __init__(self):
        self.latest = {}
        self.proc = None
        if not IS_WIN:
            return
        try:
            self.proc = subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command", self.SCRIPT],
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                                         text=True, encoding="utf-8", errors="replace",
                                         creationflags=subprocess.CREATE_NO_WINDOW)
            threading.Thread(target=self._reader, daemon=True).start()
            atexit.register(self.stop)
        except Exception:
            self.proc = None

    def _reader(self):
        for line in self.proc.stdout:
            try:
                self.latest = json.loads(line)
            except Exception:
                pass

    def stop(self):
        try:
            self.proc.kill()
        except Exception:
            pass


class Poller(threading.Thread):
    def __init__(self, data):
        super().__init__(daemon=True)
        self.data = data
        self.live = {}
        self.perf = WinPerf()
        self.max_freq = 0.0
        psutil.cpu_percent(interval=None, percpu=True)

    def run(self):
        while True:
            try:
                self.live = self.poll()
            except Exception:
                pass
            time.sleep(1.0)

    def poll(self):
        L = {"time": time.strftime("%H:%M:%S")}
        cores = psutil.cpu_percent(interval=None, percpu=True)
        L["cpu_pct"] = sum(cores) / len(cores) if cores else 0
        for i, v in enumerate(cores):
            L[f"core{i}"] = v
        L["cpu_load"] = f'{L["cpu_pct"]:.0f} %'
        base = self.data["cpu"]["base_mhz"]
        perf = (self.perf.latest or {}).get("perf")
        f = psutil.cpu_freq()
        cur = base * perf / 100 if base and perf else (f.current if f else None)
        L["cpu_freq"] = f"{cur:.0f} МГц" if cur else NA
        if cur:
            self.max_freq = max(self.max_freq, cur)
            L["cpu_max_seen"] = f"{self.max_freq:.0f} МГц"
            ref = base or self.data["cpu"]["max_mhz"]
            if ref:
                r = cur / ref
                L["cpu_oc"] = (f"Выше базовой на {(r - 1) * 100:.0f} % (буст / разгон)" if r > 1.03
                               else "Простой (энергосбережение)" if r < 0.85 else "Около базовой частоты")
        t = (self.perf.latest or {}).get("temp")
        if t is None:
            try:
                temps = psutil.sensors_temperatures()
                t = next((v[0].current for k, v in temps.items() if k in ("coretemp", "k10temp", "zenpower") and v), None)
            except Exception:
                t = None
        L["cpu_temp"] = f"{t:.0f} °C" if t else NA
        vm, sw = psutil.virtual_memory(), psutil.swap_memory()
        L["ram_pct"] = vm.percent
        L["ram_pct_txt"] = f"{vm.percent:.0f} %"
        L["ram_short"] = f"{vm.used / 1024 ** 3:.1f} / {vm.total / 1024 ** 3:.0f} ГБ"
        L["ram_used"] = f"{fmt_bytes(vm.used)} / {fmt_bytes(vm.total)}  ({vm.percent:.0f} %)"
        L["ram_free"] = fmt_bytes(vm.available)
        L["swap"] = f"{fmt_bytes(sw.used)} / {fmt_bytes(sw.total)}"
        gp = self.data["gpus"]
        if any(g.get("nv_index") is not None for g in gp):
            nv = nvidia_query()
            for g in gp:
                i = g.get("nv_index")
                if i is None or i >= len(nv):
                    continue
                q = nv[i]
                n = lambda k, u="": f"{q[k]} {u}".strip() if s(q[k]) != NA else NA
                L[f"g{i}_pct"] = num(q["utilization.gpu"]) or 0
                L[f"g{i}_load"] = n("utilization.gpu", "%")
                L[f"g{i}_temp"] = n("temperature.gpu", "°C")
                L[f"g{i}_core"] = n("clocks.gr", "МГц")
                L[f"g{i}_mem"] = n("clocks.mem", "МГц")
                L[f"g{i}_power"] = (f'{num(q["power.draw"]):.0f} Вт' if num(q["power.draw"]) else NA)
                L[f"g{i}_fan"] = n("fan.speed", "%")
                L[f"g{i}_oc"] = (f'{q["clocks.gr"]} / {q["clocks.max.gr"]} МГц (ядро), '
                                 f'{q["clocks.mem"]} / {q["clocks.max.mem"]} МГц (память)')
                used, tot = num(q["memory.used"]), num(q["memory.total"])
                if used is not None and tot:
                    L[f"g{i}_vram"] = f"{used:.0f} / {tot:.0f} МБ ({used / tot * 100:.0f} %)"
                    L[f"g{i}_vram_short"] = f"{used / 1024:.1f} / {tot / 1024:.0f} ГБ"
                    L[f"g{i}_vram_pct"] = used / tot * 100
        return L


# ───────────────────────────── настройки и оверлей ─────────────────────────────
def settings_path():
    base = os.environ.get("APPDATA") if IS_WIN else os.path.expanduser("~/.config")
    return os.path.join(base or os.path.expanduser("~"), "PCSpecs", "settings.json")


DEFAULTS = {"ov_on": False, "ov_order": [], "ov_enabled": ["cpu_load", "cpu_freq", "ram", "g0_load", "g0_temp"],
            "ov_alpha": 0.85, "ov_font": 11, "ov_accent": "#5ee6a8", "ov_bg": "#0e1014", "ov_horizontal": False,
            "ov_labels": True, "ov_locked": False, "ov_x": 24, "ov_y": 24}


class Settings(dict):
    def __init__(self):
        super().__init__(DEFAULTS)
        try:
            with open(settings_path(), encoding="utf-8") as f:
                self.update(json.load(f))
        except Exception:
            pass

    def save(self):
        try:
            os.makedirs(os.path.dirname(settings_path()), exist_ok=True)
            with open(settings_path(), "w", encoding="utf-8") as f:
                json.dump(self, f, ensure_ascii=False, indent=1)
        except Exception:
            pass


def overlay_catalog(gpus):
    """[(ключ, подпись, ключ live-значения)] — всё, что можно вывести в оверлей."""
    cat = [("cpu_load", "CPU", "cpu_load"), ("cpu_freq", "CPU МГц", "cpu_freq"), ("cpu_temp", "CPU t°", "cpu_temp"),
           ("ram", "ОЗУ", "ram_short"), ("ram_pct", "ОЗУ %", "ram_pct_txt")]
    nvs = [g for g in gpus if g.get("nv_index") is not None]
    for g in nvs:
        i, p = g["nv_index"], "GPU" if len(nvs) == 1 else f'GPU{g["nv_index"] + 1}'
        cat += [(f"g{i}_load", p, f"g{i}_load"), (f"g{i}_temp", f"{p} t°", f"g{i}_temp"),
                (f"g{i}_core", f"{p} МГц", f"g{i}_core"), (f"g{i}_mem", f"{p} память МГц", f"g{i}_mem"),
                (f"g{i}_vram", f"{p} VRAM", f"g{i}_vram_short"), (f"g{i}_power", f"{p} Вт", f"g{i}_power")]
    cat.append(("time", "Время", "time"))
    return cat


BG, PANEL, PANEL2 = "#0e1014", "#161a21", "#1d222b"
FG, MUTED, ACCENT, GOOD = "#e8eaf0", "#7d8599", "#4cc9f0", "#5ee6a8"
FONT = "Segoe UI" if IS_WIN else "DejaVu Sans"
MONO = "Consolas" if IS_WIN else "DejaVu Sans Mono"


class Overlay(tk.Toplevel if tk else object):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.vars = {}
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="Закрепить / открепить", command=self.toggle_lock)
        self.menu.add_command(label="Настройки…", command=lambda: (app.deiconify(), app.show("overlay")))
        self.menu.add_separator()
        self.menu.add_command(label="Закрыть оверлей", command=lambda: app.set_overlay(False))
        self.geometry(f'+{app.cfg["ov_x"]}+{app.cfg["ov_y"]}')
        self.rebuild()

    def toggle_lock(self):
        self.app.cfg["ov_locked"] = not self.app.cfg["ov_locked"]
        self.app.cfg.save()

    def _press(self, e):
        self._off = (e.x_root - self.winfo_x(), e.y_root - self.winfo_y())

    def _drag(self, e):
        if not self.app.cfg["ov_locked"]:
            self.geometry(f"+{e.x_root - self._off[0]}+{e.y_root - self._off[1]}")

    def _release(self, e):
        self.app.cfg["ov_x"], self.app.cfg["ov_y"] = self.winfo_x(), self.winfo_y()
        self.app.cfg.save()

    def _bind_all(self, w):
        for ev, fn in (("<ButtonPress-1>", self._press), ("<B1-Motion>", self._drag),
                       ("<ButtonRelease-1>", self._release),
                       ("<Button-3>", lambda e: self.menu.tk_popup(e.x_root, e.y_root))):
            w.bind(ev, fn)
        for ch in w.winfo_children():
            self._bind_all(ch)

    def rebuild(self):
        c = self.app.cfg
        for w in self.winfo_children():
            w.destroy()
        self.vars.clear()
        try:
            self.attributes("-alpha", float(c["ov_alpha"]))
        except tk.TclError:
            pass
        self.configure(bg=c["ov_bg"])
        fs = int(c["ov_font"])
        box = tk.Frame(self, bg=c["ov_bg"], padx=12, pady=8, highlightthickness=1, highlightbackground=PANEL2)
        box.pack()
        horiz = c["ov_horizontal"]
        for key, label, live in self.app.ordered_catalog(only_enabled=True):
            row = tk.Frame(box, bg=c["ov_bg"])
            row.pack(side="left" if horiz else "top", fill=None if horiz else "x", padx=(0, 14) if horiz else 0)
            if c["ov_labels"]:
                tk.Label(row, text=label, bg=c["ov_bg"], fg=MUTED, font=(FONT, fs), anchor="w").pack(side="left")
            var = tk.StringVar(value="…")
            self.vars[live] = var
            tk.Label(row, textvariable=var, bg=c["ov_bg"], fg=c["ov_accent"], font=(MONO, fs, "bold"),
                     anchor="e", width=0 if horiz else 12).pack(side="left" if horiz else "right", padx=(8, 0))
        self._bind_all(self)
        self.tick()

    def tick(self):
        live = self.app.live
        for k, var in self.vars.items():
            var.set(str(live.get(k, "…")))


# ───────────────────────────── интерфейс ─────────────────────────────
class Live:
    def __init__(self, key):
        self.key = key


class Bar:
    def __init__(self, key):
        self.key = key


if IS_WIN:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PCSpecs.App")
    except Exception:
        pass


class App(tk.Tk if tk else object):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("920x700")
        self.minsize(800, 540)
        self.configure(bg=BG)
        try:
            self.iconbitmap(resource("pcspecs.ico"))
        except Exception:
            pass
        self.cfg = Settings()
        self.tab = None
        self.live_vars, self.bars, self.data, self.poller, self.overlay = {}, {}, None, None, None

        side = tk.Frame(self, bg=PANEL, width=180)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Label(side, text="PC SPECS", bg=PANEL, fg=ACCENT, font=(FONT, 15, "bold")).pack(pady=(22, 2))
        tk.Label(side, text="сведения о системе", bg=PANEL, fg=MUTED, font=(FONT, 9)).pack(pady=(0, 18))
        self.nav = {}
        for key, label in (("cpu", "Процессор"), ("board", "Плата и ОС"), ("ram", "Память"),
                           ("disks", "Диски"), ("gpu", "Видеокарта"), ("overlay", "Оверлей")):
            b = tk.Label(side, text=label, bg=PANEL, fg=MUTED, font=(FONT, 11), anchor="w", padx=22, pady=9,
                         cursor="hand2")
            b.pack(fill="x")
            b.bind("<Button-1>", lambda e, k=key: self.show(k))
            self.nav[key] = b
        tk.Button(side, text="Экспорт в .txt", command=self.export, bg=PANEL2, fg=FG, relief="flat",
                  activebackground=ACCENT, activeforeground=BG, font=(FONT, 9), pady=6, cursor="hand2"
                  ).pack(side="bottom", fill="x", padx=16, pady=16)

        self.main = tk.Frame(self, bg=BG)
        self.main.pack(side="left", fill="both", expand=True)
        self.status = tk.Label(self.main, text="Сбор данных…", bg=BG, fg=MUTED, font=(FONT, 12))
        self.status.pack(expand=True)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._pending = None
        threading.Thread(target=self._collect, daemon=True).start()
        self.after(100, self._wait_data)

    @property
    def live(self):
        return self.poller.live if self.poller else {}

    def on_close(self):
        self.cfg.save()
        if self.poller:
            self.poller.perf.stop()
        self.destroy()

    def _collect(self):
        disks, parts = collect_disks()
        data = {"cpu": collect_cpu(), "board": collect_board(), "ram": collect_ram(),
                "disks": disks, "parts": parts, "gpus": collect_gpus()}
        self._pending = data  # Tk из потока не трогаем — главный поток сам заберёт

    def _wait_data(self):
        if self._pending is None:
            self.after(100, self._wait_data)
        else:
            self._ready(self._pending)

    def _ready(self, data):
        self.data = data
        self.status.destroy()
        self.canvas = tk.Canvas(self.main, bg=BG, highlightthickness=0)
        sb = tk.Scrollbar(self.main, orient="vertical", command=self.canvas.yview)
        self.body = tk.Frame(self.canvas, bg=BG)
        self.win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.win, width=e.width))
        for ev, d in (("<MouseWheel>", None), ("<Button-4>", -1), ("<Button-5>", 1)):
            self.bind_all(ev, lambda e, d=d: self.canvas.yview_scroll(d if d else int(-e.delta / 120), "units"))
        self.poller = Poller(data)
        self.poller.start()
        self.show("cpu")
        if self.cfg["ov_on"]:
            self.set_overlay(True)
        self.after(800, self._apply_live)

    def _apply_live(self):
        live = self.live
        for k, var in self.live_vars.items():
            if k in live:
                var.set(live[k])
        for k, (cv, fill) in self.bars.items():
            if k in live:
                w = max(cv.winfo_width(), 1)
                cv.coords(fill, 0, 0, w * min(float(live[k]), 100) / 100, cv.winfo_height())
        if self.overlay:
            self.overlay.tick()
        self.after(1000, self._apply_live)

    # — оверлей —
    def ordered_catalog(self, only_enabled=False):
        cat = overlay_catalog(self.data["gpus"])
        pos = {k: i for i, k in enumerate(self.cfg["ov_order"])}
        natural = [x[0] for x in cat]
        cat.sort(key=lambda c: pos.get(c[0], 1000 + natural.index(c[0])))
        if only_enabled:
            cat = [c for c in cat if c[0] in self.cfg["ov_enabled"]]
        return cat

    def set_overlay(self, on):
        self.cfg["ov_on"] = on
        self.cfg.save()
        if on and not self.overlay:
            self.overlay = Overlay(self)
        elif not on and self.overlay:
            self.overlay.destroy()
            self.overlay = None
        if self.tab == "overlay":
            self.show("overlay", keep=True)

    def refresh_overlay(self):
        self.cfg.save()
        if self.overlay:
            self.overlay.rebuild()

    # — построение страниц —
    def show(self, key, keep=False):
        if not self.data:
            return
        y = self.canvas.yview()[0] if keep else 0
        self.tab = key
        for k, b in self.nav.items():
            b.configure(fg=ACCENT if k == key else MUTED, bg=PANEL2 if k == key else PANEL)
        for w in self.body.winfo_children():
            w.destroy()
        self.live_vars.clear()
        self.bars.clear()
        getattr(self, f"page_{key}")()
        self.update_idletasks()
        self.canvas.yview_moveto(y)

    def frame(self, title, headline=None, sub=None):
        f = tk.Frame(self.body, bg=PANEL, padx=20, pady=16)
        f.pack(fill="x", padx=22, pady=(18, 0))
        if headline:
            tk.Label(f, text=headline, bg=PANEL, fg=FG, font=(FONT, 15, "bold"), anchor="w", wraplength=620,
                     justify="left").pack(fill="x")
            if sub:
                tk.Label(f, text=sub, bg=PANEL, fg=MUTED, font=(FONT, 10), anchor="w").pack(fill="x", pady=(2, 8))
        tk.Label(f, text=title.upper(), bg=PANEL, fg=ACCENT, font=(FONT, 9, "bold"), anchor="w").pack(fill="x", pady=(6, 6))
        return f

    def add_bar(self, parent, key, height=8):
        cv = tk.Canvas(parent, height=height, bg=PANEL2, highlightthickness=0)
        self.bars[key] = (cv, cv.create_rectangle(0, 0, 0, height, fill=GOOD, width=0))
        return cv

    def card(self, title, rows, headline=None, sub=None):
        f = self.frame(title, headline, sub)
        grid = tk.Frame(f, bg=PANEL)
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        for r, (k, v) in enumerate(rows):
            tk.Label(grid, text=k, bg=PANEL, fg=MUTED, font=(FONT, 10), anchor="nw").grid(row=r, column=0, sticky="nw", pady=3)
            if isinstance(v, Bar):
                self.add_bar(grid, v.key).grid(row=r, column=1, sticky="ew", padx=(24, 0), pady=7)
                continue
            if isinstance(v, Live):
                var = tk.StringVar(value=self.live.get(v.key, NA))
                self.live_vars[v.key] = var
                fg, weight = GOOD, "bold"
            else:
                var, fg, weight = tk.StringVar(value=str(v)), FG, "normal"
            tk.Label(grid, textvariable=var, bg=PANEL, fg=fg, font=(FONT, 10, weight), anchor="w", justify="left",
                     wraplength=500).grid(row=r, column=1, sticky="w", padx=(24, 0), pady=3)
        return f

    def page_cpu(self):
        c = self.data["cpu"]
        ghz = lambda v: f"{v / 1000:.2f} ГГц  ({v:.0f} МГц)" if v else NA
        self.card("Характеристики", [
            ("Сокет", c["socket"]), ("Архитектура", c["arch"]), ("Семейство / ревизия", c["family"]),
            ("Степпинг", c["stepping"]), ("Ядра", c["cores"] or NA), ("Потоки", c["threads"] or NA),
            ("Процессоров (сокетов)", c["packages"]), ("Кэш L1", c["l1"]), ("Кэш L2", c["l2"]), ("Кэш L3", c["l3"]),
            ("Виртуализация", c["virt"]), ("Инструкции", c["flags"])],
            headline=c["name"], sub=f'Производитель: {c["vendor"]}')
        self.card("Частоты и разгон", [
            ("Базовая частота", ghz(c["base_mhz"])),
            ("Макс. (по данным ОС)", ghz(c["max_mhz"])),
            ("Мин. частота", ghz(c["min_mhz"])) if c["min_mhz"] else ("Шина (BCLK)", f'{c["bus_mhz"]:.0f} МГц' if c["bus_mhz"] else NA),
            ("Множитель (прибл.)", f'x{c["multiplier"]:.0f}' if c["multiplier"] else NA),
            ("Напряжение ядра", f'{c["volt"]:.1f} В' if c["volt"] else NA),
            ("Частота сейчас", Live("cpu_freq")), ("Максимум за сеанс", Live("cpu_max_seen")),
            ("Режим", Live("cpu_oc")), ("Температура", Live("cpu_temp"))])
        f = self.frame("Загрузка")
        row = tk.Frame(f, bg=PANEL)
        row.pack(fill="x")
        row.columnconfigure(1, weight=1)
        tk.Label(row, text="Общая", bg=PANEL, fg=MUTED, font=(FONT, 10)).grid(row=0, column=0, sticky="w")
        self.add_bar(row, "cpu_pct", 10).grid(row=0, column=1, sticky="ew", padx=(24, 12), pady=4)
        var = tk.StringVar(value=self.live.get("cpu_load", NA))
        self.live_vars["cpu_load"] = var
        tk.Label(row, textvariable=var, bg=PANEL, fg=GOOD, font=(FONT, 10, "bold"), width=6).grid(row=0, column=2)
        n = c["threads"] or 0
        grid = tk.Frame(f, bg=PANEL)
        grid.pack(fill="x", pady=(10, 0))
        cols = 8 if n > 8 else max(n, 1)
        for i in range(cols):
            grid.columnconfigure(i, weight=1, uniform="core")
        for i in range(n):
            cell = tk.Frame(grid, bg=PANEL)
            cell.grid(row=i // cols, column=i % cols, sticky="ew", padx=4, pady=3)
            tk.Label(cell, text=f"Поток {i}", bg=PANEL, fg=MUTED, font=(FONT, 8)).pack(anchor="w")
            self.add_bar(cell, f"core{i}", 6).pack(fill="x")

    def page_board(self):
        b = self.data["board"]
        name = f'{b["maker"]} {b["model"]}'
        self.card("Материнская плата", [("Производитель", b["maker"]), ("Модель", b["model"]),
                                        ("Серийный номер", b["serial"])],
                  headline="Материнская плата" if name == f"{NA} {NA}" else name)
        self.card("BIOS / UEFI", [("Производитель", b["bios_vendor"]), ("Версия", b["bios_ver"]), ("Дата", b["bios_date"])])
        self.card("Система", [("ОС", b["os"]), ("Имя компьютера", b["host"])])

    def page_ram(self):
        r = self.data["ram"]
        mods = r["modules"]
        types = sorted({m["type"] for m in mods if m["type"] != NA})
        cur = max((m["current"] or 0 for m in mods), default=0)
        rated = max((m["rated"] or 0 for m in mods), default=0)
        n = r["slots_total"] or len(mods)
        used = len(mods)
        hint = None if mods else "Данные о модулях недоступны (на Linux запустите через sudo)"
        chan = {1: "Single", 2: "Dual", 3: "Dual+Single", 4: "Dual / Quad"}.get(used, f"{used} модулей") if used else NA
        self.card("Общее", [
            ("Тип", "/".join(types) or NA), ("Объём", fmt_bytes(r["total"])),
            ("Текущая скорость", f"{cur} МТ/с" if cur else NA), ("Номинал модулей", f"{rated} МТ/с" if rated else NA),
            ("Слоты", f"занято {used} из {n}" if n else NA),
            ("Макс. объём платой", fmt_bytes(r["max_cap"])), ("Коррекция ошибок (ECC)", r["ecc"]),
            ("Каналы (оценка)", chan), ("Профиль XMP / EXPO", ram_profile(mods[0]) if mods else NA)],
            headline=f'{fmt_bytes(r["total"])} {"/".join(types)}'.strip(), sub=hint)
        f = self.frame("Слоты оперативной памяти")
        slots = r["slots"] or [None] * n
        cols = 4
        grid = tk.Frame(f, bg=PANEL)
        grid.pack(fill="x")
        for i in range(min(cols, max(len(slots), 1))):
            grid.columnconfigure(i, weight=1, uniform="slot")
        for i, m in enumerate(slots):
            if m:
                text = f'{fmt_bytes(m["size"])}\n{m["type"]}-{m["current"] or m["rated"] or "?"}\n{m["slot"]}'
                box = tk.Label(grid, text=text, bg=PANEL2, fg=FG, font=(FONT, 10, "bold"), height=4,
                               highlightthickness=2, highlightbackground=ACCENT)
            else:
                box = tk.Label(grid, text=f"Слот {i + 1}\nпусто", bg=PANEL, fg=MUTED, font=(FONT, 10), height=4,
                               highlightthickness=2, highlightbackground=PANEL2)
            box.grid(row=i // cols, column=i % cols, sticky="ew", padx=4, pady=4)
        self.card("Использование", [("Занято", Live("ram_used")), ("", Bar("ram_pct")),
                                    ("Доступно", Live("ram_free")), ("Подкачка", Live("swap"))])
        for m in slots:
            if not m:
                continue
            volt = " · ".join(x for x in (f'сейчас {m["volt"]:.2f} В' if m["volt"] else "",
                                          f'мин {m["vmin"]:.2f}' if m["vmin"] else "",
                                          f'макс {m["vmax"]:.2f}' if m["vmax"] else "") if x) or NA
            self.card(f'Модуль · {m["slot"]}', [
                ("Объём", fmt_bytes(m["size"])), ("Тип / форм-фактор", f'{m["type"]} {m["form"]}'),
                ("Банк", m["bank"]), ("Ранги", m["rank"] or NA), ("Ширина шины", m["width"]),
                ("Номинальная скорость", f'{m["rated"]} МТ/с' if m["rated"] else NA),
                ("Текущая скорость", f'{m["current"]} МТ/с' if m["current"] else NA),
                ("Разгон / профиль", ram_profile(m)), ("Напряжение", volt),
                ("Производитель", m["maker"]), ("Артикул", m["part"]), ("Серийный номер", m["serial"])])

    def page_disks(self):
        if not self.data["disks"]:
            self.card("Накопители", [("", "Не удалось получить список дисков")])
        for d in self.data["disks"]:
            rows = [("Тип", d["kind"]), ("Интерфейс", d["bus"]), ("Объём", fmt_bytes(d["size"])),
                    ("Состояние", d["health"]), ("Прошивка", d["fw"]), ("Серийный номер", d["serial"])]
            if d["rpm"]:
                rows.insert(1, ("Скорость вращения", f'{d["rpm"]} об/мин'))
            self.card("Накопитель", rows, headline=d["name"], sub=f'{d["kind"]} · {fmt_bytes(d["size"])}')
        if self.data["parts"]:
            self.card("Разделы", [(f'{p["mount"]}  ({p["fs"]})',
                                   f'{fmt_bytes(p["used"])} из {fmt_bytes(p["total"])}  ·  {p["pct"]:.0f} %')
                                  for p in self.data["parts"]])

    def page_gpu(self):
        if not self.data["gpus"]:
            self.card("Видеокарта", [("", "Видеоадаптеры не найдены")])
        for g in self.data["gpus"]:
            rows = [("Производитель", g.get("vendor", NA)), ("Видеопамять", fmt_bytes(g.get("vram"))),
                    ("Драйвер", g.get("driver", NA))]
            for k, label in (("chip", "Видеопроцессор"), ("compute", "Compute capability"), ("drv_model", "Режим драйвера"),
                             ("vbios", "VBIOS"), ("bus", "Шина PCI"), ("pcie", "Интерфейс PCIe"),
                             ("res", "Текущий режим экрана")):
                if g.get(k) not in (None, NA):
                    rows.append((label, g[k]))
            self.card("Характеристики", rows, headline=g["name"], sub=f'{g.get("vendor", "")} · {fmt_bytes(g.get("vram"))}')
            i = g.get("nv_index")
            if i is None:
                tk.Label(self.body, text="Живые показатели доступны для NVIDIA через nvidia-smi.",
                         bg=BG, fg=MUTED, font=(FONT, 9)).pack(anchor="w", padx=24, pady=(8, 0))
                continue
            unit = lambda v, u: f"{v} {u}" if v != NA else NA
            pl, pd = num(g["tdp"]), num(g["tdp_def"])
            plim = unit(g["tdp"], "Вт")
            if g["tdp_def"] != NA:
                plim += f"  (по умолчанию {g['tdp_def']} Вт" + (", изменён)" if pl and pd and abs(pl - pd) > 1 else ")")
            self.card("Разгон и лимиты", [
                ("Частоты сейчас / макс.", Live(f"g{i}_oc")),
                ("Базовая частота ядра", unit(g["def_core"], "МГц")), ("Базовая частота памяти", unit(g["def_mem"], "МГц")),
                ("Макс. буст ядра", unit(g["max_core"], "МГц")), ("Макс. частота памяти", unit(g["max_mem"], "МГц")),
                ("Лимит мощности", plim), ("Макс. лимит мощности", unit(g["tdp_max"], "Вт"))])
            self.card("Сейчас", [("Частота ядра", Live(f"g{i}_core")), ("Частота памяти", Live(f"g{i}_mem")),
                                 ("Загрузка", Live(f"g{i}_load")), ("", Bar(f"g{i}_pct")),
                                 ("Видеопамять", Live(f"g{i}_vram")), ("", Bar(f"g{i}_vram_pct")),
                                 ("Температура", Live(f"g{i}_temp")), ("Потребление", Live(f"g{i}_power")),
                                 ("Вентилятор", Live(f"g{i}_fan"))])

    # — вкладка «Оверлей» —
    def page_overlay(self):
        c = self.cfg
        f = self.frame("Оверлей поверх игр и окон")
        tk.Label(f, text="Небольшая панель с живыми показателями. Перетаскивайте её мышью, правый клик — меню.\n"
                         "Игры в полноэкранном режиме её перекрывают — используйте режим «Без рамки» (borderless).",
                 bg=PANEL, fg=MUTED, font=(FONT, 10), justify="left", anchor="w").pack(fill="x", pady=(0, 10))
        on = self.overlay is not None
        tk.Button(f, text="Скрыть оверлей" if on else "Показать оверлей", command=lambda: self.set_overlay(not on),
                  bg=PANEL2 if on else ACCENT, fg=FG if on else BG, relief="flat", font=(FONT, 11, "bold"),
                  padx=20, pady=8, cursor="hand2", activebackground=GOOD).pack(anchor="w")

        f = self.frame("Показатели (галочка — показывать, стрелки — порядок)")
        cat = self.ordered_catalog()
        order = [x[0] for x in cat]
        for idx, (key, label, live) in enumerate(cat):
            row = tk.Frame(f, bg=PANEL)
            row.pack(fill="x", pady=1)
            var = tk.BooleanVar(value=key in c["ov_enabled"])

            def toggle(k=key, v=var):
                en = [x for x in c["ov_enabled"] if x != k]
                if v.get():
                    en.append(k)
                c["ov_enabled"] = en
                self.refresh_overlay()
            tk.Checkbutton(row, text=label, variable=var, command=toggle, bg=PANEL, fg=FG, selectcolor=PANEL2,
                           activebackground=PANEL, activeforeground=FG, font=(FONT, 10), anchor="w",
                           width=22).pack(side="left")
            for sym, d in (("↑", -1), ("↓", 1)):
                def move(d=d, i=idx):
                    j = i + d
                    if 0 <= j < len(order):
                        new = order[:]
                        new[i], new[j] = new[j], new[i]
                        c["ov_order"] = new
                        self.refresh_overlay()
                        self.show("overlay", keep=True)
                tk.Button(row, text=sym, command=move, bg=PANEL2, fg=FG, relief="flat", width=3, font=(FONT, 8),
                          cursor="hand2").pack(side="left", padx=2)

        f = self.frame("Внешний вид")
        grid = tk.Frame(f, bg=PANEL)
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)

        def scale(r, label, key, lo, hi, step):
            tk.Label(grid, text=label, bg=PANEL, fg=MUTED, font=(FONT, 10)).grid(row=r, column=0, sticky="w", pady=4)
            sc = tk.Scale(grid, from_=lo, to=hi, resolution=step, orient="horizontal", bg=PANEL, fg=FG,
                          troughcolor=PANEL2, highlightthickness=0, bd=0, length=260)
            sc.set(c[key])
            sc.grid(row=r, column=1, sticky="w", padx=(24, 0))
            sc.bind("<ButtonRelease-1>", lambda e: (c.__setitem__(key, sc.get()), self.refresh_overlay()))
        scale(0, "Прозрачность", "ov_alpha", 0.3, 1.0, 0.05)
        scale(1, "Размер шрифта", "ov_font", 8, 28, 1)

        def color(r, label, key):
            tk.Label(grid, text=label, bg=PANEL, fg=MUTED, font=(FONT, 10)).grid(row=r, column=0, sticky="w", pady=4)
            b = tk.Button(grid, text="  ", bg=c[key], relief="flat", width=8, cursor="hand2")

            def pick():
                col = colorchooser.askcolor(color=c[key], title=label)[1]
                if col:
                    c[key] = col
                    b.configure(bg=col)
                    self.refresh_overlay()
            b.configure(command=pick)
            b.grid(row=r, column=1, sticky="w", padx=(24, 0))
        color(2, "Цвет значений", "ov_accent")
        color(3, "Цвет фона", "ov_bg")

        def check(r, label, key):
            var = tk.BooleanVar(value=c[key])
            tk.Checkbutton(grid, text=label, variable=var, bg=PANEL, fg=FG, selectcolor=PANEL2, activebackground=PANEL,
                           activeforeground=FG, font=(FONT, 10),
                           command=lambda: (c.__setitem__(key, var.get()), self.refresh_overlay())
                           ).grid(row=r, column=0, columnspan=2, sticky="w", pady=2)
        check(4, "Горизонтальная раскладка", "ov_horizontal")
        check(5, "Показывать подписи", "ov_labels")
        check(6, "Закрепить позицию (запретить перетаскивание)", "ov_locked")

        def reset():
            c["ov_x"], c["ov_y"] = 24, 24
            if self.overlay:
                self.overlay.geometry("+24+24")
            c.save()
        tk.Button(grid, text="Сбросить позицию", command=reset, bg=PANEL2, fg=FG, relief="flat", font=(FONT, 9),
                  padx=12, pady=4, cursor="hand2").grid(row=7, column=0, columnspan=2, sticky="w", pady=(10, 0))

    # — экспорт —
    def export(self):
        if not self.data:
            return
        path = filedialog.asksaveasfilename(defaultextension=".txt", initialfile="pc_specs.txt")
        if not path:
            return
        out = []
        for k in ("cpu", "board"):
            out.append(f"== {k.upper()} ==")
            out += [f"{kk}: {v}" for kk, v in self.data[k].items()]
        out.append("== RAM ==")
        r = self.data["ram"]
        out += [f"{kk}: {v}" for kk, v in r.items() if kk not in ("modules", "slots")]
        out += [json.dumps(m, ensure_ascii=False) for m in r["modules"]]
        out.append("== DISKS ==")
        out += [json.dumps(d, ensure_ascii=False) for d in self.data["disks"]]
        out.append("== GPU ==")
        out += [json.dumps(g, ensure_ascii=False) for g in self.data["gpus"]]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(out))
        messagebox.showinfo(APP_NAME, "Сохранено:\n" + path)


if __name__ == "__main__":
    if "--dump" in sys.argv:
        disks, parts = collect_disks()
        print(json.dumps({"cpu": collect_cpu(), "board": collect_board(), "ram": collect_ram(),
                          "disks": disks, "parts": parts, "gpus": collect_gpus()},
                         ensure_ascii=False, indent=2, default=str))
    elif tk is None:
        sys.exit("Не найден tkinter (Linux: sudo apt install python3-tk)")
    else:
        App().mainloop()
