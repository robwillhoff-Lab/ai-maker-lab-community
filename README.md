# AI Maker Lab — v0.1.0-alpha candidate

AI Maker Lab is an **early Linux alpha**: a parent-supervised GTK dashboard for
creative learning. The Python package version is `0.1.0a0`; the human release
name is **v0.1.0-alpha**.

The AI Maker Lab Community repository is hosted at:
https://github.com/robwillhoff-Lab/ai-maker-lab-community

The repository is currently in private pre-release staging. Public availability
is not yet announced.

Learners can plan small games and scripts, explore 3D design, keep a maker
journal, and use separately installed creative tools. The learning loop is
**Imagine → Predict → Build → Test → Explain**. Adults choose appropriate
activities, administer accounts, review AI output, and supervise physical making.

## What the alpha provides

| Pathway | Current behavior |
| --- | --- |
| Maker Coach | Opens a parent-configured ChatGPT GPT/project destination when external launches are enabled |
| Code Lab | Opens Codex CLI in Foot or xterm, in the learner's own Code directory; no tmux persistence |
| 3D Workshop | Detects a separately installed Bambu Studio executable, AppImage, supported desktop entry, or Flatpak |
| Gaming Lab | Offers separately installed Prism Launcher for Minecraft and DOOM Retro with parent-selected Freedoom assets |
| My Projects | Opens the learner's own Projects directory |
| Maker Journal | Built-in UTF-8 editor with temporary-file write, flush/fsync, atomic replacement, and failed-save feedback |

Coach and Codex do not automatically share conversations or memory. Learners
manually copy a small plan to Codex and bring a tested result back to Coach.
See the [teaching workflow](docs/teaching-workflow.md).

## Requirements and tested scope

Required for the dashboard: **Linux, Python 3.10+, PyGObject, and GTK 3**. A POSIX
shell runs the source launcher. These prerequisites must already be available;
this project does not install system packages. On the tested Omarchy system the
relevant package names are `python`, `python-gobject`, and `gtk3`; use your own
distribution's instructions to provision them. No pip install is needed for the
supported source/zipapp workflow.

Only **Omarchy/Hyprland with Python 3.14.8 and GTK 3** has been exercised here.
Other Linux distributions, desktops, older supported Python versions, and other
hardware configurations remain unverified. macOS and Windows are not supported.
No minimum CPU, RAM, GPU, or disk budget is established.

Optional activities need their own applications and access: Codex CLI plus Foot
or xterm, `xdg-open`, Bambu Studio, Prism Launcher with suitable Java and licensed
Minecraft access, or DOOM Retro and separately obtained Freedoom assets. AI access
requires internet and eligible service accounts. None of these accounts, programs,
assets, printer profiles, or credentials is bundled. Bubblewrap is needed only
for the isolated acceptance harness, not normal dashboard use.

## First source preview

Obtain the owner-approved source candidate directory or, after publication is
separately authorized, the approved release archive. Enter that directory; do
not use a private backup or a copy of the original `.git` history as a public
release. Then run:

```sh
sh scripts/run-dev.sh --system-check
sh scripts/run-dev.sh
```

The default is **preview mode**. External applications stay closed. A missing
optional application produces a parent setup message; it does not prevent the
other pathways or the journal from being available. Availability does not mean
an app, login, game, or printer operation has been tested successfully.

Source preview creates only `.dev-data/user-<OS uid>/` inside this checkout for
Code, Projects, Journal, and Games. Each ordinary learner account uses its own
checkout. It does not read or migrate an existing lab's projects or settings.

## Private configuration and optional applications

Copy `config/dashboard.example.json` yourself to ignored `config/local.json`,
edit it locally, and explicitly select it:

```sh
sh scripts/run-dev.sh --config config/local.json
```

Leave optional values null until a parent configures them. Coach accepts only
an HTTPS ChatGPT GPT/project destination. Commands are executable names on PATH;
structured overrides support reviewed absolute or `~/` executable/AppImage paths
and installed Flatpak IDs. The AppImage example is generic, not an installed
path. Do not commit local configuration. See [configuration examples](config/README.md)
and the [alpha guide](docs/alpha-guide.md).

Only after reviewing the chosen applications and local settings, a parent can
explicitly enable external launching:

```sh
sh scripts/run-dev.sh --config config/local.json --launch-external
```

That mode is **not sandboxed**. External programs can access their normal profiles
and write outside the workspace. The dashboard does not provision Codex
permissions, filter the web, establish child eligibility for services, or manage
printer safety. See [parent safety boundaries](docs/safety.md).

## User-local installation foundation

First inspect the no-write plan:

```sh
sh scripts/run-dev.sh --install --dry-run
```

Review `ready`, collisions, dependencies, destinations, and preserved-data fields.
A successful report command is not a guarantee of compatibility. For a future
explicitly authorized disposable-account or VM acceptance test, the apply and
verification commands are:

```sh
sh scripts/run-dev.sh --install
sh scripts/run-dev.sh --verify-install
```

Do not run apply commands on a protected reference installation during this
preparation. The offline zipapp installer needs no sudo, pip, build hooks, network
access, or system-package changes. It refuses existing destinations and missing
required dependencies; it does not upgrade or adopt an existing installation.
The distinct portable menu entry opens the same preview-first dashboard.

Program files default to `$HOME/.local/share/ai-maker-lab/installation`, projects
and journals to its sibling `workspace`, and optional private configuration to
`$HOME/.config/ai-maker-lab/dashboard.json`. XDG overrides are supported only
inside the current OS account's home. The [alpha guide](docs/alpha-guide.md)
explains exact paths, installed commands, verification, and data preservation.

Preview uninstall before an authorized removal:

```sh
sh scripts/run-dev.sh --uninstall --dry-run
sh scripts/run-dev.sh --uninstall
```

Uninstall removes only verified installer-owned files. **Projects, journals,
configuration, state, and unrelated files remain.** Back them up separately.
Modified/missing installation files stop verification or removal; there is no
force-delete workaround. Normal pip/wheel installation is not an accepted path.

## Tests and release checks

```sh
python3 -B -m unittest discover -s tests -v
python3 -B scripts/accept_installer.py
python3 -B scripts/check_public_snapshot.py
```

The last command verifies a normal Git checkout and permits its `.git` directory.
For an exported source snapshot without `.git`, enter the exported directory and
run:

```sh
python3 -B scripts/check_public_snapshot.py --snapshot .
```

Snapshot mode requires exactly the [public file inventory](release/public-files.txt)
and rejects Git metadata and extra files. Source maintainers use `--source` when
checking selected files inside a private development tree with additional records.
Acceptance runs in a
temporary filesystem sandbox, not the real account; it stops if isolation cannot
be established. No external application is launched by these tests.

## Known limitations and license

This is not an operating-system installer, a complete family deployment tool, a
child-safety sandbox, or a generally supported Linux package. Installed menu/GUI
behavior and real Bambu/AppImage/Flatpak startup need further acceptance.
Persistent Code Lab sessions, upgrades, release signatures, concurrent operation,
and broad compatibility remain future work. Journal saves preserve the prior file
on pre-replacement failure; parent-directory power-loss durability and malicious
same-user filesystem races are not guaranteed.

Original project components are under the [MIT License](LICENSE).
Copyright (c) 2026 robwillhoff-Lab. External applications retain their own terms;
see [dependency and provenance notices](docs/third-party-notices.md).
