# Zhia Lian Quest Browser

A small Python web app for Project Gorgon's Zhia Lian Halloween event. It reads the
official game data from the Project Gorgon CDN and shows:

- **Questlines** (the first tab): an interactive map of how the quests chain together.
  Click a quest's seal to mark it done; the map shows what that unlocks.
- **By NPC**: every quest grouped by who gives it (Zhia Lian, Brandon Mellus, the Bat in
  the Hat, the cursed cultists and so on), plus the quests each NPC appears in.
- **By region**: quests grouped by overworld region, with the specific spot where the
  data names one (Serbule Crypt, Borghild, the ruined Kur Tower, Gazluk Keep...).
- **Rewards & items**: titles, event hats and masks, abilities, recipes, Zhia's
  blessings, candy, keys, a table of every quest reward, and the recipes the quests
  ask you to craft.

Progress is saved in your browser (localStorage), so it survives reloads and new data
versions. The menu next to the search box can copy your progress to another browser
or reset it for next year's event.

## Import your player file

Click **Import player file** (or drop the file anywhere on the page) and choose the
`Character_<name>_<server>.json` file the game saved. The app shows what it found before
changing anything:

- **Zhia Lian favour** appears in large type in the header, with your favour level,
  from `NPCs` → `NPC_ZhiaLian` → `Favor` in the file. Until you import a file the header
  says "Import a player file to see your Zhia Lian favour".
- Event quests in your `ActiveQuests` list show as **In journal**.
- The file doesn't list finished event quests, because they repeat every year, so the
  app works them out from the quest chain in two ways:
  1. **From what had to come before.** If a quest is in your journal, everything it needs
     was reached; anything reached that isn't in your journal any more is finished. When
     either of two quests could have unlocked one, only what both have in common counts.
  2. **From Zhia's follow-ups** (you can switch this off in the dialog). Zhia hands out
     follow-up quests by herself the moment you finish one, and they can't be abandoned,
     so a follow-up of a finished quest that isn't in your journal is finished too.
- Your other ticks stay unless you choose **Clear my other ticks first**. Quests that are
  back in your journal lose their tick, since they're in progress again.

With the example file (Lacrimosa on Dreva), that's 17 quests in the journal and 24
finished: 21 from the first method and 3 more from the second.

## Watch your player file for updates

The game can write a fresh player file every time you log out. Turn this on in game:
"Automatically export on logout" checkbox should be ticked (Settings -> VIP).

The first time you import a file, the dialog asks whether to **watch it for updates**.
When watching:

- The header says **Watching Character_Lacrimosa_Dreva.json** and when it last checked.
- The app checks the file every 15 seconds. When the game saves it again, every open page
  updates its ticks and favour by itself and says what changed, the same way the first
  import worked (including your follow-ups choice).
- **Force recheck** reads the file straight away.
- The checkbox in the header turns watching off and on again. The app remembers what it
  watches, even after you close and restart it.
- Other devices on your network pick up the same updates, even ones that never imported
  a file.

How the app finds the file: your browser can't tell it where an uploaded file came from,
so the app looks for a file with the same name in Project Gorgon's Reports folder on the
computer it runs on:

- Windows: `%USERPROFILE%\AppData\LocalLow\Elder Game\Project Gorgon\Reports`, then
  `Documents\Project Gorgon Data\Reports`
- Linux: `~/.config/unity3d/Elder Game/Project Gorgon/Reports`
- macOS: `~/Library/Application Support/Elder Game/Project Gorgon/Reports`

If it isn't there, the dialog lets you paste where the file is. For safety, that only
works from the computer running the app (http://localhost/), and the app only ever reads
files that are Project Gorgon player files. `ZHIA_REPORTS_DIR` adds another folder to look in.

## Run it

**As a Windows app:** double-click `ZhiaLianQuestBrowser.exe`. A small window opens
showing the addresses, and your browser opens the app. Close that window to quit.
Nothing needs installing.

**From source** (any OS, Python 3.10 or newer):

```bash
pip install -r requirements.txt
python app.py
```

By default the app listens on **0.0.0.0, port 80**, so other devices on your network can
open it too (the window lists the addresses), and your browser opens http://localhost/.
If you start it a second time, it just reopens the page.

| Option | What it does |
| --- | --- |
| `--port:N` | Use port N instead of 80, for example `--port:8080`. `--port N` and `--port=N` work too. |
| `--localhostonly` | Only accept connections from this computer (listen on 127.0.0.1). |
| `--no-browser` | Don't open a browser on start. |
| `--help` | Show these options. |

For example: `ZhiaLianQuestBrowser.exe --port:8080 --localhostonly`. To always start it
that way, make a Windows shortcut to the EXE and add the options to its *Target* box.

Good to know:
- **Port 80 in use.** If another program already uses port 80 (IIS, another web server,
  some chat apps), the window says so; start it with `--port:8080` instead.
- **Windows Firewall** asks once whether to allow the app on your network when it
  listens on 0.0.0.0. Allow it on private networks if you want to use it from your
  phone or another PC; with `--localhostonly` it never asks.
- **Each address keeps its own ticks.** Browsers store your ticks per address, so
  `http://localhost/` and `http://192.168.1.20/` (or another port) each start empty.
  Import your player file on each device (or watch it), or use *Copy my progress* and
  *Paste progress* in the menu.

## Game data

- **First run:** the app downloads all 13 game data files it uses (about 5 MB) into its
  data folder, showing progress in the page.
- **Updates:** it looks for a new data version every 30 minutes, and you can check now
  with **Check for game data updates** in the menu. A new version downloads, the page
  switches to it, and the two newest versions are kept (about 50 MB each).
- **Download all game data again** fetches every file afresh, in case the saved copy
  is damaged. The old files stay in use until the new ones have all arrived.
- **Offline:** it uses the newest saved copy, or the snapshot built into the EXE, so it
  works even with no internet on the very first run.

The data folder is `%LOCALAPPDATA%\ZhiaLianQuestBrowser` for the EXE, and the project
folder when running from source. Game icons are cached there as you view them, and
`settings.json` there remembers which player file is watched.

Environment variables, all optional: `ZHIA_DATA_DIR` (data folder), `ZHIA_CHECK_MINUTES`
(how often to look for new data, default 30), and `PORT`, `HOST` and `ZHIA_NO_BROWSER=1`,
which the command-line options override.

## Build the EXE yourself

On Windows, with Python 3.10 to 3.13 from python.org installed:

1. Double-click `build_exe.bat`. It makes a private virtual environment, installs Flask
   and PyInstaller into it, and runs `build.py`.
2. Collect `dist\ZhiaLianQuestBrowser.exe` (about 15 MB). That one file is the whole app.

`build.py` first snapshots the current game data and the icons the app uses (about
700 KB) into `snapshot\`, then has PyInstaller bundle Python, the code, the page, the
fonts and the snapshot into one EXE. Options:

- `build_exe.bat --onedir` builds a folder instead of a single file. It starts faster,
  because a single-file EXE unpacks itself to a temporary folder on every launch.
- `build_exe.bat --no-snapshot` leaves the game data out; the EXE then needs internet
  the first time it runs.

Rebuild after Project Gorgon updates if you want the built-in copy to stay current;
the app downloads newer data by itself either way.

**Antivirus and SmartScreen.** Windows may warn about an unsigned EXE from the
internet ("Windows protected your PC": choose *More info*, then *Run anyway*). Some
antivirus tools also flag PyInstaller apps by mistake. Building it yourself with
`build_exe.bat` avoids the download warning.

## How it works

| File | Job |
| --- | --- |
| `gorgon.py` | Reads the data version, downloads and caches the 13 JSON files it needs, rejects the CDN's "missing file" HTML pages. |
| `zhia.py` | Builds the event model: finds the event quests, works out givers, regions, links between quests, rewards, titles and event items. |
| `curated.py` | The few facts the data doesn't encode, taken from the wiki: Brandon's "offered once assigned" links, where he stands for the beer quests, short NPC notes, and the place names used to find regions. |
| `app.py` | Flask app and launcher. Serves the page, `/api/event` (gzip, ETag from a hash of the content), `/api/refresh`, `/api/status`, `/api/player…` and `/icon/N.png`; picks live, cached or snapshot data; reads the command-line options; opens the browser. |
| `player.py` | Finds and watches the player file: looks in the Reports folders, checks it every 15 seconds, keeps a small summary (favour, export time, quest names). |
| `static/`, `templates/` | The front end, plain JavaScript with no build step. Fonts are bundled in `static/fonts` (SIL Open Font License). |
| `build.py`, `build_exe.bat`, `packaging/` | The Windows EXE build: data snapshot, PyInstaller settings, app icon. |

**Which quests count.** Every quest whose internal name starts with `Event_Halloween`
or that is tied to the `HalloweenQuests` rule (110 in v487), plus the three
title-collection books whose objectives are event titles.

**Givers.** From the quest's `FavorNpc`. Most of Zhia's quests have none, because she
talks into your head; those are detected from the speaker in the quest text.

**Regions.** Matched from place names in the quest name and objectives, then the quest
text, then the location of named event monsters, plus the giver's area. Quests with
no place at all are listed under *Anywhere*. This is inferred, so treat it as a strong
hint rather than gospel.

**Quest links.** Four kinds, drawn differently on the map:
- *Finishing unlocks* (`FollowUpQuests`): any one parent unlocks the quest.
- *Needs every link finished* (`QuestCompleted` requirements): all are needed.
- *Offered once assigned* (from the wiki): Brandon offers these while the parent
  quest is in your journal.
- *Counts toward* (interaction flags): finishing one quest ticks off another, such
  as *The Elven Medicine* completing *Help Westley the Elf*.

A quest shows as **Available** when it's unlocked by those rules, and **Locked**
otherwise. The Whimsical Challenges always show as available, but in game they only
appear while Zhia runs a server-wide challenge.

## Known gaps

- Monster loot is rarely recorded in the data, so candy and some masks show no source.
- The data doesn't say which Whimsical Challenge gives which of Zhia's four blessings.
- When a new year's event changes quests, everything updates automatically except the
  wiki links in `curated.py`; unknown names there are simply ignored.

Some portions copyright 2026 Elder Game, LLC. Game data from the official Project
Gorgon CDN; extra notes from the [Project Gorgon wiki](https://wiki.projectgorgon.com/wiki/Halloween_2024).
