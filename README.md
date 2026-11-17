# uppa

<p align="center">
  <img src="assets/uppa.svg" alt="Uppa: Hej! Jag är Uppa." width="720">
</p>

Håller dina **PowerShell- och Microsoft-CLI-verktyg** uppdaterade på **Windows, macOS och Linux**: ett kommando, en checklista, parallella uppdateringar, och grundpaket som installerar allt en M365/Azure-admin behöver. Inspirerat av [azup](https://github.com/saeid-adz/azup).

## Installera

**Windows** (PowerShell; installerar Python per användare om det saknas)

```powershell
irm https://raw.githubusercontent.com/pipebreak33/uppa/main/install.ps1 | iex
```

**macOS / Linux**

```sh
curl -fsSL https://raw.githubusercontent.com/pipebreak33/uppa/main/install.sh | sh
```

Öppna en ny terminal och kör `uppa`. Vill du ha allt på en gång: `uppa install bas` (eller `m365` / `azure`). Uppdatera uppa själv med `uppa self-update`. Lås en version med `UPPA_BRANCH=v1.0.0` (PowerShell: `$env:UPPA_BRANCH = 'v1.0.0'`) före installationsraden.

## Vad uppa sköter

| Källa | Vad | Hur |
|---|---|---|
| CLI (Homebrew, macOS/Linux) | powershell, azure-cli, dotnet (+ azd, azcopy, sqlcmd … om de installeras) | `brew upgrade --formula` i ett anrop |
| CLI (winget, Windows) | Microsoft.PowerShell, Microsoft.AzureCLI, Microsoft.DotNet.SDK.*, Microsoft.Azure.* | `winget upgrade --id … --silent` (PowerShell i egen terminal p.g.a. UAC) |
| PowerShell-moduler | Az, Microsoft.Graph, ExchangeOnlineManagement, MicrosoftTeams, PnP.PowerShell, PowerApps, PartnerCenter, SqlServer, ImportExcel … | `Update-Module`, tre parallella spår (Az · Graph/Entra · övriga) |
| az-tillägg | resource-graph (+ Bicep om `az bicep` finns) | `az extension update` |
| CLI (npm) | @pnp/cli-microsoft365 (+ @azure/*, @microsoft/*) | `npm install -g …@latest` (sudo i egen terminal om npm-mappen ägs av root) |
| Puppa | syskonverktyget för PowerShell-uppgifter med några knapptryck | `uppa install puppa` kör Puppas egen installationsrad; därefter finns **Uppdatera Puppa** i menyn (kör installern igen) |
| uppa självt | jämför sin version med GitHub | `uppa self-update` (ingår i `uppa update`): laddar ner, kontrollerar, byter fil och sparar den gamla som `uppa.py.bak`; i en git-klon körs `git pull` |
| .NET-verktyg | globala `dotnet tool`s | `dotnet tool update -g` |

Undermodulerna till Az och Microsoft.Graph (141 st) läses ur meta-modulernas manifest (`ModuleList` / `RequiredModules`) och följer med när meta-modulen uppdateras. Därför tar en skanning ungefär 7 s i stället för ~2 min.

## Möt Uppa

```text
  ██     ██    ╭──────────────────────────────────────────────╮
  ██ ◕ ◕ ██  ◂ │ Hej! 11 saker kan uppdateras. Ska vi uppa dem? │
  ██  ‿  ██    ╰──────────────────────────────────────────────╯
  ██▄   ▄██     uppa 1.1.0
   ▀█████▀
  Senast kollat 13 min sedan
  ● uppa  ● brew 2  ● PowerShell 8  ● az-tillägg  ● npm 1  ● .NET  ● Puppa

   ❯ 1  Uppdatera allt          11 st · 4 nya huvudversioner
     2  Välj själv…             kryssa i det som ska uppdateras
     …
     u  Logga ut från allt      Graph · Az · PnP · az · m365
     q  Avsluta
```

Uppa är ett tjockt U med ansiktet i skålen – storebror till [Puppa](https://github.com/pipebreak33/puppa)s P, byggd på samma sätt: helskärmsmeny med piltangenter och siffror, en statusrad med en prick per källa, och "enter = tillbaka till menyn" efter varje åtgärd. Uppa blinkar och tittar runt medan menyn väntar, pratar medan den skannar, jublar med konfetti när allt gått bra och ser ledsen ut när något failar (`uppa hej` för ett skämt). Animationer stängs av med `--no-anim`, `UPPA_NO_ANIM=1`, `NO_COLOR` eller när utdata pipas.

## Syskonet Puppa

<p align="center">
  <a href="https://github.com/pipebreak33/puppa"><img src="https://raw.githubusercontent.com/pipebreak33/puppa/main/assets/puppa.svg" alt="Puppa: Hej! Jag är Puppa." width="640"></a>
</p>

Uppa har en lillasyster: **[Puppa](https://github.com/pipebreak33/puppa)**, det blå P:et. Där Uppa ser till att verktygen är installerade och uppdaterade, är det Puppa som *använder* dem: vanliga M365-adminuppgifter i PowerShell med några knapptryck i stället för att skriva cmdlets.

- **Kundprofiler:** PnP-appregistrering för SharePoint och sparade tenants, så att du byter kund med ett knapptryck.
- **Färdiga recept** för SharePoint, OneDrive, Exchange, grupper, användare och Teams, med export till Excel. Varje recept visar exakt vilket kommando som körs och frågar innan något ändras.
- **Samma utseende som Uppa:** helskärmsmeny, statusrad, Windows, macOS och Linux.

Installera Puppa direkt från uppa:

```sh
uppa install puppa       # eller välj "Installera Puppa" i menyn
```

Därefter finns **Uppdatera Puppa** i uppas meny, och statusraden visar om det finns en ny Puppa. Puppa ingår också i grundpaketet `m365`.

## Skanna och installera grundpaket

```sh
uppa scan                 # CLI-verktyg, alla huvudmoduler (+N undermoduler) och hur komplett varje paket är
uppa scan -a              # även Az-/Graph-undermodulerna
uppa install              # checklista; b/m/z/l kryssar i bas/m365/azure/alla
uppa install bas          # installera det som saknas i grundpaketet
uppa install m365 azure   # flera paket
uppa install ImportExcel Some.Module   # enskilda moduler (okända namn kontrolleras mot PSGallery först)
```

| Paket | Innehåll |
|---|---|
| **bas** | PowerShell 7, Azure CLI, Microsoft.Graph, ExchangeOnlineManagement, MicrosoftTeams, Az.Accounts, Az.Resources, ImportExcel, SecretManagement + SecretStore, PSScriptAnalyzer |
| **m365** | bas + Graph Beta, Microsoft.Entra, PnP.PowerShell, Power Platform-modulerna, PartnerCenter, CLI for Microsoft 365, Puppa |
| **azure** | bas + Az (hela), Az.ResourceGraph, az resource-graph, Bicep, AzCopy, azd |
| **alla** | hela katalogen |

Egna paket: lägg till i `~/.uppa/config.json`, t.ex. `{"profiles": {"kund": ["Microsoft.Graph", "ExchangeOnlineManagement"]}}`. Moduler installeras med `Install-Module -Scope CurrentUser`.

## Kommandon

```sh
uppa                      # meny
uppa status [-a] [källa|namn] [--refresh]
uppa update [källa|namn] [-n] [-y] [-j N] [--changes]
uppa select               # checklista: space, a/n, s = hela källan, enter
uppa changes [namn]       # GitHub-release notes mellan din version och senaste
uppa doctor               # pwsh startar? az/m365 inloggade? npm-sudo, PATH-dubbletter, gamla modulversioner
uppa clean pwsh           # ta bort gamla modulversioner som Update-Module lämnar kvar
uppa ignore pwsh:Az       # hoppa över något (unignore för att ångra)
uppa nudge enable         # en rad om dagen i nya terminaler när något är inaktuellt
uppa schedule enable [--daily] [--at 07:30]   # launchd / Task Scheduler / cron; hoppar över sudo/UAC och rapporterar
uppa self-update          # hämta senaste uppa  (i menyn: Uppdatera uppa – startar om i nya versionen)
uppa logout [-n]          # logga ut överallt: rensar sparade inloggningar för az, azd, m365, Az, Graph/Entra, PnP
uppa logout --ps | iex    # i ett öppet pwsh-fönster: kopplar även ner EXO, Teams, PnP, Graph, Az, Partner Center, Power Apps
uppa hej                  # ett skämt från Uppa
```

Påminnelsen läggs i zsh/bash och i PowerShell-profilen (`$PROFILE`), så den syns oavsett vilket skal du öppnar.

`-n` är torrkörning, `-y` hoppar över frågan. Vid `Kör? [J/n/c]` visar `c` release notes först.

## Filer

- `uppa.py` – allt i en fil (bara standardbiblioteket, Python 3.8+)
- `install.sh` / `install.ps1` – installationsraderna; fungerar även lokalt från en klon
- `~/.uppa/` – skriptet, cache, state, `config.json` (`ignore`, `profiles`, `repos`, `local`), `logs/`

Lägga till ett verktyg: en `Tool(...)`-rad i `CATALOG` (med winget-id för Windows), eller utöka `MS_FORMULA` / `MS_WINGET` / `MS_NPM`.

## Licens

MIT
