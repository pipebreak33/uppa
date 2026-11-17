#!/usr/bin/env python3
"""uppa – håller dina PowerShell- och Microsoft-CLI-verktyg uppdaterade, och bara dem.
Täcker det du faktiskt har installerat: PowerShell 7 och dess moduler (Az, Graph, EXO, Teams, PnP …),
Azure CLI + az-tillägg/Bicep, .NET + globala dotnet-verktyg, och Microsofts CLI:er i npm -g (CLI for Microsoft 365).
Kusinen Puppa (github.com/pipebreak33/puppa) installeras och uppdateras också via uppa.

  uppa                     meny
  uppa status [källa|namn] vad är inaktuellt (-a visar allt)
  uppa update [källa|namn] uppdatera (parallellt per källa, -n torrkörning, -y inga frågor, -j N)
  uppa select              checklista: kryssa, enter, klart
  uppa changes [namn]      release notes mellan din version och senaste
  uppa doctor              dubbletter, rättigheter, vad som är påslaget
  uppa ignore KÄLLA:NAMN   hoppa över något för gott (unignore för att ångra, ignore utan argument listar)
  uppa nudge enable|disable|status|snooze 7d
  uppa schedule enable [--daily] [--at 09:00] | disable | status

Enbart standardbiblioteket, Python 3.8+.
"""
from __future__ import annotations

import base64
import json
import random
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path

VERSION = "1.1.1"
HOME = Path.home()
DIR = HOME / ".uppa"
CACHE = DIR / "cache.json"
STATE = DIR / "state.json"
CONFIG = DIR / "config.json"
LOGS = DIR / "logs"
LABEL = "se.uppa.update"
PLIST = HOME / "Library/LaunchAgents" / (LABEL + ".plist")
IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"
if IS_WIN:
    _LA = os.environ.get("LOCALAPPDATA", str(HOME / "AppData" / "Local"))
    _AD = os.environ.get("APPDATA", str(HOME / "AppData" / "Roaming"))
    _PF = os.environ.get("ProgramFiles", r"C:\Program Files")
    _PF86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    EXTRA_PATH = [os.path.join(_LA, "Microsoft", "WindowsApps"), os.path.join(_AD, "npm"),
                  os.path.join(_PF, "PowerShell", "7"), os.path.join(_PF, "Microsoft SDKs", "Azure", "CLI2", "wbin"),
                  os.path.join(_PF86, "Microsoft SDKs", "Azure", "CLI2", "wbin"), os.path.join(_PF, "dotnet"),
                  str(HOME / ".dotnet" / "tools"), str(DIR / "bin"), str(HOME / ".puppa" / "bin")]
else:
    EXTRA_PATH = ["/opt/homebrew/bin", "/opt/homebrew/sbin", "/home/linuxbrew/.linuxbrew/bin", "/usr/local/bin",
                  str(HOME / ".local/bin"), str(HOME / ".dotnet/tools"), "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
# winget-id:n för Microsofts CLI-verktyg (Windows)
MS_WINGET = re.compile(r"^Microsoft\.(PowerShell(\.Preview)?|AzureCLI|Azure\.[\w.]+|DotNet\.SDK\.\d+|Bicep|Sqlcmd|"
                       r"GitCredentialManagerCore)$", re.I)
# Only command-line Microsoft / PowerShell tools. GUI apps (Office, Teams, Windows App …) are out of scope.
MS_FORMULA = re.compile(r"^(powershell(@.+)?|azure-cli|azure-dev|azd|bicep|azcopy|kubelogin|dotnet(@.+)?|"
                        r"azure-functions-core-tools(@.+)?|mssql-tools\d*|msodbcsql\d*|sqlcmd|"
                        r"git-credential-manager|microsoft/.+|azure/.+)$")
MS_CASK = re.compile(r"^(powershell(@preview|-lts)?|dotnet-sdk(@.+)?|git-credential-manager)$")
MS_NPM = re.compile(r"^(@pnp/cli-microsoft365|@microsoft/.+|@azure/.+|azure-functions-core-tools|"
                    r"@azure/static-web-apps-cli|@azure-tools/.+)$")
os.environ["PATH"] = os.pathsep.join(dict.fromkeys(os.environ.get("PATH", "").split(os.pathsep) + EXTRA_PATH))

# ───────────────────────────── terminal ─────────────────────────────
def _win_console():
    """UTF-8 + ANSI-färger i Windows-konsolen (Windows Terminal, conhost, VS Code)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.SetConsoleOutputCP(65001)
        h = k.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if k.GetConsoleMode(h, ctypes.byref(mode)):
            k.SetConsoleMode(h, mode.value | 0x0004)       # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass


if IS_WIN:
    _win_console()
TTY = sys.stdout.isatty()
COLOR = TTY and "NO_COLOR" not in os.environ
ANIM = TTY and not os.environ.get("UPPA_NO_ANIM") and not os.environ.get("CI")


def c(code, s):
    return f"\033[{code}m{s}\033[0m" if COLOR else s


def green(s): return c("38;5;42", s)
def yellow(s): return c("38;5;214", s)
def red(s): return c("38;5;203", s)
def dim(s): return c("2", s)
def bold(s): return c("1", s)
def accent(s): return c("38;5;49", s)
def cyan(s): return c("38;5;80", s)


ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


def vlen(s):
    return len(ANSI.sub("", s))


def pad(s, n):
    return s + " " * max(0, n - vlen(s))


def cut(s, n):
    s = ANSI.sub("", s).replace("\t", " ").strip()
    return s if len(s) <= n else s[: max(0, n - 1)] + "…"


def width():
    return max(20, shutil.get_terminal_size((100, 30)).columns)


def fit(s, w=None):
    """Klipp en (färgad) rad så att den aldrig radbryts i terminalen."""
    w = max(8, (w or width()) - 1)
    if vlen(s) <= w:
        return s
    out, n, i = [], 0, 0
    while i < len(s) and n < w - 1:
        m = ANSI.match(s, i)
        if m:
            out.append(m.group(0))
            i = m.end()
            continue
        out.append(s[i])
        n += 1
        i += 1
    return "".join(out) + ("\033[0m" if COLOR else "") + "…"


class Live:
    """Ritar om ett block rader på plats, även efter att fönstret ändrat storlek (terminalen radbryter om)."""

    def __init__(self):
        self.prev = []

    def _up(self):
        w = width()
        return sum(max(1, -(-n // w)) for n in self.prev)

    def draw(self, lines):
        w = width()
        lines = [fit(l, w) for l in lines]
        sys.stdout.write("\r" + "\033[F" * self._up() + "\033[J" + "".join(l + "\n" for l in lines))
        sys.stdout.flush()
        self.prev = [vlen(l) for l in lines]

    def clear(self):
        sys.stdout.write("\r" + "\033[F" * self._up() + "\033[J")
        sys.stdout.flush()
        self.prev = []


LOGO = "U›"
QUIPS = [
    "Frågar Homebrew snällt om nyheter…",
    "PowerShell Gallery tar sin fika. Strax.",
    "Räknar versioner. Det är fler än man tror.",
    "Det här är bara läsning. Inget ändras.",
    "Kollar om någon släppt en .1 i natt.",
    "Semver är ett löfte. Inte en garanti.",
    "-WhatIf är mitt mellannamn.",
]
DIRTY = False      # något har skrivits ut som användaren bör hinna läsa innan skärmen töms


def banner():
    print()
    print(fit(f"  {accent(bold(LOGO))}  {bold('uppa')} {dim(VERSION + ' · PowerShell & Microsoft-CLI')}"))
    print()


# ───────────────────────────── helpers ─────────────────────────────
def resolve(cmd):
    """Windows: kör npm.cmd/az.cmd m.fl. via full sökväg (CreateProcess hittar inte .cmd på namn)."""
    cmd = list(cmd)
    if IS_WIN and cmd and not os.path.isabs(cmd[0]):
        found = shutil.which(cmd[0])
        if found:
            cmd[0] = found
    return cmd


def ps_cmd(script):
    """pwsh med -EncodedCommand: inga citat-/escape-problem på varken Windows eller Unix."""
    enc = base64.b64encode(script.encode("utf-16-le")).decode()
    return ["pwsh", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc]


def show_cmd(cmd):
    if "-EncodedCommand" in cmd:
        script = base64.b64decode(cmd[cmd.index("-EncodedCommand") + 1]).decode("utf-16-le")
        return "pwsh: " + re.sub(r"\s+", " ", script.split(";", 1)[-1]).strip()
    return " ".join(cmd)


def run(cmd, timeout=600, env=None, input=None):
    """Returns (rc, stdout, stderr). Never raises for a missing command."""
    try:
        p = subprocess.run(resolve(cmd), capture_output=True, text=True, timeout=timeout, encoding="utf-8",
                           errors="replace", env={**os.environ, **(env or {})}, input=input,
                           stdin=None if input is not None else subprocess.DEVNULL)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", f"{cmd[0]}: hittades inte"
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"


def have(cmd):
    return shutil.which(cmd) is not None


def http_json(url, data=None, headers=None, timeout=20):
    h = {"User-Agent": "uppa/" + VERSION, "Accept": "application/json"}
    h.update(headers or {})
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def vtuple(v):
    v = str(v or "").strip().lstrip("vV")
    v = v.split(",")[0]                       # brew casks: "4.94.0,241994"
    main, _, pre = v.partition("-")
    nums = tuple(int(x) for x in re.findall(r"\d+", main)[:6])
    return nums + ((0,) if pre else (1,))     # 1.0.0 > 1.0.0-preview


def newer(latest, current):
    try:
        return bool(latest) and vtuple(latest) > vtuple(current)
    except Exception:
        return False


def major_bump(cur, new):
    a, b = vtuple(cur), vtuple(new)
    return bool(a and b) and b[0] > a[0]


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def config():
    cfg = {"ignore": [], "greedy_casks": False}
    cfg.update(load_json(CONFIG, {}))
    return cfg


# ───────────────────────────── model ─────────────────────────────
class Item:
    """One thing that can be updated."""

    def __init__(self, source, name, current, latest, label=None, manual=False, note="", meta=None):
        self.source, self.name, self.current, self.latest = source, name, current, latest
        self.label = label or name
        self.manual = manual          # shown, never updated by uppa (e.g. macOS)
        self.note = note
        self.meta = meta or {}

    @property
    def key(self):
        return f"{self.source}:{self.name}"

    @property
    def outdated(self):
        return self.latest is not None and (self.latest == "?" or newer(self.latest, self.current))

    def to_dict(self):
        return dict(source=self.source, name=self.name, current=self.current, latest=self.latest,
                    label=self.label, manual=self.manual, note=self.note, meta=self.meta)

    @classmethod
    def from_dict(cls, d):
        return cls(d["source"], d["name"], d["current"], d["latest"], d.get("label"), d.get("manual", False),
                   d.get("note", ""), d.get("meta"))


class Task:
    def __init__(self, label, cmd, lane, interactive=False, after=(), items=(), fallback=None, env=None):
        self.label, self.cmd, self.lane = label, cmd, lane
        self.interactive = interactive
        self.after = set(after)      # lanes that must finish first
        self.items = list(items)
        self.fallback = fallback     # list of commands to try one by one if cmd fails
        self.env = env or {}
        self.state = "queued"
        self.last = ""
        self.t0 = self.t1 = None
        self.output = []
        self.failed_parts = []

    @property
    def secs(self):
        if not self.t0:
            return ""
        return f"{int((self.t1 or time.time()) - self.t0)}s"


class Source:
    key = ""
    title = ""
    lane = None

    def available(self):
        return False

    def scan(self):
        """-> (items, summary)  items = everything installed that we know about (outdated or not)."""
        return [], ""

    def tasks(self, items, plan_keys):
        return []


# ───────────────────────────── sources ─────────────────────────────
BREW_ENV = {"HOMEBREW_NO_AUTO_UPDATE": "1", "HOMEBREW_NO_ENV_HINTS": "1", "HOMEBREW_COLOR": "0"}


class Brew(Source):
    key, title = "brew", "CLI (Homebrew)"

    def available(self):
        return have("brew")

    def scan(self):
        """Only Microsoft / PowerShell formulae and casks (MS_FORMULA / MS_CASK)."""
        run(["brew", "update", "--quiet"], timeout=300, env={"HOMEBREW_NO_ENV_HINTS": "1"})
        inst = {}
        for kind, flag, rx in (("formula", "--formula", MS_FORMULA), ("cask", "--cask", MS_CASK)):
            for line in run(["brew", "list", flag, "--versions"], env=BREW_ENV)[1].splitlines():
                parts = line.split()
                if len(parts) >= 2 and rx.match(parts[0]):
                    inst[(kind, parts[0])] = parts[-1]
        args = ["brew", "outdated", "--json=v2"]
        if config().get("greedy_casks"):
            args.append("--greedy")
        data = json.loads(run(args, timeout=300, env=BREW_ENV)[1] or "{}")
        latest = {}
        for kind, key in (("formula", "formulae"), ("cask", "casks")):
            for f in data.get(key, []):
                if not f.get("pinned"):
                    latest[(kind, f["name"])] = f["current_version"]
        items = [Item("brew", n, v, latest.get((k, n), v), label=n + (" (cask)" if k == "cask" else ""),
                      meta={"kind": k}) for (k, n), v in sorted(inst.items(), key=lambda x: x[0][1])]
        return items, ", ".join(i.name for i in items) or "inga Microsoft-paket"

    def tasks(self, items, plan_keys):
        out = []
        formulae = [i for i in items if i.meta.get("kind") == "formula"]
        if formulae:
            names = [i.name for i in formulae]
            out.append(Task(f"{len(names)} formulor" if len(names) > 1 else names[0],
                            ["brew", "upgrade", "--formula", *names], "brew", items=formulae, env=BREW_ENV,
                            fallback=[["brew", "upgrade", "--formula", n] for n in names]))
        for i in items:
            if i.meta.get("kind") == "cask":   # casks can ask for a password: own terminal, one at a time
                out.append(Task(i.label, ["brew", "upgrade", "--cask", i.name], "brew-cask", interactive=True,
                                items=[i], env=BREW_ENV))
        return out


class Npm(Source):
    key, title = "npm", "CLI (npm)"

    def available(self):
        return have("npm")

    def prefix(self):
        return run(["npm", "prefix", "-g"])[1].strip()

    def needs_sudo(self):
        if IS_WIN:
            return False
        p = Path(self.prefix()) / "lib/node_modules"
        return p.exists() and not os.access(p, os.W_OK)

    def scan(self):
        rc, out, _ = run(["npm", "ls", "-g", "--depth=0", "--json"], timeout=120)
        deps = json.loads(out or "{}").get("dependencies", {})
        rc, out, _ = run(["npm", "outdated", "-g", "--json"], timeout=180)
        outd = json.loads(out or "{}")
        items = []
        for name, d in deps.items():
            if not MS_NPM.match(name):
                continue
            o = outd.get(name)
            latest = o.get("latest") if o else d.get("version")
            items.append(Item("npm", name, d.get("version", "?"), latest))
        s = f"{len(items)} Microsoft-paket" + (dim(" · kräver sudo") if items and self.needs_sudo() else "")
        return items, s

    def tasks(self, items, plan_keys):
        if not items:
            return []
        sudo = self.needs_sudo()
        args = ["npm", "install", "-g", *[f"{i.name}@latest" for i in items]]
        return [Task(f"{len(items)} paket" if len(items) > 1 else items[0].name,
                     (["sudo"] + args) if sudo else args, "npm", interactive=sudo, items=items)]


PS_SCAN = r"""
$ErrorActionPreference = 'SilentlyContinue'
$all = @(Get-InstalledModule)
$dep = @{}
foreach ($meta in 'Az', 'Microsoft.Graph', 'Microsoft.Graph.Beta', 'Microsoft.Entra') {
  $m = $all | Where-Object Name -eq $meta
  if (-not $m) { continue }
  $psd = Join-Path $m.InstalledLocation "$meta.psd1"
  $data = if (Test-Path $psd) { Import-PowerShellDataFile $psd } else { @{} }
  foreach ($d in @($data.RequiredModules) + @($data.ModuleList) + @($m.Dependencies)) {
    if (-not $d) { continue }
    $dn = if ($d -is [string]) { $d } elseif ($d.ModuleName) { $d.ModuleName } else { $d.Name }
    if ($dn -and $dn -ne $meta) { $dep[[string]$dn] = $meta }
  }
}
$roots = @($all | Where-Object { -not $dep.ContainsKey($_.Name) } | ForEach-Object Name)
$latest = @{}
if ($roots.Count) {
  Find-PSResource -Name $roots -Repository PSGallery | ForEach-Object { $latest[$_.Name] = $_.Version.ToString() }
}
@($all | ForEach-Object {
  [pscustomobject]@{ n = $_.Name; v = $_.Version.ToString(); l = $latest[$_.Name]; p = $dep[$_.Name]; u = [string]$_.ProjectUri }
}) | ConvertTo-Json -Compress
"""


class Pwsh(Source):
    key, title = "pwsh", "PowerShell-moduler"

    def available(self):
        return have("pwsh")

    def scan(self):
        rc, out, err = run(ps_cmd(PS_SCAN), timeout=600)
        rows = json.loads(out or "[]")
        if isinstance(rows, dict):
            rows = [rows]
        items, sub = [], 0
        for r in rows:
            if r.get("p"):            # part of Az / Microsoft.Graph – updated together with its meta-module
                sub += 1
                continue
            items.append(Item("pwsh", r["n"], r["v"], r.get("l") or r["v"], meta={"uri": r.get("u") or ""}))
        return items, f"{len(rows)} moduler ({sub} följer med Az/Graph)"

    @staticmethod
    def lane_for(name):
        if name == "Az" or name.startswith("Az."):
            return "pwsh-az"
        if name.startswith("Microsoft.Graph") or name.startswith("Microsoft.Entra"):
            return "pwsh-graph"
        return "pwsh"

    def tasks(self, items, plan_keys):
        lanes = {}
        for i in items:
            lanes.setdefault(self.lane_for(i.name), []).append(i)
        out = []
        for lane, its in lanes.items():
            names = ",".join("'" + i.name.replace("'", "''") + "'" for i in its)
            ps = (f"$ProgressPreference='SilentlyContinue'; Update-Module -Name {names} -Force -AcceptLicense "
                  f"-ErrorAction Stop -Verbose 4>&1 | ForEach-Object {{ $_.ToString() }}")
            out.append(Task(", ".join(i.name for i in its) if len(its) <= 3 else f"{len(its)} moduler",
                            ps_cmd(ps), lane, items=its,
                            after=("brew",) if "brew:powershell" in plan_keys else ()))
        return out


class AzExt(Source):
    key, title = "az", "az-tillägg"

    def available(self):
        return have("az")

    def scan(self):
        rc, out, _ = run(["az", "extension", "list", "-o", "json"], timeout=120)
        inst = {e["name"]: e["version"] for e in json.loads(out or "[]")}
        avail = {}
        if inst:
            rc, out, _ = run(["az", "extension", "list-available", "-o", "json"], timeout=180)
            for e in json.loads(out or "[]"):
                if e.get("name") in inst:
                    avail[e["name"]] = e.get("version")
        items = [Item("az", n, v, avail.get(n) or v) for n, v in inst.items()]
        rc, out, _ = run(["az", "bicep", "version"], timeout=60)
        m = re.search(r"version (\d+\.\d+\.\d+)", out)
        if rc == 0 and m:
            rc2, out2, _ = run(["az", "bicep", "list-versions", "-o", "json"], timeout=60)
            vers = json.loads(out2 or "[]")
            lat = vers[0].lstrip("v") if vers else m.group(1)
            items.append(Item("az", "bicep", m.group(1), lat, label="Bicep"))
        return items, f"{len(items)} st"

    def tasks(self, items, plan_keys):
        after = ("brew",) if "brew:azure-cli" in plan_keys else ()
        out = []
        for i in items:
            cmd = ["az", "bicep", "upgrade"] if i.name == "bicep" else ["az", "extension", "update", "--name", i.name]
            out.append(Task(i.label, cmd, "az", items=[i], after=after))
        return out


class Dotnet(Source):
    key, title = "dotnet", ".NET-verktyg"

    def available(self):
        return have("dotnet")

    def scan(self):
        rc, out, _ = run(["dotnet", "tool", "list", "-g"], timeout=60)
        rows = [l.split() for l in out.splitlines()[2:] if l.strip()]

        def one(r):
            name, cur = r[0], r[1]
            try:
                vs = http_json(f"https://api.nuget.org/v3-flatcontainer/{name.lower()}/index.json")["versions"]
                vs = [v for v in vs if "-" not in v] or vs
                lat = vs[-1]
            except Exception:
                lat = cur
            return Item("dotnet", name, cur, lat)

        with ThreadPoolExecutor(6) as ex:
            items = list(ex.map(one, rows))
        return items, f"{len(items)} verktyg"

    def tasks(self, items, plan_keys):
        return [Task(i.name, ["dotnet", "tool", "update", "-g", i.name], "dotnet", items=[i]) for i in items]


def parse_winget(text):
    """Tolkar tabellen från `winget list` (rubrikerna kan vara översatta, så kolumnerna tas i ordning)."""
    lines = [l.split("\r")[-1].rstrip() for l in text.splitlines()]
    for k, l in enumerate(lines[:-1]):
        nxt = lines[k + 1].strip()
        if nxt and set(nxt) <= set("-─") and len(re.findall(r"\S+", l)) >= 3:
            head, body = l, lines[k + 2:]
            break
    else:
        return []
    starts = [m.start() for m in re.finditer(r"\S+", head)]
    sources = ("winget", "msstore")
    out = []
    for l in body:
        if not l.strip() or set(l.strip()) <= set("-─") or len(l) <= starts[1]:
            continue
        # Namn kan innehålla mellanslag (kortas med … av winget); Id, version m.m. gör det aldrig.
        # Läs därför orden från Id-kolumnen och framåt i stället för att lita på exakta kolumnbredder.
        start = starts[1]
        while start > 0 and not l[start - 1].isspace():
            start -= 1
        rest = l[start:].split()
        while len(rest) >= 3 and "." not in rest[0] and "." in rest[1]:   # namnet sträckte sig in i Id-kolumnen
            rest.pop(0)
        if len(rest) < 2:
            continue
        avail = ""
        if len(rest) >= 3 and rest[2] not in sources and len(starts) >= 4:
            avail = rest[2]
        out.append({"name": l[:start].strip(), "id": rest[0], "version": rest[1], "available": avail})
    return out


WINGET_PS = r"""
if (Get-Module -ListAvailable Microsoft.WinGet.Client) {
  Import-Module Microsoft.WinGet.Client
  @(Get-WinGetPackage -Source winget | ForEach-Object {
    [pscustomobject]@{ id = $_.Id; name = $_.Name; version = [string]$_.InstalledVersion;
                       available = [string]($_.AvailableVersions | Select-Object -First 1) }
  }) | ConvertTo-Json -Compress
} else { 'NOMODULE' }
"""


def winget_packages():
    """Microsoft.WinGet.Client (objekt, ej översatt) om modulen finns, annars tolkas `winget list`."""
    if have("pwsh"):
        out = run(ps_cmd(WINGET_PS), timeout=300)[1].strip()
        if out and out != "NOMODULE":
            try:
                rows = json.loads(out)
                return [rows] if isinstance(rows, dict) else rows
            except ValueError:
                pass
    out = run(["winget", "list", "--source", "winget", "--accept-source-agreements", "--disable-interactivity"],
              timeout=300)[1]
    return parse_winget(out)


class Winget(Source):
    key, title = "winget", "CLI (winget)"

    def available(self):
        return IS_WIN and have("winget")

    def scan(self):
        items = []
        for p in winget_packages():
            if MS_WINGET.match(p["id"]):
                items.append(Item("winget", p["id"], p["version"], p.get("available") or p["version"],
                                  label=p.get("name") or p["id"]))
        return items, ", ".join(i.label for i in items) or "inga Microsoft-paket"

    def tasks(self, items, plan_keys):
        out = []
        for i in items:
            cmd = ["winget", "upgrade", "--id", i.name, "-e", "--silent", "--accept-package-agreements",
                   "--accept-source-agreements", "--disable-interactivity"]
            # PowerShell kan behöva UAC-fråga och stänga öppna fönster: egen terminal
            out.append(Task(i.label, cmd, "winget", interactive=i.name.lower().startswith("microsoft.powershell"),
                            items=[i]))
        return out


def github_version(name, filename):
    """VERSION i ett skript på GitHub (raw), eller None om det inte går att nå."""
    repo, branch = repo_for(name)
    try:
        req = urllib.request.Request(f"https://raw.githubusercontent.com/{repo}/{branch}/{filename}",
                                     headers={"User-Agent": "uppa/" + VERSION, "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=15) as r:
            text = r.read().decode("utf-8", "replace")
    except Exception:
        return None, None
    m = re.search(r'^VERSION\s*=\s*["\']([^"\']+)', text, re.M)
    return (m.group(1) if m else None), text


class Self(Source):
    """uppa självt: jämför den här versionen med GitHub."""
    key, title = "self", "Uppa"

    def available(self):
        return True

    def scan(self):
        lat, _ = github_version("uppa", "uppa.py")
        repo, branch = repo_for("uppa")
        where = "utvecklingskopia (git)" if is_git_checkout() else f"github.com/{repo}"
        return [Item("self", "uppa", VERSION, lat or VERSION, label="uppa")], where

    def tasks(self, items, plan_keys):
        cmd = [sys.executable, os.path.realpath(__file__), "self-update", "--yes", "--no-anim"]
        return [Task("Uppa (sig själv)", cmd, "uppa", items=items)] if items else []


class Puppa(Source):
    """Kusinen Puppa: visas alltid, även när den inte är installerad."""
    key, title = "puppa", "Puppa"

    def available(self):
        return True

    def latest(self):
        return github_version("puppa", "puppa.py")[0]

    def scan(self):
        lat = self.latest()
        if not have("puppa"):
            hint = "inte installerad → uppa install puppa" if lat else "inte installerad · inte publicerad än"
            return [], hint
        m = re.search(r"\d+\.\d+(\.\d+)?", run(["puppa", "--version"], timeout=30)[1])
        cur = m.group(0) if m else "?"
        return [Item("puppa", "puppa", cur, lat or cur, label="Puppa")], "PowerShell med några knapptryck"

    def tasks(self, items, plan_keys):
        return [Task("Puppa", sibling_installer("puppa"), "puppa", items=items)] if items else []


SOURCES = [Self(), Brew(), Winget(), Pwsh(), AzExt(), Npm(), Dotnet(), Puppa()]
BY_KEY = {s.key: s for s in SOURCES}


# ───────────────────────────── Uppa, maskoten ─────────────────────────────
# Uppa är ett tjockt U, kusin till Puppa (P:et). Ansiktet bor i U:ets skål.
EYES = {"happy": " ◕ ◕ ", "blink": " ─ ─ ", "left": "◕ ◕  ", "right": "  ◕ ◕", "wait": " ◕ ◕ ", "look": "◔ ◔  ",
        "sad": " ◕ ◕ ", "proud": " ^ ^ ", "wow": " ◕ ◕ ", "worry": " ◔ ◔ ", "sleep": " ─ ─ "}
MOUTH = {"happy": "  ‿  ", "blink": "  ‿  ", "left": " ‿   ", "right": "   ‿ ", "wait": "  ─  ", "look": " ‿   ",
         "sad": "  ⁀  ", "proud": "  ◡  ", "wow": "  o  ", "worry": "  ~  ", "sleep": "  ᶻ  "}
ART = ["██     ██", "██{e}██", "██{m}██", "██▄   ▄██", " ▀█████▀ "]
SHADE = ["38;5;121", "38;5;85", "38;5;49", "38;5;43", "38;5;36"]      # ljus topp → mörkare botten
SAD_SHADE = ["38;5;152", "38;5;115", "38;5;109", "38;5;72", "38;5;66"]
ART_W = 9
JOKES = [
    "Jag heter Uppa. Det står för uppdatera på autopilot. Typ.",
    "Jag är ett U. Det står för Uppdaterad. Eller Underbar. Du väljer.",
    "Har du testat att stänga av och sätta på den igen? Jag menar Update-Module.",
    "Jag är formad som en kopp. Full av uppdateringar.",
    "Det finns två sorters admins: de som tar backup, och de som kommer att göra det.",
    "Connect-MgGraph: för att en inloggning om dagen aldrig räcker.",
    "Jag går aldrig sönder. Jag får bara nya huvudversioner.",
    "-WhatIf är mitt mellannamn. -Confirm är mitt efternamn.",
    "AzureAD-modulen? Vi pratar inte om AzureAD-modulen.",
    "Min kusin Puppa kör recepten. Jag ser till att modulerna är fräscha.",
]


def uppa_art(mood="happy"):
    e, m = EYES.get(mood, EYES["happy"]), MOUTH.get(mood, MOUTH["happy"])
    sh = SAD_SHADE if mood == "sad" else SHADE

    def mid(k, inner):
        return c(sh[k], "██") + bold(inner) + c(sh[k], "██")
    return [c(sh[0], ART[0]), mid(1, e), mid(2, m), c(sh[3], ART[3]), c(sh[4], ART[4])]


def wrap(msg, w, maxl=4):
    lines, cur = [], ""
    for word in ANSI.sub("", msg).split():
        if cur and len(cur) + 1 + len(word) > w:
            lines.append(cur)
            cur = word
        else:
            cur = (cur + " " + word).strip()
    if cur:
        lines.append(cur)
    if len(lines) > maxl:
        lines = lines[:maxl]
        lines[-1] = cut(lines[-1] + " …", w)
    return [cut(l, w) for l in lines] or [""]


def uppa_frame(msg="", mood="happy", lift=0, top="", sub=""):
    """Maskot + pratbubbla. Under 44 kolumner döljs maskoten."""
    w = width()
    if w < 44:
        lines = []
        if msg:
            for k, l in enumerate(wrap(msg, w - 6, 4)):
                lines.append((f"  {accent(bold(LOGO))} " if k == 0 else "     ") + l)
        if sub:
            lines.append("     " + dim(cut(sub, w - 7)))
        return lines
    rows = [""] * 7
    for k, r in enumerate(uppa_art(mood)):
        rows[k + 1 - lift] = r
    if top and not rows[0]:
        rows[0] = top
    bub = []
    if msg:
        lines = wrap(msg, max(14, min(60, w - 20)), 4)
        iw = max(len(l) for l in lines)
        bub = [dim("╭" + "─" * (iw + 2) + "╮")] + \
              [dim("│ ") + l + " " * (iw - len(l)) + dim(" │") for l in lines] + \
              [dim("╰" + "─" * (iw + 2) + "╯")]
    res = []
    for k in range(7):
        line = "  " + pad(rows[k], ART_W + 1)
        if 0 <= k - 1 < len(bub):
            line += " " + (accent("◂ ") if k == 2 else "  ") + bub[k - 1]
        elif sub and k - 1 == len(bub):
            line += "    " + dim(cut(sub, w - ART_W - 9))
        res.append(fit(line, w))
    while res and not ANSI.sub("", res[-1]).strip():
        res.pop()
    while res and not ANSI.sub("", res[0]).strip():
        res.pop(0)
    return res


def say(msg, mood="happy", sub=""):
    global DIRTY
    DIRTY = True
    if TTY:
        print("\n".join(uppa_frame(msg, mood, sub=sub)))
    else:
        print(f"  {LOGO} {msg}")


def idle_mood(t):
    """Blinkar då och då, tittar runt ibland."""
    if t % 4.1 < 0.16:
        return "blink"
    phase = int(t / 2.3) % 7
    return {2: "left", 5: "right"}.get(phase, "happy")


def celebrate(msg):
    global DIRTY
    DIRTY = True
    if not ANIM:
        return say(msg, "proud")
    cols = ["38;5;121", "38;5;214", "38;5;80", "38;5;212", "38;5;227"]
    live = Live()
    sys.stdout.write("\033[?25l")
    try:
        for f in range(14):
            top = "".join(c(random.choice(cols), random.choice("✦✧⋆·*")) if random.random() < .35 else " "
                          for _ in range(ART_W + 1))
            live.draw(uppa_frame(msg, "proud" if f % 5 else "blink", lift=f % 2, top=top))
            time.sleep(0.09)
        live.draw(uppa_frame(msg, "proud"))
    finally:
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()


# ───────────────────────────── scanning ─────────────────────────────
class Spinner:
    """Uppa svävar, blinkar och pratar medan vi väntar. `pending` är en dict (krymper) eller en text."""
    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, pending):
        self.pending = pending
        self.stop = threading.Event()
        self.t = threading.Thread(target=self.loop, daemon=True)
        self.live = Live()

    def __enter__(self):
        if ANIM:
            sys.stdout.write("\033[?25l")
            self.t.start()
        return self

    def text(self, i, el):
        if isinstance(self.pending, dict):
            left = list(self.pending.values())
            m = "Väntar på " + ", ".join(left[:3]) + (f" +{len(left) - 3}" if len(left) > 3 else "")
        else:
            m = str(self.pending)
        q = QUIPS[int(el / 4.5) % len(QUIPS)] if el > 4 else ""
        return f"{self.FRAMES[i % 10]} {m}" + (f" · {q}" if q else "")

    def loop(self):
        i, t0 = 0, time.time()
        while not self.stop.is_set():
            el = time.time() - t0
            im = idle_mood(el)
            mood = "wait" if im == "happy" else im
            self.live.draw(uppa_frame(self.text(i, el), mood, lift=int(el * 1.5) % 2))
            i += 1
            time.sleep(0.09)

    def __exit__(self, *a):
        self.stop.set()
        if ANIM:
            self.t.join()
            self.live.clear()
            sys.stdout.write("\033[?25h")
            sys.stdout.flush()


def scan(keys=None, quiet=False):
    srcs = [s for s in SOURCES if (not keys or s.key in keys) and s.available()]
    pending = {s.key: s.title for s in srcs}
    results = {}

    def work(s):
        try:
            items, summary = s.scan()
            results[s.key] = {"items": [i.to_dict() for i in items], "summary": summary, "error": ""}
        except Exception as e:
            results[s.key] = {"items": [], "summary": "", "error": f"{type(e).__name__}: {e}"}
        pending.pop(s.key, None)

    if quiet or not ANIM:
        with ThreadPoolExecutor(len(srcs) or 1) as ex:
            list(ex.map(work, srcs))
    else:
        with Spinner(pending), ThreadPoolExecutor(len(srcs) or 1) as ex:
            list(ex.map(work, srcs))
    cache = load_json(CACHE, {"sources": {}})
    cache.setdefault("sources", {}).update(results)
    if not keys:
        cache["sources"] = {k: v for k, v in cache["sources"].items() if k in results}
    cache["time"] = time.time()
    save_json(CACHE, cache)
    return cache


def items_from(cache, include_ignored=False):
    ign = set(config()["ignore"])
    out = []
    for key in [s.key for s in SOURCES]:
        for d in cache.get("sources", {}).get(key, {}).get("items", []):
            it = Item.from_dict(d)
            if include_ignored or it.key not in ign:
                out.append(it)
    return out


def match(items, words):
    """Words can be a source key (brew), source:name, or a bare name (case-insensitive)."""
    if not words:
        return items
    res = []
    for it in items:
        for w in words:
            wl = w.lower()
            if wl == it.source or wl == it.key.lower() or wl == it.name.lower() or wl == it.label.lower():
                res.append(it)
                break
    return res


# ───────────────────────────── status ─────────────────────────────
def cols_for(w, names):
    """Kolumnbredder: namn · nuvarande → senaste · etikett. Krymper med terminalen."""
    vw = 12 if w >= 84 else 11
    bw = 8 if w >= 72 else 2
    # rad = 5 indrag + namn + 2 + nuv + " →  " + ny + etikett (+1 marginal)
    namew = max(12, min(max([len(n) for n in names] + [12]), w - 1 - 5 - 2 - 4 - 2 * vw - bw))
    return namew, vw, bw


def item_rows(i, cols, w):
    """En rad i breda fönster, två rader (namn / versioner) i smala."""
    if w >= 58:
        return ["     " + item_line(i, cols)]
    namew, vw, bw = cols
    full = item_line(i, (0, vw, bw))
    return ["     " + bold(cut(i.label, w - 7)), "       " + full.lstrip()]


def item_line(i, cols=None):
    namew, vw, bw = cols or cols_for(min(width(), 104), [i.label])
    name = pad(cut(i.label, namew), namew + 2) if namew else ""
    if i.outdated:
        cur = pad(dim(cut(i.current or "–", vw)), vw)
        new = pad(green(cut(i.latest, vw)), vw)
        badge = ""
        if i.current and i.latest != "?" and major_bump(i.current, i.latest):
            badge = (c("1;38;5;232;48;5;214", " MAJOR ") if COLOR else "[MAJOR]") if bw >= 8 else yellow("▲")
        note = dim("  " + i.note) if i.note else ""
        return f"{name}{cur} {dim('→')}  {new}{badge}{note}"
    return f"{name}{dim(cut(i.current, vw))} {green('✔')}"


def section_head(title, sub, right, w):
    left = f"  {accent('▍')}{bold(title)}"
    room = w - 1 - vlen(left) - vlen(right) - 4
    if sub and room > 8:
        left += "  " + dim(cut(ANSI.sub("", sub), room))
    return left + " " * max(2, w - 1 - vlen(left) - vlen(right)) + right


def ago(secs):
    if secs < 90:
        return "nyss"
    if secs < 3600:
        return f"{int(secs // 60)} min sedan"
    if secs < 86400:
        return f"{int(secs // 3600)} h sedan"
    return f"{int(secs // 86400)} d sedan"


def print_status(cache, words=None, show_all=False, hints=True):
    items = items_from(cache)
    sel = match(items, words) if words else items
    W = min(width(), 104)
    cols = cols_for(W, [i.label for i in sel if i.outdated or show_all])
    total = majors = 0
    for s in SOURCES:
        data = cache.get("sources", {}).get(s.key)
        if not data:
            continue
        its = [i for i in sel if i.source == s.key]
        if words and not its and s.key not in [x.lower() for x in words]:
            continue
        outd = [i for i in its if i.outdated]
        total += len([i for i in outd if not i.manual])
        majors += len([i for i in outd if i.current and i.latest != "?" and major_bump(i.current, i.latest)])
        if data.get("error"):
            right = red("✘ fel")
        elif s.key == "puppa" and not its:
            right = dim("○ inte installerad")
        elif outd:
            right = yellow(f"{len(outd)} att uppdatera")
        else:
            right = green("✔ aktuellt")
        print(fit(section_head(s.title.upper(), data["summary"], right, W)))
        if data.get("error"):
            print(fit(dim("     " + data["error"])))
        show = its if show_all else outd
        limit = None if (show_all or words) else 8
        for i in show[:limit]:
            for row in item_rows(i, cols, W):
                print(fit(row))
        if limit and len(show) > limit:
            print(fit(dim(f"     … +{len(show) - limit} till  →  uppa status {s.key}")))
        if show:
            print()
    print(dim("  " + "─" * (W - 4)))
    if total:
        left = f"  {yellow('▲')} {bold(str(total))} kan uppdateras" + \
               (dim(f" · {majors} nya huvudversioner") if majors else "")
    else:
        left = f"  {green('✔')} Allt är uppdaterat"
    right = dim("skannat " + ago(time.time() - cache.get("time", 0)))
    print(fit(left + " " * max(2, W - 1 - vlen(left) - vlen(right)) + right))
    n_ign = len(config()["ignore"])
    if n_ign:
        print(dim(f"    {n_ign} ignoreras (uppa ignore)"))
    if hints:
        print(fit(dim("    uppa update · uppa select · uppa changes · uppa status --refresh")))
    print()
    return total


# ───────────────────────────── update engine ─────────────────────────────
def build_plan(items):
    keys = {i.key for i in items}
    tasks = []
    for s in SOURCES:
        its = [i for i in items if i.source == s.key and not i.manual]
        if its:
            tasks += s.tasks(its, keys)
    return tasks


def print_plan(tasks):
    print(f"  {bold('Plan')}")
    for t in tasks:
        tag = yellow(" (egen terminal)") if t.interactive else ""
        print(fit(f"   {accent('•')} {pad(cut(t.label, 40), 41)} {dim(show_cmd(t.cmd))}{tag}"))
        if len(t.items) > 1:
            names = ", ".join(f"{i.name} (ny)" if i.current == "–" else f"{i.name} {i.current}→{i.latest}" for i in t.items)
            print(dim("       " + cut(names, width() - 10)))
    print()


def ask(prompt, default=True, extra=""):
    if not sys.stdin.isatty():
        return default
    opts = "[J/n" + extra + "]" if default else "[j/N" + extra + "]"
    try:
        a = input(fit(f"  {accent('?')} {bold(prompt)} {dim(opts)}") + " ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not a:
        return default
    return a if a in extra.lower().split("/")[1:] else a in ("j", "ja", "y", "yes")


class Board:
    def __init__(self, tasks):
        self.tasks = tasks
        self.live = Live()
        self.lock = threading.Lock()

    def draw(self, final=False):
        if not ANIM:
            return
        with self.lock:
            w = min(width(), 120)
            lw = 28 if w >= 90 else 18
            done = sum(t.state in ("ok", "fail", "skip") for t in self.tasks)
            running = sum(t.state == "running" for t in self.tasks)
            lanes = len({t.lane for t in self.tasks})
            out = [f"  {accent('»')} {len(self.tasks)} jobb · {lanes} spår parallellt  "
                   f"{dim(f'{running} kör · {done}/{len(self.tasks)} klara')}"]
            fr = Spinner.FRAMES[int(time.time() * 11) % 10]
            for t in self.tasks:
                icon = {"ok": green("✔"), "fail": red("✘"), "running": accent(fr), "waiting": dim("◌"),
                        "skip": yellow("–")}.get(t.state, dim("○"))
                msg = {"waiting": "väntar på " + ", ".join(sorted(t.after)), "queued": "i kö",
                       "ok": "klart", "skip": "hoppas över"}.get(t.state, t.last)
                if t.state == "fail":
                    msg = "misslyckades" + (": " + t.last if t.last else "")
                lane = pad(dim(t.lane), 12) if w >= 70 else ""
                used = 5 + lw + 1 + (12 if w >= 70 else 0) + 6
                line = f"   {icon} {pad(cut(t.label, lw), lw + 1)}{lane}{pad(dim(t.secs), 6)}" \
                       f"{dim(cut(msg, max(6, w - used - 2)))}"
                out.append(line)
            n = len(self.tasks)
            bw = max(10, min(30, w - 16))
            f = int(bw * done / n) if n else bw
            out.append(f"  {dim('▕')}{accent('█' * f)}{dim('░' * (bw - f) + '▏')} {done}/{n}")
            self.live.draw(out)


def exec_task(t, log):
    def one(cmd):
        t.last = "$ " + show_cmd(cmd)[:80]
        try:
            p = subprocess.Popen(resolve(cmd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                                 env={**os.environ, **t.env}, bufsize=1)
        except FileNotFoundError:
            t.output.append(f"{cmd[0]}: hittades inte")
            return 127
        for line in p.stdout:
            line = line.rstrip()
            t.output.append(line)
            if line.strip():
                t.last = ANSI.sub("", line).strip()
        return p.wait()

    t.state, t.t0 = "running", time.time()
    rc = one(t.cmd)
    if rc != 0 and t.fallback:
        t.output.append("== samlad körning misslyckades, provar en i taget ==")
        bad = []
        for cmd in t.fallback:
            if one(cmd) != 0:
                bad.append(cmd[-1])
        t.failed_parts = bad
        rc = 1 if bad else 0
    t.t1 = time.time()
    t.state = "ok" if rc == 0 else "fail"
    if rc != 0:
        t.last = next((l for l in reversed(t.output) if re.search(r"error|fel|failed|denied", l, re.I)),
                      t.last)
    log.write(f"\n===== {t.label} [{t.lane}] rc={rc} {t.secs}\n$ {show_cmd(t.cmd)}\n" + "\n".join(t.output) + "\n")
    log.flush()


def run_plan(tasks, jobs=4, unattended=False):
    LOGS.mkdir(parents=True, exist_ok=True)
    logpath = LOGS / datetime.now().strftime("%Y%m%d-%H%M%S.log")
    bg = [t for t in tasks if not t.interactive]
    fg = [t for t in tasks if t.interactive]
    with open(logpath, "w", encoding="utf-8") as log:
        log.write(f"uppa {VERSION} {datetime.now().isoformat()} unattended={unattended}\n")
        if bg:
            lanes = {}
            for t in bg:
                lanes.setdefault(t.lane, []).append(t)
            done_ev = {l: threading.Event() for l in lanes}
            sem = threading.Semaphore(max(1, jobs))
            board = Board(bg)

            def lane_worker(lane, ts):
                for t in ts:
                    deps = [d for d in t.after if d in done_ev and d != lane]
                    if deps:
                        t.state = "waiting"
                        for d in deps:
                            done_ev[d].wait()
                        failed = [x for x in bg if x.lane in deps and x.state == "fail"]
                        if failed:
                            t.state, t.last = "skip", f"{failed[0].label} misslyckades"
                            continue
                    with sem:
                        exec_task(t, log)
                done_ev[lane].set()

            if ANIM:
                sys.stdout.write("\033[?25l")
            threads = [threading.Thread(target=lane_worker, args=(l, ts), daemon=True) for l, ts in lanes.items()]
            for th in threads:
                th.start()
            last_states = {}
            try:
                while any(th.is_alive() for th in threads):
                    if ANIM:
                        board.draw()
                    else:
                        for t in bg:
                            if last_states.get(id(t)) != t.state and t.state in ("running", "ok", "fail", "skip"):
                                print(f"  [{t.state:7}] {t.label} ({t.lane}) {t.secs}", flush=True)
                                last_states[id(t)] = t.state
                    time.sleep(0.1)
                if ANIM:
                    board.draw()
                else:
                    for t in bg:
                        if last_states.get(id(t)) != t.state:
                            print(f"  [{t.state:7}] {t.label} ({t.lane}) {t.secs}", flush=True)
            finally:
                if ANIM:
                    sys.stdout.write("\033[?25h")
        for t in fg:
            if unattended:
                t.state, t.last = "skip", "kräver lösenord/terminal – kör uppa update själv"
                log.write(f"\n===== {t.label} SKIPPED (interactive)\n")
                continue
            print(f"\n  {accent('▶')} {bold(t.label)}  {dim('$ ' + show_cmd(t.cmd))}")
            t.state, t.t0 = "running", time.time()
            rc = subprocess.call(resolve(t.cmd), env={**os.environ, **t.env})
            t.t1 = time.time()
            t.state = "ok" if rc == 0 else "fail"
            log.write(f"\n===== {t.label} [interaktiv] rc={rc} {t.secs}\n$ {' '.join(t.cmd)}\n")
    return logpath


def summarize(tasks, logpath, unattended=False):
    ok = [t for t in tasks if t.state == "ok"]
    fail = [t for t in tasks if t.state == "fail"]
    skip = [t for t in tasks if t.state == "skip"]
    print(f"\n  {bold('Sammanfattning')}")
    for t in tasks:
        icon = {"ok": green("✔"), "fail": red("✘"), "skip": yellow("–")}.get(t.state, dim("?"))
        extra = ""
        if t.failed_parts:
            extra = red("  misslyckades: " + ", ".join(t.failed_parts))
        elif t.state != "ok" and t.last:
            extra = dim("  " + cut(t.last, 60))
        print(f"   {icon} {pad(cut(t.label, 34), 35)}{pad(dim(t.lane), 12)}{dim(t.secs)}{extra}")
    print(dim(f"\n  logg: {str(logpath).replace(str(HOME), '~')}"))
    print()
    if not fail and not skip:
        celebrate(f"Klart! {len(ok)} jobb gick vägen. Allt är uppat.")
    elif fail:
        say(f"Det gick inte hela vägen. {len(fail)} misslyckades – loggen visar varför, resten gick bra.", "sad")
    else:
        say(f"Klart, men {len(skip)} behöver dig (lösenord eller UAC). Kör uppa update när du sitter vid datorn.", "worry")
    print()
    st = load_json(STATE, {})
    st["last_run"] = {"time": time.time(), "unattended": unattended, "ok": len(sum((t.items for t in ok), [])),
                      "fail": [t.label for t in fail], "skip": [t.label for t in skip], "log": str(logpath),
                      "seen": not unattended}
    save_json(STATE, st)


def do_update(items, args, unattended=False):
    items = [i for i in items if i.outdated and not i.manual]
    if not items:
        say("Inget att uppdatera. Allt är redan fräscht.", "proud")
        print()
        return 0
    tasks = build_plan(items)
    print_plan(tasks)
    if args.dry_run:
        say("Torrkörning: inget kördes. Så här skulle det se ut.", "happy")
        print()
        return 0
    if not (args.yes or unattended):
        a = ask("Kör?", True, "/c")
        if a == "c":
            show_changes(items)
            a = ask("Kör?", True)
        if not a:
            say("Okej, inget ändrat.", "happy")
            print()
            return 1
    logpath = run_plan(tasks, args.jobs, unattended)
    summarize(tasks, logpath, unattended)
    try:
        scan([s for s in {t.items[0].source for t in tasks if t.items}], quiet=True)
    except Exception:
        pass
    return 1 if any(t.state == "fail" for t in tasks) else 0


# ───────────────────────────── changes ─────────────────────────────
GH_RE = re.compile(r"github\.com[/:]([\w.-]+)/([\w.-]+?)(?:\.git)?(?:[/#?]|$)")


def gh_repo_for(i):
    url = ""
    try:
        if i.source == "brew":
            kind = "--cask" if i.meta.get("kind") == "cask" else "--formula"
            d = json.loads(run(["brew", "info", "--json=v2", kind, i.name], env=BREW_ENV)[1] or "{}")
            e = (d.get("formulae") or d.get("casks") or [{}])[0]
            url = " ".join(str(x) for x in [e.get("urls", {}).get("stable", {}).get("url"), e.get("homepage"),
                                            e.get("url")] if x)
        elif i.source == "npm":
            url = run(["npm", "view", i.name, "repository.url"], timeout=30)[1]
        elif i.source == "pwsh":
            url = i.meta.get("uri", "")
            if i.name == "Az" or i.name.startswith("Az."):
                url = "https://github.com/Azure/azure-powershell"
            elif i.name.startswith("Microsoft.Graph"):
                url = "https://github.com/microsoftgraph/msgraph-sdk-powershell"
        elif i.source == "self":
            url = "https://github.com/" + repo_for("uppa")[0]
        elif i.source == "az":
            url = "https://github.com/Azure/bicep" if i.name == "bicep" else ""
    except Exception:
        pass
    m = GH_RE.search(url or "")
    return (m.group(1), m.group(2)) if m else None


def gh_api(path):
    if have("gh") and run(["gh", "auth", "status"], timeout=15)[0] == 0:
        rc, out, _ = run(["gh", "api", path], timeout=30)
        if rc == 0:
            return json.loads(out)
    h = {"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"]} if os.environ.get("GITHUB_TOKEN") else {}
    return http_json("https://api.github.com/" + path, headers=h)


def render_notes(body, w, maxlines):
    lines, skip, boiler = [], False, False
    for raw in (body or "").splitlines():
        l = re.sub(r"<[^>]+>", "", raw.replace("\ufeff", "")).rstrip()
        if l.strip().startswith("```"):
            skip = not skip
            continue
        if l.lstrip().startswith("#"):
            boiler = bool(re.search(r"docker images|installation|install", l, re.I))
        if skip or boiler or not l.strip() or l.strip().startswith("<!--") or \
                re.search(r"powershellgallery\.com/packages|run the following command", l, re.I):
            continue
        l = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", l)
        l = re.sub(r"\*\*([^*]+)\*\*", r"\1", l)
        if l.lstrip().startswith("#"):
            lines.append(bold(cut(l.lstrip("# "), w)))
        else:
            l = re.sub(r"^\s*[-*]\s+", "• ", l)
            lines.append(cut(l, w))
    extra = max(0, len(lines) - maxlines)
    return lines[:maxlines], extra


def show_changes(items, maxlines=12):
    items = [i for i in items if i.outdated and not i.manual]
    w = width() - 8

    def fetch(i):
        repo = gh_repo_for(i)
        if not repo:
            return i, None, []
        try:
            rels = gh_api(f"repos/{repo[0]}/{repo[1]}/releases?per_page=40")
        except Exception:
            return i, repo, []
        picked = []
        for r in rels:
            tag = r.get("tag_name") or ""
            m = re.search(r"\d+(?:\.\d+)+(?:-[\w.]+)?", tag)
            if not m or r.get("draft") or (r.get("prerelease") and "-" not in str(i.latest)):
                continue
            v = m.group(0)
            if newer(v, i.current) and not newer(v, i.latest):
                picked.append(r)
        return i, repo, picked

    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(fetch, items))
    for i, repo, rels in res:
        print(f"\n  {accent('▶')} {bold(i.label)}  {dim(i.current)} → {green(i.latest)}")
        if not repo:
            print(dim("    hittade ingen GitHub-källa för release notes"))
            continue
        if not rels:
            print(dim(f"    inga GitHub-releaser mellan versionerna · https://github.com/{repo[0]}/{repo[1]}"))
            continue
        for r in rels[:4]:
            print(f"    {cyan(r.get('name') or r.get('tag_name'))} {dim((r.get('published_at') or '')[:10])}")
            lines, extra = render_notes(r.get("body"), w, maxlines)
            for l in lines:
                print("      " + l)
            if extra:
                print(dim(f"      … +{extra} rader  {r.get('html_url')}"))
        if len(rels) > 4:
            print(dim(f"    … +{len(rels) - 4} äldre releaser"))
    print()


# ───────────────────────────── select (checklist) ─────────────────────────────
_KEYS = None


class Keys:
    """Rå tangentläsning. Windows: msvcrt. macOS/Linux: termios + select. read() ger None vid timeout,
    så menyerna kan rita om när fönstret ändrat storlek (fungerar även där SIGWINCH saknas)."""

    def __enter__(self):
        global _KEYS
        if IS_WIN:
            import msvcrt
            self.m = msvcrt
        else:
            import termios
            import tty
            self.fd = sys.stdin.fileno()
            self.old = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
        _KEYS = self
        sys.stdout.write("\033[?25l")
        sys.stdout.flush()
        return self

    def restore(self):
        if not IS_WIN:
            import termios
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()

    def __exit__(self, *a):
        global _KEYS
        self.restore()
        _KEYS = None

    def read(self, timeout=0.25):
        if IS_WIN:
            end = time.time() + timeout
            while time.time() < end:
                if self.m.kbhit():
                    ch = self.m.getwch()
                    if ch in ("\x00", "\xe0"):
                        return {"H": "\x1b[A", "P": "\x1b[B", "K": "\x1b[D", "M": "\x1b[C"}.get(self.m.getwch(), "")
                    return ch
                time.sleep(0.02)
            return None
        import select
        r, _, _ = select.select([self.fd], [], [], timeout)
        return os.read(self.fd, 3).decode(errors="ignore") if r else None


def term_size():
    t = shutil.get_terminal_size((100, 30))
    return t.columns, t.lines


def pick(rows, chosen, title, line_fn, can_pick=lambda v: True, hotkeys=None, help_extra=""):
    """rows = [("head", text) | ("item", obj)]; returns the chosen objs. hotkeys: char -> f(chosen, obj) -> set."""
    sel = [k for k, r in enumerate(rows) if r[0] == "item" and can_pick(r[1])]
    if not sel:
        return []
    pos, top = sel[0], 0
    live = Live()

    def draw():
        nonlocal top
        h = max(4, shutil.get_terminal_size((100, 30)).lines - 4)
        top = min(max(top, pos - h + 1), pos)
        top = max(0, min(top, max(0, len(rows) - h)))
        out = [f"  {accent('▍')}{bold(title)}  {dim(f'{len(chosen)} valda')}"]
        for k in range(top, min(len(rows), top + h)):
            kind, v = rows[k]
            if kind == "head":
                out.append("  " + accent(v.upper()))
                continue
            mark = (green("◉") if id(v) in chosen else dim("○")) if can_pick(v) else green("✔")
            out.append(f" {accent('❯' if k == pos else ' ')} {mark} {line_fn(v)}")
        out.append(dim("  ↑/↓ flytta · space välj · a alla · n inga" + help_extra + " · enter kör · q avbryt"))
        live.draw(out)

    with Keys() as kb:
        size = None
        while True:
            if size != term_size():
                size = term_size()
                draw()
            ch = kb.read()
            if ch is None:
                continue
            size = None
            idx = sel.index(pos)
            if ch in ("\x1b[A", "k"):
                pos = sel[max(0, idx - 1)]
            elif ch in ("\x1b[B", "j"):
                pos = sel[min(len(sel) - 1, idx + 1)]
            elif ch == " ":
                chosen ^= {id(rows[pos][1])}
            elif ch == "a":
                chosen = {id(rows[k][1]) for k in sel}
            elif ch == "n":
                chosen = set()
            elif hotkeys and ch in hotkeys:
                chosen = hotkeys[ch](chosen, rows[pos][1])
            elif ch in ("\r", "\n"):
                break
            elif ch in ("q", "\x1b", "\x03"):
                chosen = set()
                break
    print()
    return [rows[k][1] for k in sel if id(rows[k][1]) in chosen]


def checklist(items):
    rows = []
    for s in SOURCES:
        its = [i for i in items if i.source == s.key and i.outdated and not i.manual]
        if its:
            rows.append(("head", s.title))
            rows += [("item", i) for i in its]
    pickable = [r[1] for r in rows if r[0] == "item"]

    def whole_source(chosen, cur):
        ids = {id(i) for i in pickable if i.source == cur.source}
        return chosen - ids if ids <= chosen else chosen | ids

    names = [i.label for i in pickable]
    return pick(rows, {id(i) for i in pickable}, "Välj vad som ska uppdateras",
                lambda i: item_line(i, cols_for(min(width(), 104) - 4, names)),
                hotkeys={"s": whole_source}, help_extra=" · s hela källan")


# ───────────────────────────── nudge / schedule ─────────────────────────────
BEGIN, END = "# >>> uppa nudge >>>", "# <<< uppa nudge <<<"
SH_BODY = 'command -v uppa >/dev/null 2>&1 && uppa _nudge'
PS_BODY = 'if (Get-Command uppa -ErrorAction SilentlyContinue) { uppa _nudge }'


def rc_files():
    """zsh/bash på macOS/Linux, plus PowerShell-profilerna (pwsh 7 och Windows PowerShell) där de finns."""
    files = []
    if not IS_WIN:
        sh = os.environ.get("SHELL", "")
        if sh.endswith("bash"):
            files.append(HOME / (".bash_profile" if IS_MAC else ".bashrc"))
        else:
            files.append(HOME / ".zshrc")
    if have("pwsh"):
        prof = run(ps_cmd("$PROFILE.CurrentUserCurrentHost"), timeout=60)[1].strip()
        if prof:
            files.append(Path(prof))
            if IS_WIN:
                files.append(Path(prof).parent.parent / "WindowsPowerShell" / "Microsoft.PowerShell_profile.ps1")
    elif IS_WIN:
        files.append(HOME / "Documents" / "WindowsPowerShell" / "Microsoft.PowerShell_profile.ps1")
    return files


def body_for(path):
    return PS_BODY if str(path).lower().endswith(".ps1") else SH_BODY


def nudge_on():
    return [f for f in rc_files() if f.exists() and BEGIN in f.read_text(encoding="utf-8", errors="replace")]


def add_block(path, body):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    text = Path(path).read_text(encoding="utf-8", errors="replace") if Path(path).exists() else ""
    if BEGIN in text:
        return False
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"\n{BEGIN}\n{body}\n{END}\n")
    return True


def remove_block(path):
    p = Path(path)
    if not p.exists():
        return False
    text = p.read_text(encoding="utf-8")
    new = re.sub(r"\n?" + re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", "\n", text, flags=re.S)
    if new == text:
        return False
    p.write_text(new.rstrip("\n") + "\n", encoding="utf-8")
    return True


def parse_dur(s):
    m = re.fullmatch(r"(\d+)([mhd])", s or "")
    return int(m.group(1)) * {"m": 60, "h": 3600, "d": 86400}[m.group(2)] if m else None


def parse_at(s):
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", s or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ValueError("tid ska vara HH:MM")
    return int(m.group(1)), int(m.group(2))


def nudge_hook():
    """Called from the shell profile. Must be fast and never fail loudly."""
    try:
        st = load_json(STATE, {})
        now = time.time()
        lr = st.get("last_run")
        if lr and not lr.get("seen"):
            msg = f"schemakörningen uppdaterade {lr['ok']} st"
            if lr.get("skip"):
                msg += f", hoppade över {len(lr['skip'])} (kräver dig) → uppa update"
            if lr.get("fail"):
                msg += f", {len(lr['fail'])} misslyckades → uppa doctor"
            print(f"  {accent(LOGO)} {bold('uppa')} {msg}")
            lr["seen"] = True
            save_json(STATE, st)
        cache = load_json(CACHE, {})
        stale = now - cache.get("time", 0) > 20 * 3600
        lock = DIR / "refresh.lock"
        if stale and not (lock.exists() and now - lock.stat().st_mtime < 3600):
            DIR.mkdir(parents=True, exist_ok=True)
            lock.touch()
            detach = {"creationflags": 0x00000008 | 0x00000200} if IS_WIN else {"start_new_session": True}
            subprocess.Popen([sys.executable, os.path.abspath(__file__), "_refresh"], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **detach)
        if now < st.get("snooze_until", 0) or st.get("nudged_day") == datetime.now().strftime("%Y-%m-%d"):
            return
        items = [i for i in items_from(cache) if i.outdated and not i.manual]
        if not items:
            return
        me = next((i for i in items if i.source == "self"), None)
        if me:
            print(f"  {accent(LOGO)} {bold('uppa')} {me.latest} finns på GitHub → {bold('uppa self-update')}")
            items = [i for i in items if i is not me]
            if not items:
                st["nudged_day"] = datetime.now().strftime("%Y-%m-%d")
                save_json(STATE, st)
                return
        srcs = {}
        for i in items:
            srcs[BY_KEY[i.source].title] = srcs.get(BY_KEY[i.source].title, 0) + 1
        top = ", ".join(f"{k} {v}" for k, v in sorted(srcs.items(), key=lambda x: -x[1])[:4])
        print(f"  {accent(LOGO)} {bold('uppa')} {len(items)} saker kan uppdateras ({top}) → {bold('uppa update')}")
        st["nudged_day"] = datetime.now().strftime("%Y-%m-%d")
        save_json(STATE, st)
    except Exception:
        pass


def cmd_nudge(a):
    st = load_json(STATE, {})
    if a.action == "enable":
        for rc in rc_files():
            print(f"  {green('✔')} lade till påminnelsen i {rc}" if add_block(rc, body_for(rc))
                  else f"  redan påslagen i {rc}")
    elif a.action == "disable":
        removed = [rc for rc in rc_files() if remove_block(rc)]
        for rc in removed:
            print(f"  {green('✔')} tog bort blocket ur {rc}")
        if not removed:
            print("  var inte påslagen")
    elif a.action == "snooze":
        secs = parse_dur(a.arg or "7d")
        if not secs:
            sys.exit("  ange t.ex. 3d, 12h eller 30m")
        st["snooze_until"] = time.time() + secs
        save_json(STATE, st)
        print(f"  tyst till {datetime.fromtimestamp(st['snooze_until']).strftime('%Y-%m-%d %H:%M')}")
    else:
        on = nudge_on()
        print(f"  påminnelse: {green('på') if on else dim('av')}" + (dim(" · " + ", ".join(map(str, on))) if on else ""))
        if st.get("snooze_until", 0) > time.time():
            print(f"  tyst till {datetime.fromtimestamp(st['snooze_until']).strftime('%Y-%m-%d %H:%M')}")


def plist_xml(daily, hh, mm):
    cal = f"<key>Hour</key><integer>{hh}</integer><key>Minute</key><integer>{mm}</integer>"
    if not daily:
        cal = "<key>Weekday</key><integer>1</integer>" + cal
    args = "".join(f"<string>{x}</string>" for x in
                   [sys.executable, os.path.abspath(__file__), "update", "--yes", "--unattended"])
    path = os.pathsep.join(EXTRA_PATH)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
 <key>Label</key><string>{LABEL}</string>
 <key>ProgramArguments</key><array>{args}</array>
 <key>StartCalendarInterval</key><dict>{cal}</dict>
 <key>EnvironmentVariables</key><dict><key>PATH</key><string>{path}</string><key>UPPA_NO_ANIM</key><string>1</string></dict>
 <key>StandardOutPath</key><string>{LOGS}/schedule.out</string>
 <key>StandardErrorPath</key><string>{LOGS}/schedule.out</string>
</dict></plist>
"""


TASK_NAME = "uppa-update"
CRON_TAG = "# uppa-update"


def runner():
    """Python + skript för schemakörning (pythonw på Windows, så inget konsolfönster blinkar upp)."""
    py = sys.executable
    if IS_WIN:
        w = Path(py).with_name("pythonw.exe")
        py = str(w) if w.exists() else py
    return py, os.path.abspath(__file__)


def schedule_on():
    if IS_MAC:
        return PLIST.exists()
    if IS_WIN:
        return run(["schtasks", "/Query", "/TN", TASK_NAME])[0] == 0
    return CRON_TAG in run(["crontab", "-l"])[1]


def cmd_schedule(a):
    if IS_WIN or not IS_MAC:
        return schedule_other(a)
    uid = os.getuid()
    if a.action == "enable":
        hh, mm = parse_at(a.at)
        xml = plist_xml(a.daily, hh, mm)
        when = ("varje dag" if a.daily else "måndagar") + f" {hh:02d}:{mm:02d}"
        if a.dry_run:
            print(f"  skulle skriva {PLIST} ({when}):\n\n{xml}")
            return
        LOGS.mkdir(parents=True, exist_ok=True)
        PLIST.parent.mkdir(parents=True, exist_ok=True)
        run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"])
        PLIST.write_text(xml, encoding="utf-8")
        rc, _, err = run(["launchctl", "bootstrap", f"gui/{uid}", str(PLIST)])
        print(f"  {green('✔')} automatisk uppdatering {when}" if rc == 0 else red(f"  launchctl: {err.strip()}"))
        print(dim("    saker som kräver lösenord (casks, sudo-npm) hoppas över och visas i nästa terminal"))
        return
    elif a.action == "disable":
        run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"])
        if PLIST.exists():
            PLIST.unlink()
        print(f"  {green('✔')} schemat borttaget")
    else:
        if not PLIST.exists():
            print(f"  schema: {dim('av')}  →  uppa schedule enable")
            return
        txt = PLIST.read_text(encoding="utf-8")
        h = re.search(r"<key>Hour</key><integer>(\d+)", txt)
        m = re.search(r"<key>Minute</key><integer>(\d+)", txt)
        when = ("måndagar" if "Weekday" in txt else "varje dag") + f" {int(h.group(1)):02d}:{int(m.group(1)):02d}"
        loaded = run(["launchctl", "print", f"gui/{uid}/{LABEL}"])[0] == 0
        print(f"  schema: {green('på') if loaded else yellow('fil finns men ej laddad')} · {when}")
        lr = load_json(STATE, {}).get("last_run")
        if lr:
            print(dim(f"  senaste körning {datetime.fromtimestamp(lr['time']).strftime('%Y-%m-%d %H:%M')} · "
                      f"{lr['ok']} ok · {len(lr.get('fail', []))} fel · logg {lr['log']}"))


def schedule_other(a):
    """Windows: Task Scheduler. Linux: crontab."""
    py, script = runner()
    if a.action == "enable":
        hh, mm = parse_at(a.at)
        when = ("varje dag" if a.daily else "måndagar") + f" {hh:02d}:{mm:02d}"
        if IS_WIN:
            cmd = ["schtasks", "/Create", "/TN", TASK_NAME, "/TR", f'"{py}" "{script}" update --yes --unattended',
                   "/SC", "DAILY" if a.daily else "WEEKLY"] + ([] if a.daily else ["/D", "MON"]) + \
                  ["/ST", f"{hh:02d}:{mm:02d}", "/F"]
            if a.dry_run:
                print("  skulle köra: " + " ".join(cmd))
                return
            rc, out, err = run(cmd)
        else:
            line = f'{mm} {hh} * * {"*" if a.daily else "1"} UPPA_NO_ANIM=1 PATH="{os.pathsep.join(EXTRA_PATH)}" ' \
                   f'"{py}" "{script}" update --yes --unattended >> "{LOGS}/schedule.out" 2>&1 {CRON_TAG}'
            if a.dry_run:
                print("  skulle lägga till i crontab:\n  " + line)
                return
            LOGS.mkdir(parents=True, exist_ok=True)
            cur = [l for l in run(["crontab", "-l"])[1].splitlines() if CRON_TAG not in l]
            rc, out, err = run(["crontab", "-"], input="\n".join(cur + [line]) + "\n")
        print(f"  {green('✔')} automatisk uppdatering {when}" if rc == 0 else red(f"  fel: {(err or out).strip()}"))
        print(dim("    saker som kräver lösenord/UAC hoppas över och visas i nästa terminal"))
    elif a.action == "disable":
        if IS_WIN:
            run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
        else:
            cur = [l for l in run(["crontab", "-l"])[1].splitlines() if CRON_TAG not in l]
            run(["crontab", "-"], input="\n".join(cur) + "\n")
        print(f"  {green('✔')} schemat borttaget")
    else:
        print(f"  schema: {green('på') if schedule_on() else dim('av  →  uppa schedule enable')}")
        lr = load_json(STATE, {}).get("last_run")
        if lr:
            print(dim(f"  senaste körning {datetime.fromtimestamp(lr['time']).strftime('%Y-%m-%d %H:%M')} · "
                      f"{lr['ok']} ok · {len(lr.get('fail', []))} fel · logg {lr['log']}"))


def which_all(cmd):
    exts = os.environ.get("PATHEXT", ".EXE;.CMD;.BAT").lower().split(";") if IS_WIN else [""]
    hits = []
    for d in os.environ.get("PATH", "").split(os.pathsep):
        for e in exts:
            f = os.path.join(d, cmd + e)
            if os.path.isfile(f) and (IS_WIN or os.access(f, os.X_OK)):
                hits.append(os.path.realpath(f))
    return list(dict.fromkeys(hits))


# ───────────────────────────── doctor / ignore ─────────────────────────────
def cmd_doctor(a):
    banner()
    ok = lambda m: print(f"  {green('✔')} {m}")
    warn = lambda m, fix="": print(f"  {yellow('▲')} {m}" + (f"\n      {dim('→ ' + fix)}" if fix else ""))
    print(f"  {bold('Källor')}")
    for s in SOURCES:
        print(f"   {green('●') if s.available() else dim('○')} {pad(s.title, 24)}{dim(s.key)}")
    print(f"\n  {bold('Kontroller')}")
    npm = BY_KEY["npm"]
    if npm.available() and npm.needs_sudo():
        warn(f"npm:s globala mapp ({npm.prefix()}) ägs av root – m365-uppdateringar kräver sudo",
             "npm config set prefix ~/.npm-global och lägg ~/.npm-global/bin i PATH, så slipper du sudo")
    # PATH shadowing
    for cmd in ("pwsh", "az", "dotnet", "m365"):
        paths = which_all(cmd)
        if len(paths) > 1:
            warn(f"{cmd} finns på flera ställen i PATH, {paths[0]} vinner", ", ".join(paths[1:]))
    if have("pwsh"):
        rc, out, _ = run(ps_cmd("$PSVersionTable.PSVersion.ToString()"), timeout=60)
        ok(f"pwsh {out.strip()} startar") if rc == 0 else warn("pwsh startar inte", "pwsh -NoProfile")
    if have("az"):
        rc, out, _ = run(["az", "account", "show", "--query", "user.name", "-o", "tsv"], timeout=60)
        ok(f"az inloggad som {out.strip()}") if rc == 0 else warn("az är inte inloggad", "az login")
    if have("m365"):
        rc, out, _ = run(["m365", "status", "--output", "text"], timeout=60)
        ok("m365 inloggad") if rc == 0 and "Logged out" not in out else warn("m365 är inte inloggad", "m365 login")
    if have("pwsh"):
        rc, out, _ = run(ps_cmd("(Get-InstalledModule -AllVersions -EA 0 | Group-Object Name | ? Count -gt 1 | "
                                "Measure-Object).Count"), timeout=300)
        n = int(out.strip() or 0) if out.strip().isdigit() else 0
        if n:
            warn(f"{n} PowerShell-moduler har gamla versioner kvar (Update-Module tar inte bort dem)",
                 "uppa clean pwsh")
    on = nudge_on()
    print(f"\n  {bold('Påslaget')}")
    print(f"   påminnelse i terminalen: {green('på') if on else dim('av  → uppa nudge enable')}")
    print(f"   schemalagd uppdatering:  {green('på') if schedule_on() else dim('av  → uppa schedule enable')}")
    ign = config()["ignore"]
    print(f"   ignoreras: {', '.join(ign) if ign else dim('inget')}")
    print()


def cmd_clean(a):
    if a.what != "pwsh":
        sys.exit("  just nu: uppa clean pwsh  (tar bort gamla versioner av PowerShell-moduler)")
    ps = ("Get-InstalledModule -AllVersions -EA 0 | Group-Object Name | ? Count -gt 1 | % { "
          "$_.Group | Sort-Object {[version]($_.Version -replace '-.*','')} -Descending | Select-Object -Skip 1 } | "
          "% { '{0}|{1}' -f $_.Name, $_.Version }")
    rows = [l.split("|") for l in run(ps_cmd(ps), timeout=300)[1].split() if "|" in l]
    if not rows:
        print(f"  {green('✔')} inga gamla versioner")
        return
    print(f"  {len(rows)} gamla versioner: " + dim(cut(", ".join(f"{n} {v}" for n, v in rows), width() * 2)))
    if a.dry_run or not (a.yes or ask("Ta bort dem?", False)):
        return
    for n, v in rows:
        rc, _, err = run(ps_cmd(f"Uninstall-Module -Name '{n}' -RequiredVersion '{v}' -Force -EA Stop"), timeout=300)
        print(f"   {green('✔') if rc == 0 else red('✘')} {n} {v}" + (dim("  " + cut(err, 60)) if rc else ""))


def cmd_ignore(a, add=True):
    cfg = config()
    if not a.keys:
        print("  ignoreras:", ", ".join(cfg["ignore"]) or dim("inget"))
        return
    for k in a.keys:
        if ":" not in k:
            sys.exit(f"  skriv källa:namn, t.ex. npm:{k}")
        if add and k not in cfg["ignore"]:
            cfg["ignore"].append(k)
        elif not add and k in cfg["ignore"]:
            cfg["ignore"].remove(k)
    save_json(CONFIG, cfg)
    print(f"  {green('✔')} ignoreras nu: {', '.join(cfg['ignore']) or 'inget'}")


# ───────────────────────────── installation från GitHub ─────────────────────────────
def repo_for(name):
    """ägare/repo + gren för uppa eller kusinen Puppa. Styrs med t.ex. PUPPA_REPO / UPPA_BRANCH
    eller config.json {"repos": {"puppa": "ägare/repo"}}."""
    env = name.upper()
    repo = os.environ.get(env + "_REPO") or (config().get("repos") or {}).get(name) or f"pipebreak33/{name}"
    return repo, os.environ.get(env + "_BRANCH", "main")


def sibling_installer(name):
    """Kommandot som kör verktygets egen installationsrad (samma som man klistrar in själv).
    Finns en lokal checkout (config.json {"local": {"puppa": "/sökväg"}}) används den i stället."""
    local = (config().get("local") or {}).get(name)
    if local:
        script = Path(local).expanduser() / ("install.ps1" if IS_WIN else "install.sh")
        if IS_WIN:
            return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)]
        return ["sh", str(script)]
    repo, branch = repo_for(name)
    base = f"https://raw.githubusercontent.com/{repo}/{branch}"
    if IS_WIN:
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", f"irm {base}/install.ps1 | iex"]
    return ["sh", "-c", f"curl -fsSL {base}/install.sh | sh"]


def is_git_checkout():
    return (Path(os.path.realpath(__file__)).parent / ".git").exists()


def cmd_self_update(a):
    me = Path(os.path.realpath(__file__))
    if is_git_checkout():                        # utvecklingskopia: hämta med git
        if a.dry_run:
            print(f"  skulle köra: git -C \"{me.parent}\" pull --ff-only")
            return 0
        rc, out, err = run(["git", "-C", str(me.parent), "pull", "--ff-only"], timeout=120)
        print(("  " + green("✔") + " " if rc == 0 else "  " + red("✘") + " ") + (out or err).strip().splitlines()[-1])
        return rc
    new, text = github_version("uppa", "uppa.py")
    repo, branch = repo_for("uppa")
    if not text:
        sys.exit(f"  kunde inte nå github.com/{repo} ({branch})")
    if not newer(new or "", VERSION):
        print(f"  {green('✔')} uppa {VERSION} är senaste versionen")
        return 0
    import ast
    try:
        ast.parse(text)
    except SyntaxError:
        sys.exit("  den nedladdade versionen är trasig, behåller nuvarande")
    if a.dry_run:
        print(f"  skulle uppdatera uppa {VERSION} → {new}")
        return 0
    if not a.yes and not ask(f"Uppdatera uppa {VERSION} → {new}?", True):
        return 1
    backup = me.with_suffix(".py.bak")
    shutil.copy2(me, backup)                     # går att backa med: mv ~/.uppa/uppa.py.bak ~/.uppa/uppa.py
    tmp = me.with_suffix(".py.new")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, me)
    print()
    celebrate(f"Jag är uppdaterad! {VERSION} → {new}. Den gamla versionen ligger kvar som uppa.py.bak.")
    print()
    return 0


# ───────────────────────────── katalog & grundpaket ─────────────────────────────
class Tool:
    def __init__(self, key, label, kind, pkg, desc, group, winget=None):
        self.key, self.label, self.kind, self.pkg, self.desc, self.group = key, label, kind, pkg, desc, group
        self.winget = winget          # "brew"-verktyg installeras med winget på Windows


CATALOG = [
    Tool("powershell", "PowerShell 7", "brew", "powershell", "pwsh, själva skalet", "CLI", "Microsoft.PowerShell"),
    Tool("azure-cli", "Azure CLI", "brew", "azure-cli", "az, Azure från terminalen", "CLI", "Microsoft.AzureCLI"),
    Tool("azd", "Azure Developer CLI", "brew", "azure-dev", "azd up, mallar", "CLI", "Microsoft.Azure.AZD"),
    Tool("bicep", "Bicep", "azbicep", "bicep", "IaC för Azure (via az bicep)", "CLI"),
    Tool("azcopy", "AzCopy", "brew", "azcopy", "snabb kopiering mot Storage", "CLI", "Microsoft.Azure.AZCopy.10"),
    Tool("dotnet", ".NET SDK", "brew", "dotnet", "dotnet, behövs för vissa moduler/verktyg", "CLI",
         "Microsoft.DotNet.SDK.10"),
    Tool("m365", "CLI for Microsoft 365", "npm", "@pnp/cli-microsoft365", "m365, hela M365 från terminalen", "CLI"),
    Tool("puppa", "Puppa", "puppa", "puppa", "PowerShell-uppgifter med några knapptryck (PnP m.m.)", "CLI"),
    Tool("resource-graph", "az: resource-graph", "azext", "resource-graph", "az graph query över alla prenumerationer",
         "CLI"),
    Tool("Microsoft.Graph", "Microsoft Graph", "pwsh", "Microsoft.Graph",
         "Graph v1.0: användare, grupper, enheter, Intune", "Microsoft 365"),
    Tool("Microsoft.Graph.Beta", "Microsoft Graph Beta", "pwsh", "Microsoft.Graph.Beta", "Graphs beta-endpoints",
         "Microsoft 365"),
    Tool("Microsoft.Entra", "Microsoft Entra", "pwsh", "Microsoft.Entra", "Entra ID-cmdlets, ersätter AzureAD",
         "Microsoft 365"),
    Tool("ExchangeOnlineManagement", "Exchange Online", "pwsh", "ExchangeOnlineManagement",
         "Connect-ExchangeOnline + Purview (IPPS)", "Microsoft 365"),
    Tool("MicrosoftTeams", "Microsoft Teams", "pwsh", "MicrosoftTeams", "Teams-policyer, telefoni, team",
         "Microsoft 365"),
    Tool("PnP.PowerShell", "PnP PowerShell", "pwsh", "PnP.PowerShell", "SharePoint Online och OneDrive",
         "Microsoft 365"),
    Tool("Microsoft.PowerApps.Administration.PowerShell", "Power Platform admin", "pwsh",
         "Microsoft.PowerApps.Administration.PowerShell", "miljöer, DLP, appar och flöden", "Microsoft 365"),
    Tool("Microsoft.PowerApps.PowerShell", "Power Apps (maker)", "pwsh", "Microsoft.PowerApps.PowerShell",
         "egna appar och flöden", "Microsoft 365"),
    Tool("PartnerCenter", "Partner Center", "pwsh", "PartnerCenter", "CSP-kunder och licenser", "Microsoft 365"),
    Tool("Az", "Az (hela)", "pwsh", "Az", "Azure PowerShell, alla tjänster (~100 moduler)", "Azure"),
    Tool("Az.Accounts", "Az.Accounts", "pwsh", "Az.Accounts", "Connect-AzAccount, kontexter", "Azure"),
    Tool("Az.Resources", "Az.Resources", "pwsh", "Az.Resources", "resursgrupper, RBAC, policy", "Azure"),
    Tool("Az.ResourceGraph", "Az.ResourceGraph", "pwsh", "Az.ResourceGraph", "Search-AzGraph", "Azure"),
    Tool("ImportExcel", "ImportExcel", "pwsh", "ImportExcel", "Export-Excel utan Office", "Verktyg"),
    Tool("PSScriptAnalyzer", "PSScriptAnalyzer", "pwsh", "PSScriptAnalyzer", "lint för dina skript", "Verktyg"),
    Tool("Pester", "Pester", "pwsh", "Pester", "tester för skript och moduler", "Verktyg"),
    Tool("Microsoft.PowerShell.SecretManagement", "SecretManagement", "pwsh",
         "Microsoft.PowerShell.SecretManagement", "hemligheter utan klartext i skript", "Verktyg"),
    Tool("Microsoft.PowerShell.SecretStore", "SecretStore", "pwsh", "Microsoft.PowerShell.SecretStore",
         "lokalt valv för SecretManagement", "Verktyg"),
    Tool("SqlServer", "SqlServer", "pwsh", "SqlServer", "Invoke-Sqlcmd och SQL-administration", "Verktyg"),
    Tool("Microsoft.WinGet.Client", "WinGet-modulen", "pwsh", "Microsoft.WinGet.Client",
         "winget från PowerShell (gör uppa snabbare på Windows)", "Verktyg"),
]
TOOL = {t.key.lower(): t for t in CATALOG}
TOOL.update({t.pkg.lower(): t for t in CATALOG})
BAS = ["powershell", "azure-cli", "Microsoft.Graph", "ExchangeOnlineManagement", "MicrosoftTeams", "Az.Accounts",
       "Az.Resources", "ImportExcel", "Microsoft.PowerShell.SecretManagement", "Microsoft.PowerShell.SecretStore",
       "PSScriptAnalyzer"]
BUILTIN_PROFILES = {
    "bas": ("grundpaket för M365/Azure-admin", BAS),
    "m365": ("bas + allt för Microsoft 365", BAS + ["Microsoft.Graph.Beta", "Microsoft.Entra", "PnP.PowerShell",
                                                    "Microsoft.PowerApps.Administration.PowerShell",
                                                    "Microsoft.PowerApps.PowerShell", "PartnerCenter", "m365",
                                                    "puppa"]),
    "azure": ("bas + Azure fullt ut", BAS + ["Az", "Az.ResourceGraph", "resource-graph", "bicep", "azcopy", "azd"]),
    "alla": ("allt i katalogen", [t.key for t in CATALOG]),
}


def profiles():
    """Inbyggda + egna i ~/.uppa/config.json: {"profiles": {"mitt": ["Microsoft.Graph", "ImportExcel"]}}."""
    prof = dict(BUILTIN_PROFILES)
    for name, keys in (config().get("profiles") or {}).items():
        prof[name.lower()] = ("eget paket", list(keys))
    return prof


def tool_for(name):
    t = TOOL.get(name.lower())
    if t:
        return t
    if name.startswith("pwsh:"):
        name = name[5:]
    return Tool(name, name, "pwsh", name, "PowerShell-modul", "Övrigt")


PS_INV = r"""
$ErrorActionPreference = 'SilentlyContinue'
$all = @(Get-InstalledModule)
$dep = @{}
foreach ($meta in 'Az', 'Microsoft.Graph', 'Microsoft.Graph.Beta', 'Microsoft.Entra') {
  $m = $all | Where-Object Name -eq $meta
  if (-not $m) { continue }
  $psd = Join-Path $m.InstalledLocation "$meta.psd1"
  $data = if (Test-Path $psd) { Import-PowerShellDataFile $psd } else { @{} }
  foreach ($d in @($data.RequiredModules) + @($data.ModuleList)) {
    if (-not $d) { continue }
    $dn = if ($d -is [string]) { $d } elseif ($d.ModuleName) { $d.ModuleName } else { $d.Name }
    if ($dn -and $dn -ne $meta) { $dep[[string]$dn] = $meta }
  }
}
@($all | ForEach-Object {
  $desc = ([string]$_.Description -split "`n")[0]
  [pscustomobject]@{ n = $_.Name; v = $_.Version.ToString(); p = $dep[$_.Name]; d = $desc }
}) | ConvertTo-Json -Compress
"""


def inventory(quiet=False):
    inv = {"brew": {}, "winget": {}, "pwsh": {}, "npm": {}, "azext": {}, "azbicep": {}, "puppa": {}, "rows": []}

    def puppa():
        m = re.search(r"\d+\.\d+(\.\d+)?", run(["puppa", "--version"], timeout=30)[1])
        inv["puppa"]["puppa"] = m.group(0) if m else "?"

    def winget():
        inv["winget"] = {p["id"]: p["version"] for p in winget_packages()}

    def brew():
        for flag in ("--formula", "--cask"):
            for line in run(["brew", "list", flag, "--versions"], env=BREW_ENV)[1].splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    inv["brew"][parts[0]] = parts[-1]

    def pwsh():
        rows = json.loads(run(ps_cmd(PS_INV), timeout=300)[1] or "[]")
        inv["rows"] = [rows] if isinstance(rows, dict) else rows
        inv["pwsh"] = {r["n"]: r["v"] for r in inv["rows"]}

    def npm():
        deps = json.loads(run(["npm", "ls", "-g", "--depth=0", "--json"], timeout=120)[1] or "{}").get("dependencies", {})
        inv["npm"] = {k: v.get("version", "?") for k, v in deps.items()}

    def az():
        for e in json.loads(run(["az", "extension", "list", "-o", "json"], timeout=120)[1] or "[]"):
            inv["azext"][e["name"]] = e["version"]
        rc, out, _ = run(["az", "bicep", "version"], timeout=60)
        m = re.search(r"version (\d+\.\d+\.\d+)", out)
        if rc == 0 and m:
            inv["azbicep"]["bicep"] = m.group(1)

    jobs = [f for f, ok in ((brew, have("brew")), (winget, IS_WIN and have("winget")), (pwsh, have("pwsh")),
                            (npm, have("npm")), (az, have("az")), (puppa, have("puppa"))) if ok]
    with (nullcontext() if quiet or not ANIM else Spinner("Kikar i lådorna efter moduler och verktyg…")):
        with ThreadPoolExecutor(4) as ex:
            list(ex.map(lambda f: f(), jobs))
    return inv


def installed(t, inv):
    if t.kind == "brew" and IS_WIN:
        return inv["winget"].get(t.winget) if t.winget else None
    return inv.get(t.kind, {}).get(t.pkg)


def cmd_scan(a):
    banner()
    inv = inventory()
    w = min(width(), 110)
    descw = w - 50
    print(fit(section_head("CLI-VERKTYG", "", "", w)))
    for t in [t for t in CATALOG if t.group == "CLI"]:
        v = installed(t, inv)
        mark, ver = (green("✔"), v) if v else (dim("○"), dim("saknas"))
        print(fit(f"     {mark} {pad(t.label, 24)}{pad(ver, 14)}" + (dim(cut(t.desc, descw)) if descw > 12 else "")))
    known = {t.pkg for t in CATALOG}
    extra = [n for n in inv["brew"] if (MS_FORMULA.match(n) or MS_CASK.match(n)) and n not in known]
    extra += [n for n in inv["npm"] if MS_NPM.match(n) and n not in known]
    for n in extra:
        print(fit(f"     {green('✔')} {pad(n, 24)}{pad(inv['brew'].get(n) or inv['npm'].get(n), 14)}{dim('utanför katalogen')}"))

    rows = inv["rows"]
    roots = sorted([r for r in rows if not r.get("p")], key=lambda r: r["n"].lower())
    subs = {}
    for r in rows:
        if r.get("p"):
            subs.setdefault(r["p"], []).append(r)
    print()
    print(fit(section_head("POWERSHELL-MODULER", f"{len(rows)} installerade · {len(roots)} huvudmoduler", "", w)))
    namew = max(14, min(max([len(r["n"]) for r in roots] + [14]), w - 30))
    restw = w - 7 - namew - 2 - 11
    for r in roots:
        n_sub = len(subs.get(r["n"], []))
        extra_txt = f"+{n_sub} undermoduler" if n_sub else ""
        line = f"     {green('●')} {pad(cut(r['n'], namew), namew + 2)}{pad(r['v'], 11)}"
        if restw >= 18:
            line += pad(dim(extra_txt), 18)
        if restw >= 34:
            line += dim(cut(r.get("d") or "", restw - 18))
        print(fit(line))
        if a.all:
            for s in sorted(subs.get(r["n"], []), key=lambda x: x["n"]):
                print(fit(dim(f"         └ {pad(s['n'], namew)}{s['v']}")))
    if subs and not a.all:
        print(dim("     undermoduler visas med  uppa scan -a"))

    print()
    print(fit(section_head("GRUNDPAKET", "", "", w)))
    bas_missing = []
    for name, (desc, keys) in profiles().items():
        tools = [tool_for(k) for k in keys]
        missing = [t for t in tools if not installed(t, inv)]
        if name == "bas":
            bas_missing = missing
        state = green("✔ komplett") if not missing else yellow(f"{len(tools) - len(missing)}/{len(tools)}")
        print(fit(f"     {pad(bold(name), 8)} {pad(state, 12)} {dim(desc)}"))
        if missing:
            print(fit(dim(f"                   saknas: {', '.join(t.label for t in missing)}")))
            print(fit(dim(f"                   →  uppa install {name}")))
    print()
    if bas_missing:
        say(f"Du saknar {len(bas_missing)} saker från grundpaketet. Kör uppa install bas – det går fort.", "worry")
    else:
        say("Grundpaketet är komplett. Du är redo för vad som helst. Nästan.", "proud")
    print()


def install_tasks(tools):
    keys = {t.key for t in tools}
    out = []
    if IS_WIN:
        for t in [t for t in tools if t.kind == "brew" and t.winget]:
            out.append(Task(t.label, ["winget", "install", "--id", t.winget, "-e", "--silent",
                                      "--accept-package-agreements", "--accept-source-agreements",
                                      "--disable-interactivity"], "winget", items=[Item("winget", t.winget, "–", "ny")]))
    brew = [t for t in tools if t.kind == "brew"] if not IS_WIN else []
    if brew:
        names = [t.pkg for t in brew]
        out.append(Task(", ".join(t.label for t in brew), ["brew", "install", "--formula", *names], "brew",
                        env=BREW_ENV, items=[Item("brew", t.pkg, "–", "ny") for t in brew],
                        fallback=[["brew", "install", "--formula", n] for n in names]))
    lanes = {}
    for t in tools:
        if t.kind == "pwsh":
            lanes.setdefault(Pwsh.lane_for(t.pkg), []).append(t)
    for lane, ts in lanes.items():
        names = ",".join("'" + t.pkg.replace("'", "''") + "'" for t in ts)
        ps = (f"$ProgressPreference='SilentlyContinue'; Install-Module -Name {names} -Scope CurrentUser "
              f"-Repository PSGallery -Force -AcceptLicense -AllowClobber -ErrorAction Stop -Verbose 4>&1 | "
              f"ForEach-Object {{ $_.ToString() }}")
        out.append(Task(", ".join(t.label for t in ts) if len(ts) <= 3 else f"{len(ts)} moduler",
                        ps_cmd(ps), lane,
                        items=[Item("pwsh", t.pkg, "–", "ny") for t in ts],
                        after=("brew", "winget") if "powershell" in keys else ()))
    npm = [t for t in tools if t.kind == "npm"]
    if npm:
        sudo = BY_KEY["npm"].needs_sudo() if have("npm") else False
        args = ["npm", "install", "-g", *[t.pkg for t in npm]]
        out.append(Task(", ".join(t.label for t in npm), (["sudo"] + args) if sudo else args, "npm",
                        interactive=sudo, items=[Item("npm", t.pkg, "–", "ny") for t in npm]))
    after_az = ("brew", "winget") if "azure-cli" in keys else ()
    for t in tools:
        if t.kind == "puppa":
            out.append(Task("Puppa", sibling_installer("puppa"), "puppa", items=[Item("puppa", "puppa", "–", "ny")],
                            after=("brew", "winget") if "powershell" in keys else ()))
    for t in tools:
        if t.kind == "azext":
            out.append(Task(t.label, ["az", "extension", "add", "--name", t.pkg, "--only-show-errors"], "az",
                            items=[Item("az", t.pkg, "–", "ny")], after=after_az))
        elif t.kind == "azbicep":
            out.append(Task(t.label, ["az", "bicep", "install"], "az", items=[Item("az", "bicep", "–", "ny")],
                            after=after_az))
    return out


def verify_ps_names(tools):
    """Okända modulnamn kontrolleras mot PowerShell Gallery innan något körs."""
    unknown = [t for t in tools if t.kind == "pwsh" and t.group == "Övrigt"]
    if not unknown or not have("pwsh"):
        return tools
    names = ",".join("'" + t.pkg.replace("'", "''") + "'" for t in unknown)
    out = run(ps_cmd(f"Find-PSResource -Name {names} -Repository PSGallery -EA SilentlyContinue | % Name"),
              timeout=180)[1]
    found = {n.strip().lower() for n in out.split()}
    for t in unknown:
        if t.pkg.lower() not in found:
            print(f"  {red('✘')} {t.pkg} finns inte i PowerShell Gallery, hoppar över")
    return [t for t in tools if not (t in unknown and t.pkg.lower() not in found)]


def cmd_install(a):
    banner()
    inv = inventory()
    prof = profiles()
    if not a.names:
        if not sys.stdin.isatty():
            sys.exit("  ange ett paket (" + ", ".join(prof) + ") eller modulnamn")
        rows, groups = [], {}
        for t in CATALOG:
            groups.setdefault(t.group, []).append(t)
        for g, ts in groups.items():
            rows.append(("head", g))
            rows += [("item", t) for t in ts]
        missing = lambda t: not installed(t, inv)

        def line(t):
            v = installed(t, inv)
            return f"{pad(t.label, 30)}{pad(dim(v) if v else yellow('saknas'), 16)}{dim(cut(t.desc, width() - 56))}"

        def prof_key(name):
            ids = {id(tool_for(k)) for k in prof[name][1] if missing(tool_for(k))}
            return lambda chosen, cur: ids

        say("Kryssa i det du vill ha. b, m, z och l väljer ett helt paket åt dig.", "happy")
        print()
        bas_ids = {id(tool_for(k)) for k in prof["bas"][1] if missing(tool_for(k))}
        targets = pick(rows, bas_ids, "Installera", line, can_pick=missing,
                       hotkeys={"b": prof_key("bas"), "m": prof_key("m365"), "z": prof_key("azure"),
                                "l": prof_key("alla")},
                       help_extra=" · b bas · m m365 · z azure · l alla")
        if not targets:
            print(dim("  Inget valt.\n"))
            return 0
    else:
        targets = []
        for n in a.names:
            if n.lower() in prof:
                targets += [tool_for(k) for k in prof[n.lower()][1]]
            else:
                targets.append(tool_for(n))
        targets = list({id(t): t for t in targets}.values())
    have_ = [t for t in targets if installed(t, inv)]
    todo = verify_ps_names([t for t in targets if not installed(t, inv)])
    if have_:
        print(f"  {green('✔')} redan installerat: {dim(cut(', '.join(t.label for t in have_), width() * 2))}")
    if not todo:
        print()
        say("Allt det där har du redan. Jag gillar din stil.", "proud")
        print()
        return 0
    print()
    tasks = install_tasks(todo)
    print_plan(tasks)
    if a.dry_run:
        say("Torrkörning: inget kördes. Så här skulle det se ut.", "happy")
        print()
        return 0
    if not a.yes and not ask("Installera?", True):
        say("Okej, inget ändrat.", "happy")
        print()
        return 1
    logpath = run_plan(tasks, a.jobs)
    summarize(tasks, logpath)
    try:
        scan(quiet=True)
    except Exception:
        pass
    return 1 if any(t.state == "fail" for t in tasks) else 0


# ───────────────────────────── logga ut ─────────────────────────────
# Sessionsinloggningar (EXO, Teams, PartnerCenter, PowerApps) lever bara i det pwsh-fönster där de gjordes.
# De loggas ut med:  uppa logout --ps | iex   (körs i det öppna fönstret)
LOGOUT_PS_LINES = [
    "if (Get-Module ExchangeOnlineManagement) { Disconnect-ExchangeOnline -Confirm:$false -ErrorAction SilentlyContinue; 'Exchange Online: utloggad' }",
    "if (Get-Module MicrosoftTeams) { Disconnect-MicrosoftTeams -ErrorAction SilentlyContinue; 'Teams: utloggad' }",
    "if (Get-Module PnP.PowerShell) { Disconnect-PnPOnline -ClearPersistedLogin -ErrorAction SilentlyContinue; 'PnP: utloggad' }",
    "if (Get-Module Microsoft.Entra*) { Disconnect-Entra -ErrorAction SilentlyContinue | Out-Null; 'Entra: utloggad' }",
    "if (Get-Module Microsoft.Graph.Authentication) { Disconnect-MgGraph -ErrorAction SilentlyContinue | Out-Null; 'Graph: utloggad' }",
    "if (Get-Module Az.Accounts) { Disconnect-AzAccount -ErrorAction SilentlyContinue | Out-Null; Clear-AzContext -Scope Process -Force -ErrorAction SilentlyContinue; 'Az: utloggad' }",
    "if (Get-Module PartnerCenter) { Disconnect-PartnerCenter -ErrorAction SilentlyContinue | Out-Null; 'Partner Center: utloggad' }",
    "if (Get-Module Microsoft.PowerApps.Administration.PowerShell, Microsoft.PowerApps.PowerShell) { Remove-PowerAppsAccount -ErrorAction SilentlyContinue; 'Power Apps: utloggad' }",
    "if (Get-Module Microsoft.Online.SharePoint.PowerShell) { Disconnect-SPOService -ErrorAction SilentlyContinue; 'SharePoint Online: utloggad' }",
]


def identity_cache():
    base = Path(os.environ.get("LOCALAPPDATA", str(HOME / "AppData" / "Local"))) if IS_WIN else HOME
    return base / ".IdentityService" / "msal.cache"


def pnp_settings():
    return HOME / ".m365pnppowershell" / "settings.json"


def logout_plan():
    """Vad som är inloggat/sparat just nu och hur det loggas ut. Läser bara konto-namn, aldrig tokens."""
    plan = []
    if have("az"):
        rc, out, _ = run(["az", "account", "show", "--query", "user.name", "-o", "tsv"], timeout=60)
        plan.append({"label": "Azure CLI", "who": out.strip() if rc == 0 else "",
                     "steps": [("cmd", ["az", "logout"]), ("cmd", ["az", "account", "clear"])]})
    if have("azd"):
        rc, out, _ = run(["azd", "auth", "login", "--check-status"], timeout=60)
        plan.append({"label": "Azure Developer CLI", "who": "inloggad" if rc == 0 and "Logged in" in out else "",
                     "steps": [("cmd", ["azd", "auth", "logout"])]})
    if have("m365"):
        rc, out, _ = run(["m365", "status", "--output", "text"], timeout=60)
        who = "" if rc != 0 or "Logged out" in out else (out.strip().splitlines() or ["inloggad"])[0]
        plan.append({"label": "CLI for Microsoft 365", "who": who, "steps": [("cmd", ["m365", "logout"])]})
    ctx = HOME / ".Azure" / "AzureRmContext.json"
    if ctx.exists():
        try:
            data = json.loads(ctx.read_text(encoding="utf-8-sig"))
            accts = sorted({(c.get("Account") or {}).get("Id", "") for c in (data.get("Contexts") or {}).values()} - {""})
        except Exception:
            accts = []
        plan.append({"label": "Az PowerShell", "who": ", ".join(accts) + (f" ({len(data.get('Contexts', {}))} kontexter)" if accts else ""),
                     "steps": [("ps", "Import-Module Az.Accounts; Clear-AzContext -Scope CurrentUser -Force")]})
    rec = HOME / ".mg" / "mg.authrecord.json"
    if rec.exists() or have("pwsh"):
        who = ""
        if rec.exists():
            try:
                who = json.loads(rec.read_text(encoding="utf-8")).get("username", "") or "sparad inloggning"
            except Exception:
                who = "sparad inloggning"
        broker = " -SignOutFromBroker" if IS_WIN else ""
        plan.append({"label": "Microsoft Graph / Entra", "who": who,
                     "steps": [("ps", "if (Get-Module -ListAvailable Microsoft.Graph.Authentication) { "
                                      f"Import-Module Microsoft.Graph.Authentication; Disconnect-MgGraph{broker} | Out-Null }}"),
                               ("rm", rec)]})
    pnp = pnp_settings()
    if pnp.exists():
        try:
            n = len(json.loads(pnp.read_text(encoding="utf-8")).get("Cache") or [])
        except Exception:
            n = 0
        plan.append({"label": "PnP PowerShell", "who": f"{n} sparad(e) inloggning(ar)" if n else "",
                     "steps": [("ps", "Import-Module PnP.PowerShell; Disconnect-PnPOnline -ClearPersistedLogin"),
                               ("pnpcache", pnp)]})
    cache = identity_cache()
    if cache.exists():
        plan.append({"label": "Delad token-cache (Az/Graph)", "who": "finns",
                     "steps": [("rm", cache)]})
    return plan


def do_step(kind, arg):
    if kind == "cmd":
        rc, out, err = run(arg, timeout=120)
        return rc == 0 or bool(re.search(r"no (active )?(subscriptions|accounts)|not (logged|signed) in|logged out",
                                         out + err, re.I))
    if kind == "ps":
        rc, _, _ = run(ps_cmd("$ErrorActionPreference='SilentlyContinue'; " + arg), timeout=180)
        return True
    if kind == "rm":
        try:
            Path(arg).unlink()
        except FileNotFoundError:
            pass
        return not Path(arg).exists()
    if kind == "pnpcache":                       # om -ClearPersistedLogin inte räckte: töm cachen (backup först)
        try:
            data = json.loads(Path(arg).read_text(encoding="utf-8"))
            if data.get("Cache"):
                shutil.copy2(arg, str(arg) + ".bak")
                data["Cache"] = []
                Path(arg).write_text(json.dumps(data, indent=2), encoding="utf-8")
            return True
        except Exception:
            return False
    return False


def cmd_logout(a):
    if a.ps:
        print("\n".join(LOGOUT_PS_LINES))
        return 0
    banner()
    with (nullcontext() if not ANIM else Spinner("Kollar vem du är inloggad som…")):
        plan = logout_plan()
    if not plan:
        say("Jag hittar inget att logga ut från. Du är redan utloggad.", "happy")
        return 0
    W = min(width(), 104)
    print(fit(section_head("SPARADE INLOGGNINGAR", "rensas så att alla nya fönster kräver ny inloggning", "", W)))
    lw = min(max(len(e["label"]) for e in plan) + 2, max(16, W // 2))
    for e in plan:
        state = dim(e["who"]) if e["who"] else dim("ingen aktiv inloggning")
        print(fit(f"     {yellow('●') if e['who'] else dim('○')} {pad(cut(e['label'], lw - 2), lw)}{state}"))
    print()
    print(fit(dim("     Exchange Online, Teams, Partner Center och Power Apps sparar bara i det öppna fönstret.")))
    print(fit(dim("     Logga ut dem där med:  ") + bold("uppa logout --ps | iex")))
    print()
    if a.dry_run:
        for e in plan:
            for kind, arg in e["steps"]:
                desc = show_cmd(arg) if kind == "cmd" else (f"pwsh: {arg}" if kind == "ps" else f"ta bort {arg}"
                                                           if kind == "rm" else f"töm PnP-cachen i {arg}")
                print(fit(dim(f"     {e['label']}: {desc}")))
        print()
        say("Torrkörning: inget kördes. Så här skulle det se ut.", "happy")
        print()
        return 0
    if not a.yes and not ask("Logga ut från allt ovan?", False):
        say("Okej, inget ändrat.", "happy")
        print()
        return 1
    failed = []
    for e in plan:
        ok = all([do_step(kind, arg) for kind, arg in e["steps"]])
        print(fit(f"   {green('✔') if ok else red('✘')} {e['label']}"))
        if not ok:
            failed.append(e["label"])
    print()
    if failed:
        say(f"Det gick inte hela vägen: {', '.join(failed)} krånglade. Prova igen, eller logga ut manuellt.", "sad")
    else:
        say("Utloggad från allt. Nästa Connect-… frågar efter inloggning igen. I öppna pwsh-fönster: uppa logout --ps | iex", "proud")
    print()
    return 1 if failed else 0


# ───────────────────────────── menu / cli ─────────────────────────────
def get_cache(refresh):
    cache = load_json(CACHE, {})
    if refresh or not cache.get("sources") or time.time() - cache.get("time", 0) > 3600:
        cache = scan()
    return cache


def new_screen():
    """Töm skärmen inför en meny. Har något just skrivits ut får man läsa klart först."""
    global DIRTY
    if DIRTY:
        pause()
    DIRTY = False
    if TTY:
        sys.stdout.write("\033[H\033[2J")
        sys.stdout.flush()


def pause():
    if sys.stdin.isatty():
        try:
            print()
            input(dim("   enter = tillbaka till menyn "))
        except (EOFError, KeyboardInterrupt):
            print()


def choose(rows, title="", msg="", mood="happy", sub="", status=None, start=None, footer=None, screen=False):
    """Piltangent-meny i Puppas stil. rows: ("head", text) eller dict(label, hint, value, key).
    Siffra väljer direkt, q/esc avbryter (→ None). Uppa blinkar och tittar runt medan den väntar."""
    if not sys.stdin.isatty():
        return None
    if screen:
        new_screen()
    sel = [k for k, r in enumerate(rows) if not isinstance(r, tuple)]
    if not sel:
        return None
    keys, n = {}, 0
    for k in sel:
        r = rows[k]
        if r.get("key"):
            keys[r["key"]] = k
        else:
            n += 1
            if n <= 9:
                r["_num"] = str(n)
                keys[str(n)] = k
    pos = sel[0]
    if start is not None:
        for k in sel:
            if rows[k]["value"] == start:
                pos = k
    top = 0
    live = Live()
    t0 = time.time()

    def draw(mood_now):
        nonlocal top
        w = width()
        lines = []
        if msg:
            lines += uppa_frame(msg, mood_now, sub=sub)
        if status:
            lines += [""] + status()
        lines.append("")
        if title:
            lines.append("  " + accent("▍") + bold(title))
        narrow = w < 58
        labels = [rows[k]["label"] for k in sel]
        lw = min(max(len(x) for x in labels) + 2, max(10, w - 14 if narrow else min(34, w // 2)))
        room = max(3, shutil.get_terminal_size((100, 30)).lines - len(lines) - 3)
        top = min(max(top, pos - room + 1), pos)
        top = max(0, min(top, max(0, len(rows) - room)))
        if top > 0:
            lines.append(dim("     ↑ fler"))
        for k in range(top, min(len(rows), top + room)):
            r = rows[k]
            if isinstance(r, tuple):
                lines.append("   " + dim(cut(r[1].upper(), w - 5)))
                continue
            on = k == pos
            key = r.get("key") or r.get("_num") or " "
            label = cut(r["label"], lw - 1)
            label = bold(accent(label)) if on else label
            if narrow:
                line = f"  {accent('❯') if on else ' '}{dim(key)} {label}"
            else:
                line = f"   {accent('❯') if on else ' '} {dim(key)}  " + pad(label, lw)
                if r.get("hint") and w >= 64:
                    line += dim(r["hint"])
            lines.append(line)
        if top + room < len(rows):
            lines.append(dim("     ↓ fler"))
        lines.append("")
        help_ = (footer or "↑/↓ · enter · siffra väljer · q tillbaka") if w >= 50 else "↑↓ enter · q"
        lines.append(dim("   " + help_))
        live.draw(lines)

    choice, cur_mood, size = None, None, None
    with Keys() as kb:
        while True:
            m = mood
            if ANIM:
                im = idle_mood(time.time() - t0)
                m = im if mood == "happy" else ("blink" if im == "blink" else mood)
            if size != term_size() or m != cur_mood:
                size, cur_mood = term_size(), m
                draw(m)
            ch = kb.read(0.12)
            if ch is None:
                continue
            idx = sel.index(pos)
            if ch in ("\x1b[A", "k", "\x1bOA"):
                pos = sel[(idx - 1) % len(sel)]
            elif ch in ("\x1b[B", "j", "\x1bOB"):
                pos = sel[(idx + 1) % len(sel)]
            elif ch in keys:
                pos = keys[ch]
                choice = rows[pos]["value"]
                break
            elif ch in ("\r", "\n"):
                choice = rows[pos]["value"]
                break
            elif ch in ("q", "\x1b", "\x03", "\x04"):
                break
            size = None
        live.clear()
    if choice is not None and not screen:
        print(fit(f"   {accent('❯')} {bold(rows[pos]['label'])}"))
    return choice


SHORT = {"self": "Uppa", "brew": "brew", "winget": "winget", "pwsh": "PowerShell", "az": "az-tillägg",
         "npm": "npm", "dotnet": ".NET", "puppa": "Puppa"}


def status_lines(cache):
    """Kompakt statusrad under Uppa: en prick per källa, gul siffra där något kan uppdateras."""
    w = width()
    items = items_from(cache)
    parts = []
    for s in SOURCES:
        data = cache.get("sources", {}).get(s.key)
        if not data:
            continue
        n = len([i for i in items if i.source == s.key and i.outdated and not i.manual])
        if s.key == "puppa" and not [i for i in items if i.source == "puppa"]:
            parts.append(dim("○ Puppa"))
        elif data.get("error"):
            parts.append(red("● " + SHORT.get(s.key, s.key)))
        elif n:
            parts.append(yellow("● ") + SHORT.get(s.key, s.key) + " " + yellow(str(n)))
        else:
            parts.append(green("● ") + dim(SHORT.get(s.key, s.key)))
    head = f"  {dim('Senast kollat')} {bold(ago(time.time() - cache.get('time', 0)))}"
    lines, cur = [head], "  "
    for p_ in parts:
        if vlen(cur) + vlen(p_) + 2 > w - 2 and cur.strip():
            lines.append(cur)
            cur = "  "
        cur += p_ + "  "
    if cur.strip():
        lines.append(cur)
    return lines


def file_version(path):
    try:
        m = re.search(r'^VERSION = "([^"]+)"', Path(path).read_text(encoding="utf-8"), re.M)
        return m.group(1) if m else None
    except Exception:
        return None


def menu_update_self(a):
    """Uppdatera uppa och starta om i den nya versionen, så menyn direkt kör den nya koden."""
    me = os.path.realpath(__file__)
    a.yes = False
    cmd_self_update(a)
    new = file_version(me)
    if new and new != VERSION:
        print()
        say(f"Startar om som uppa {new}…", "proud")
        if sys.stdin.isatty():
            pause()
        os.execv(sys.executable, [sys.executable, me])


def menu_update_puppa(a, item=None):
    """Puppa uppdateras genom att dess installer körs igen (samma rad som vid installation)."""
    cur = item.current if item else None
    lat = item.latest if item else None
    if item and not item.outdated:
        say(f"Puppa {cur} är redan senaste versionen. Vill du ändå installera om den?", "happy")
        if not ask("Installera om Puppa?", False):
            say("Okej, inget ändrat.", "happy")
            return
    task = Task("Puppa" + (f" {cur} → {lat}" if item and item.outdated else ""), sibling_installer("puppa"),
                "puppa", items=[item or Item("puppa", "puppa", cur or "?", lat or "?", label="Puppa")])
    print_plan([task])
    if not ask("Uppdatera Puppa?", True):
        say("Okej, inget ändrat.", "happy")
        return
    logpath = run_plan([task], 1)
    summarize([task], logpath)
    try:
        scan(["puppa"], quiet=True)
    except Exception:
        pass


def greeting(cache):
    """Uppa presenterar sig och föreslår nästa steg, som Puppa gör."""
    items = items_from(cache)
    outd = [i for i in items if i.outdated and not i.manual]
    n = len(outd)
    m = len([i for i in outd if i.current and i.latest != "?" and major_bump(i.current, i.latest)])
    me = next((i for i in outd if i.source == "self"), None)
    hi = "Hej! Jag är Uppa."
    if not cache.get("sources"):
        return f"{hi} Jag håller dina PowerShell- och Microsoft-verktyg fräscha. Ska vi skanna vad du har?", "worry"
    if not have("pwsh"):
        return f"{hi} PowerShell 7 saknas – ska jag installera grundpaketet åt dig?", "worry"
    if me:
        return f"{hi} Det finns en ny version av mig ({me.latest}). Ska vi uppa mig – och resten – nu?", "wow"
    if n == 1:
        return f"{hi} Jag hittade 1 sak som kan uppdateras. Ska jag uppa den?", "happy"
    if n and m:
        return f"{hi} Jag hittade {n} saker som kan uppdateras, varav {m} nya huvudversioner. Ska vi uppa dem?", "happy"
    if n:
        return f"{hi} Jag hittade {n} saker som kan uppdateras. Ska vi uppa dem?", "happy"
    return f"{hi} Allt är redan uppat – jag har inget att göra. Underbart.", "proud"


def menu(a):
    global DIRTY
    cache = get_cache(a.refresh)
    if not sys.stdin.isatty():
        msg, mood = greeting(cache)
        say(msg, mood, sub=f"uppa {VERSION} · PowerShell & Microsoft-CLI")
        print()
        print_status(cache)
        return
    last = None
    while True:
        cache = load_json(CACHE, {}) or cache
        items = items_from(cache)
        outd = [i for i in items if i.outdated and not i.manual]
        n = len(outd)
        m = len([i for i in outd if i.current and i.latest != "?" and major_bump(i.current, i.latest)])
        msg, mood = greeting(cache)
        me = next((i for i in items if i.source == "self"), None)
        pu = next((i for i in items if i.source == "puppa"), None)
        self_new = me.latest if me and newer(me.latest, VERSION) else None    # jämför med koden som körs nu
        self_hint = f"{VERSION} → {self_new} finns" if self_new else f"{VERSION} · senaste version"
        puppa_hint = (f"{pu.current} → {pu.latest} finns" if pu and pu.outdated
                      else (f"{pu.current} · senaste version" if pu else "kör Puppas installer igen"))
        rows = [dict(label="Uppdatera allt", hint=f"{n} st" + (f" · {m} nya huvudversioner" if m else ""),
                     value="update"),
                dict(label="Välj själv…", hint="kryssa i det som ska uppdateras", value="select"),
                dict(label="Visa allt inaktuellt", hint="version för version", value="status"),
                dict(label="Vad är nytt?", hint="release notes innan du uppdaterar", value="changes"),
                dict(label="Skanna installerat", hint="moduler, verktyg och grundpaket", value="scan"),
                dict(label="Installera grundpaket…", hint="bas · m365 · azure", value="install"),
                dict(label="Installera Puppa", hint="PowerShell-uppgifter med några knapptryck", value="puppa"),
                dict(label="Uppdatera Puppa", hint=puppa_hint, value="puppa-update"),
                dict(label="Uppdatera Uppa", hint=self_hint, value="self"),
                dict(label="Doctor", hint="inloggningar och hälsokoll", value="doctor"),
                dict(label="Logga ut från allt", hint="Graph · Az · PnP · az · m365", value="logout", key="u"),
                dict(label="Skanna om", hint="hämta färska versioner", value="refresh", key="r"),
                dict(label="Avsluta", value="quit", key="q")]
        if not n:
            rows = [r for r in rows if r["value"] not in ("update", "select", "status", "changes")]
        rows = [r for r in rows if r["value"] != ("puppa" if have("puppa") else "puppa-update")]
        v = choose(rows, msg=msg, mood=mood, status=lambda: status_lines(cache), start=last,
                   footer="↑/↓ · enter · siffra väljer · q avslutar" if width() >= 50 else None,
                   sub=f"uppa {VERSION}", screen=True)
        last = v
        if v in (None, "quit"):
            print()
            say(random.choice(["Hej då!", "Vi ses!", "Hej då! Håll modulerna fräscha.",
                               "Hej då! Jag håller koll på versionerna så länge."]), "happy")
            print()
            return
        print()
        a.names, a.all, a.ps = [], False, False
        if v == "update":
            do_update(items_from(cache), a)
        elif v == "select":
            chosen = checklist(items_from(cache))
            if chosen:
                do_update(chosen, a)
            else:
                say("Okej, inget valt.", "happy")
        elif v == "status":
            print_status(cache)
        elif v == "changes":
            show_changes(items_from(cache))
        elif v == "scan":
            cmd_scan(a)
        elif v == "install":
            cmd_install(a)
        elif v == "puppa":
            a.names = ["puppa"]
            cmd_install(a)
            if have("puppa"):
                say("Puppa är installerad. Starta den med puppa – och uppdatera den härifrån framöver.", "proud")
        elif v == "puppa-update":
            menu_update_puppa(a, pu)
        elif v == "self":
            menu_update_self(a)
        elif v == "doctor":
            cmd_doctor(a)
        elif v == "logout":
            cmd_logout(a)
        elif v == "refresh":
            cache = scan()
            say("Färska versioner hämtade.", "proud")
        DIRTY = True


def main(argv=None):
    import argparse
    global ANIM
    p = argparse.ArgumentParser(prog="uppa", description="uppa – håll PowerShell- och Microsoft-CLI-verktygen uppdaterade.")
    p.add_argument("--version", action="version", version="uppa " + VERSION)
    p.add_argument("--no-anim", action="store_true")
    sub = p.add_subparsers(dest="cmd")

    def common(sp):
        sp.add_argument("-n", "--dry-run", action="store_true", help="visa planen, ändra inget")
        sp.add_argument("-y", "--yes", action="store_true", help="fråga inte")
        sp.add_argument("-j", "--jobs", type=int, default=int(os.environ.get("UPPA_JOBS", 4)))
        sp.add_argument("--refresh", action="store_true", help="skanna om i stället för att använda cache")
        sp.add_argument("--no-anim", action="store_true", help=argparse.SUPPRESS)
        return sp

    s = common(sub.add_parser("status", help="vad är inaktuellt"))
    s.add_argument("names", nargs="*")
    s.add_argument("-a", "--all", action="store_true", help="visa även det som är aktuellt")
    s.add_argument("--quiet", action="store_true")
    u = common(sub.add_parser("update", help="uppdatera"))
    u.add_argument("names", nargs="*")
    u.add_argument("--changes", action="store_true", help="visa release notes först")
    u.add_argument("--unattended", action="store_true", help=argparse.SUPPRESS)
    common(sub.add_parser("select", help="checklista"))
    ch = common(sub.add_parser("changes", help="release notes"))
    ch.add_argument("names", nargs="*")
    common(sub.add_parser("doctor", help="hälsokoll"))
    sn = common(sub.add_parser("scan", help="vilka moduler och verktyg finns installerade + grundpaket"))
    sn.add_argument("-a", "--all", action="store_true", help="visa även undermoduler")
    ins = common(sub.add_parser("install", help="installera grundpaket (bas/m365/azure/alla) eller moduler"))
    ins.add_argument("names", nargs="*")
    sub.add_parser("hej", help="säg hej till Uppa")
    common(sub.add_parser("self-update", help="uppdatera uppa själv"))
    lo = common(sub.add_parser("logout", help="logga ut från Graph, Az, PnP, az, m365 … (sparade inloggningar)"))
    lo.add_argument("--ps", action="store_true", help="skriv ut PowerShell som loggar ut det öppna fönstret: uppa logout --ps | iex")
    cl = common(sub.add_parser("clean", help="städa gamla versioner"))
    cl.add_argument("what", nargs="?", default="pwsh")
    ig = sub.add_parser("ignore", help="ignorera källa:namn")
    ig.add_argument("keys", nargs="*")
    ug = sub.add_parser("unignore")
    ug.add_argument("keys", nargs="*")
    nd = sub.add_parser("nudge", help="påminnelse i terminalen")
    nd.add_argument("action", nargs="?", default="status", choices=["enable", "disable", "status", "snooze"])
    nd.add_argument("arg", nargs="?")
    sc = sub.add_parser("schedule", help="automatisk uppdatering")
    sc.add_argument("action", nargs="?", default="status", choices=["enable", "disable", "status"])
    sc.add_argument("--daily", action="store_true")
    sc.add_argument("--at", default="09:00")
    sc.add_argument("-n", "--dry-run", action="store_true")
    sub.add_parser("_nudge")
    sub.add_parser("_refresh")

    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0].startswith("-") and argv[0] not in ("--version", "-h", "--help"):
        argv = ["_menu"] + argv
    if argv[0] == "_menu":
        a = common(argparse.ArgumentParser()).parse_args([x for x in argv[1:] if x != "--no-anim"])
        if "--no-anim" in argv:
            ANIM = False
        a.cmd = "_menu"
    else:
        a = p.parse_args(argv)
    if getattr(a, "no_anim", False):
        ANIM = False
    def _sigint(*_):
        if _KEYS:
            _KEYS.restore()
        sys.stdout.write("\033[?25h\n")
        sys.stdout.flush()
        os._exit(130)

    signal.signal(signal.SIGINT, _sigint)

    if a.cmd == "_nudge":
        return nudge_hook()
    if a.cmd == "_refresh":
        try:
            scan(quiet=True)
        finally:
            try:
                (DIR / "refresh.lock").unlink()
            except Exception:
                pass
        return
    if a.cmd == "_menu":
        return menu(a)
    if a.cmd == "status":
        if a.quiet:
            scan(quiet=True)
            return
        banner()
        keys = {w.lower() for w in a.names if w.lower() in BY_KEY} or None
        only_sources = keys if keys and len(keys) == len(a.names) else None
        cache = scan(only_sources) if (a.refresh or not load_json(CACHE, {}).get("sources")) else \
            get_cache(False)
        print_status(cache, a.names, a.all)
        sys.exit(0)
    if a.cmd == "update":
        banner()
        cache = get_cache(a.refresh or not a.unattended)
        items = items_from(cache)
        if a.names:
            items = match(items, a.names)
            if not items:
                sys.exit(f"  hittade inget som matchar {' '.join(a.names)}  (prova uppa status -a)")
        if a.changes:
            show_changes(items)
        sys.exit(do_update(items, a, a.unattended))
    if a.cmd == "select":
        banner()
        if not sys.stdin.isatty():
            sys.exit("  select behöver en riktig terminal")
        chosen = checklist(items_from(get_cache(a.refresh)))
        if chosen:
            sys.exit(do_update(chosen, a))
        print(dim("  Inget valt.\n"))
        return
    if a.cmd == "changes":
        banner()
        items = items_from(get_cache(a.refresh))
        show_changes(match(items, a.names) if a.names else items)
        return
    if a.cmd == "doctor":
        return cmd_doctor(a)
    if a.cmd == "scan":
        return cmd_scan(a)
    if a.cmd == "install":
        sys.exit(cmd_install(a))
    if a.cmd == "logout":
        sys.exit(cmd_logout(a))
    if a.cmd == "self-update":
        sys.exit(cmd_self_update(a))
    if a.cmd == "hej":
        print()
        say(random.choice(JOKES), random.choice(["happy", "proud", "wow", "left"]))
        print()
        return
    if a.cmd == "clean":
        return cmd_clean(a)
    if a.cmd == "ignore":
        return cmd_ignore(a, True)
    if a.cmd == "unignore":
        return cmd_ignore(a, False)
    if a.cmd == "nudge":
        return cmd_nudge(a)
    if a.cmd == "schedule":
        return cmd_schedule(a)


if __name__ == "__main__":
    main()
