# Uppa

**English** · [Svenska](README.sv.md)

<p align="center">
  <img src="assets/uppa.svg" alt="Uppa: Hi! I'm Uppa." width="720">
</p>

Keeps your **PowerShell and Microsoft CLI tools** up to date on **Windows, macOS and Linux**: one command, one checklist, parallel updates, and bundles that install everything a Microsoft 365/Azure admin needs. One of the tools in the troupe with [Puppa](https://github.com/pipebreak33/puppa), [Muppa](https://github.com/pipebreak33/muppa), [Euppa](https://github.com/pipebreak33/euppa), [Ruppa](https://github.com/pipebreak33/ruppa) and [Wuppa](https://github.com/pipebreak33/wuppa). Inspired by [azup](https://github.com/saeid-adz/azup).

## Install

**Windows** (PowerShell; installs Python per user if it is missing)

```powershell
irm https://raw.githubusercontent.com/pipebreak33/uppa/main/install.ps1 | iex
```

**macOS / Linux**

```sh
curl -fsSL https://raw.githubusercontent.com/pipebreak33/uppa/main/install.sh | sh
```

Open a new terminal and run `uppa`. Want everything at once: `uppa install bas` (or `m365` / `azure`). Update Uppa itself with `uppa self-update`. Pin a version with `UPPA_BRANCH=v1.0.0` (PowerShell: `$env:UPPA_BRANCH = 'v1.0.0'`) before the install line.

## Uninstall

**Windows** (PowerShell):

```powershell
irm https://raw.githubusercontent.com/pipebreak33/uppa/main/uninstall.ps1 | iex
```

**macOS / Linux:**

```bash
curl -fsSL https://raw.githubusercontent.com/pipebreak33/uppa/main/uninstall.sh | sh
```

Removes the program and the `uppa` command (and the PATH entry on Windows). Uppa's cache and log in `~/.uppa` are kept.
`UPPA_PURGE=1` removes your data too, and `UPPA_YES=1` skips the question.

## Language

Uppa speaks **English** by default and **Swedish** on request. The choice is shared by the whole troupe:

```sh
uppa lang sv      # Swedish for every tool
uppa lang en      # back to English
```

The menu has a **Language** row too. `TRUPPA_LANG=sv` sets it for a single run. The setting lives in `~/.truppa/config.json`. Swedish command names (`uppa hej` …) still work.

## What Uppa looks after

| Source | What | How |
|---|---|---|
| CLI (Homebrew, macOS/Linux) | powershell, azure-cli, dotnet (+ azd, azcopy, sqlcmd … if installed) | `brew upgrade --formula` in one call |
| CLI (winget, Windows) | Microsoft.PowerShell, Microsoft.AzureCLI, Microsoft.DotNet.SDK.*, Microsoft.Azure.* | `winget upgrade --id … --silent` (PowerShell in its own terminal because of UAC) |
| PowerShell modules | Az, Microsoft.Graph, ExchangeOnlineManagement, MicrosoftTeams, PnP.PowerShell, PowerApps, PartnerCenter, SqlServer, ImportExcel … | `Update-Module`, three parallel lanes (Az · Graph/Entra · the rest) |
| az extensions | resource-graph (+ Bicep if `az bicep` exists) | `az extension update` |
| CLI (npm) | @pnp/cli-microsoft365 (+ @azure/*, @microsoft/*) | `npm install -g …@latest` (sudo in its own terminal if the npm folder is owned by root) |
| Puppa | the tool for PowerShell tasks in a few keystrokes | `uppa install puppa` runs Puppa's own install line; after that the menu has **Update Puppa** (runs the installer again) |
| Uppa itself | compares its version with GitHub | `uppa self-update` (part of `uppa update`): downloads, checks, swaps the file and keeps the old one as `uppa.py.bak`; in a git clone it runs `git pull` |
| .NET tools | global `dotnet tool`s | `dotnet tool update -g` |

The submodules of Az and Microsoft.Graph (141 of them) are read from the meta modules' manifests (`ModuleList` / `RequiredModules`) and come along when the meta module is updated. That is why a scan takes about 7 s instead of ~2 min.

## Meet Uppa

```text
  ██     ██    ╭────────────────────────────────────────────────╮
  ██ ◕ ◕ ██  ◂ │ Hi! 11 things can be updated. Shall we uppa them? │
  ██  ‿  ██    ╰────────────────────────────────────────────────╯
  ██▄   ▄██     uppa 1.2.0
   ▀█████▀
  Last checked 13 min ago
  ● Uppa  ● brew 2  ● PowerShell 8  ● az extensions  ● npm 1  ● .NET  ● Puppa

   ❯ 1  Update all              11 · 4 new major versions
     2  Pick yourself…          tick what to update
     …
     u  Sign out of everything  Graph · Az · PnP · az · m365
     s  Language: English
     q  Quit
```

Uppa is a fat U with its face in the bowl, built the same way as the rest of the troupe: a full-screen menu with arrow keys and digits, a status line with one dot per source, and "enter = back to the menu" after every action. Uppa blinks and looks around while the menu waits, talks while it scans, cheers with confetti when everything went well and looks sad when something fails (`uppa hello` for a joke). Animations are turned off with `--no-anim`, `UPPA_NO_ANIM=1`, `NO_COLOR` or when the output is piped.

## Scan and install bundles

```sh
uppa scan                 # CLI tools, all main modules (+N submodules) and how complete each bundle is
uppa scan -a              # the Az/Graph submodules too
uppa install              # checklist; b/m/z/l tick bas/m365/azure/alla
uppa install bas          # install what is missing from the base bundle
uppa install m365 azure   # several bundles
uppa install ImportExcel Some.Module   # single modules (unknown names are checked against PSGallery first)
```

| Bundle | Contents |
|---|---|
| **bas** | PowerShell 7, Azure CLI, Microsoft.Graph, ExchangeOnlineManagement, MicrosoftTeams, Az.Accounts, Az.Resources, ImportExcel, SecretManagement + SecretStore, PSScriptAnalyzer |
| **m365** | bas + Graph Beta, Microsoft.Entra, PnP.PowerShell, the Power Platform modules, PartnerCenter, CLI for Microsoft 365, Puppa |
| **azure** | bas + Az (all of it), Az.ResourceGraph, az resource-graph, Bicep, AzCopy, azd |
| **alla** | the whole catalogue |

Your own bundles: add them to `~/.uppa/config.json`, e.g. `{"profiles": {"customer": ["Microsoft.Graph", "ExchangeOnlineManagement"]}}`. Modules are installed with `Install-Module -Scope CurrentUser`.

## Commands

```sh
uppa                      # menu
uppa status [-a] [source|name] [--refresh]
uppa update [source|name] [-n] [-y] [-j N] [--changes]
uppa select               # checklist: space, a/n, s = the whole source, enter
uppa changes [name]       # GitHub release notes between your version and the latest
uppa doctor               # does pwsh start? az/m365 signed in? npm sudo, PATH duplicates, old module versions
uppa clean pwsh           # remove old module versions that Update-Module leaves behind
uppa ignore pwsh:Az       # skip something (unignore to undo)
uppa nudge enable         # one line a day in new terminals when something is outdated
uppa schedule enable [--daily] [--at 07:30]   # launchd / Task Scheduler / cron; skips sudo/UAC and reports
uppa self-update          # fetch the latest Uppa  (in the menu: Update Uppa, restarts in the new version)
uppa logout [-n]          # sign out everywhere: clears saved sign-ins for az, azd, m365, Az, Graph/Entra, PnP
uppa logout --ps | iex    # in an open pwsh window: also disconnects EXO, Teams, PnP, Graph, Az, Partner Center, Power Apps
uppa lang [en|sv]         # language for the whole troupe
uppa hello                # a joke from Uppa
```

The nudge is added to zsh/bash and to the PowerShell profile (`$PROFILE`), so it shows whichever shell you open.

`-n` is a dry run, `-y` skips the question. At `Run? [Y/n/c]`, `c` shows the release notes first.

## Files

- `uppa.py` – everything in one file (standard library only, Python 3.8+)
- `install.sh` / `install.ps1` – the install lines; they also work locally from a clone
- `~/.uppa/` – the script, cache, state, `config.json` (`ignore`, `profiles`, `repos`, `local`), `logs/`

Adding a tool: a `Tool(...)` line in `CATALOG` (with a winget id for Windows), or extend `MS_FORMULA` / `MS_WINGET` / `MS_NPM`.

## License

MIT
