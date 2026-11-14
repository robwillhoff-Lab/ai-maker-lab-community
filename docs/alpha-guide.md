# v0.1.0-alpha guide

This is a source candidate for private review, not a published release. Package
version: `0.1.0a0`. Obtain an approved source directory and enter it before using
these commands. No GitHub repository, release, or tag is created by this guide.

## Prerequisites and preview

The supported development path uses system Python 3.10+, PyGObject and GTK 3,
a Linux graphical session, and a POSIX shell. The tested setup is Omarchy/
Hyprland, Python 3.14.8, GTK 3. Other combinations are unverified. Dependencies
must be provisioned separately by an adult using the distribution's instructions;
the app installer cannot supply GTK or service accounts. Do not run as root.

```sh
sh scripts/run-dev.sh --system-check
sh scripts/run-dev.sh
```

System-check does not open a display or execute application probes. It reports
OS/desktop, Python, GTK, optional launchers, and whether a legacy shared or
portable user-local installation is present. Runtime reports may show personal
paths; review them before sharing. Detection never copies private profiles.

Preview opens the six-pathway dashboard but keeps external apps closed. The
journal editor writes only its own workspace. Source preview data is under
`.dev-data/user-<OS uid>/` within the checkout. Use separate ordinary Linux
accounts and separate checkouts for learners. The app does not create accounts,
change existing permissions, configure autostart, or import another lab's data.

## Configure one optional activity at a time

Copy `config/dashboard.example.json` manually to ignored `config/local.json`.
For an AppImage selection, `config/dashboard.appimage.example.json` is a smaller
valid example. It must be edited to a program the parent already trusts.

```sh
sh scripts/run-dev.sh --config config/local.json
```

- Coach needs a parent-approved HTTPS ChatGPT GPT/project destination, eligible
  account access, and internet. No API key or account is shipped. Conversations
  are not synchronized with Code Lab; see the teaching workflow.
- Code Lab needs Codex on PATH and configured Foot or xterm. It opens a direct
  terminal in Code; it neither starts tmux nor establishes a Codex security policy.
- 3D Workshop needs a separately installed Bambu program. Detection checks command
  aliases, standard binary locations, current-user AppImages, a conservative
  desktop-entry subset, and installed Flatpak metadata. Missing or ambiguous
  launchers require parent selection; nothing is installed or chmodded.
- Minecraft opens a separately installed Prism Launcher. The learner/parent
  chooses their own licensed account, instance and matching Java. No instance,
  credentials, worlds, or profile is copied by the lab.
- Freedoom needs a separately installed native DOOM Retro executable and an
  absolute path to separately obtained, appropriately licensed WAD assets.
  The file extension is not proof of provenance. No original DOOM data is bundled.
- My Projects opens only its own Projects directory through xdg-open. Maker
  Journal is built into the dashboard and needs no external editor.

Example executable override:

```json
{
  "application_launchers": {
    "bambu": {"kind": "executable", "path": "~/Applications/BambuStudio.AppImage"}
  }
}
```

Example installed Flatpak override:

```json
{
  "application_launchers": {
    "bambu": {"kind": "flatpak", "app_id": "com.bambulab.BambuStudio", "scope": "user"}
  }
}
```

Executable overrides accept absolute or home-relative paths without shell syntax
or parent traversal. Unknown fields are rejected. Explicit invalid selections do
not fall back silently. Flatpak needs both its runtime and matching installed
metadata; named installations and arbitrary branches/arches are unsupported.
Freedoom overrides are native executables only. Complex desktop wrappers and
extra Exec flags are not automatically interpreted. Root/current-user ownership
and non-writable-by-others targets are checked; immutable unmapped-root files
in managed namespaces have a narrowly checked read-only exception. This is not
publisher or signature verification. Parents review applications before use.

To deliberately leave preview mode:

```sh
sh scripts/run-dev.sh --config config/local.json --launch-external
```

External apps use their own profiles, access, caches, and permissions. This is
not a sandbox and can write outside the lab. Do not treat the menu, Coach URL
validation, or a settings label as child access control. Review service eligibility,
AI-generated commands, game content/online access, and physical printer use
independently; see [safety](safety.md).

## Installation and verification in an authorized test account

This preparation does not authorize applying installation on the reference
machine. A parent can use a disposable account/VM for later acceptance:

```sh
sh scripts/run-dev.sh --install --dry-run
sh scripts/run-dev.sh --install
sh scripts/run-dev.sh --verify-install
```

The first command creates nothing. Check its `ready` value, missing dependencies,
collisions, destinations, and preserved paths. Install refuses root, an existing
installation directory, any destination collision, missing required dependencies,
symlink/foreign-owned destinations, or XDG paths outside the OS account home.
It never upgrades a live installation. Optional activity dependencies do not
block the preview dashboard.

The installer builds a standard Python zipapp from eight explicit project
modules, a bootstrap and the MIT notice. It copies no home directory and runs
no pip, dependency download, build hook, or package manager. A distinct
**AI Maker Lab (Portable)** menu entry invokes the exact Python interpreter with
isolation/bytecode options. An alternative default-path command is:

```sh
python3 -I -B "$HOME/.local/share/ai-maker-lab/installation/app.pyz"
python3 -I -B "$HOME/.local/share/ai-maker-lab/installation/app.pyz" --system-check
python3 -I -B "$HOME/.local/share/ai-maker-lab/installation/app.pyz" --verify-install
```

The archive defaults to preview. With no explicit --config it reads its own
optional XDG configuration if one exists, otherwise defaults. No configuration
file is created or migrated during installation. Python/GTK must remain available
at the recorded interpreter; pip/wheel installation has not been accepted.

| XDG location | Contents | Removal policy |
| --- | --- | --- |
| data home / ai-maker-lab/installation | app.pyz, LICENSE, install-manifest.json | Verified owned files only |
| data home / applications/ai-maker-lab-portable.desktop | Distinct menu entry | Verified owned file only |
| data home / ai-maker-lab/workspace | Code, Projects, Journal, Games | Always retained |
| config home / ai-maker-lab/dashboard.json | Optional private settings | Always retained |
| state home / ai-maker-lab | Reserved state | Always retained |

Defaults for data/config/state homes are `.local/share`, `.config`, and
`.local/state` inside the OS account home. Absolute XDG overrides within that
home are allowed. Shared/symlinked storage and configuration outside it are
unsupported. Installed data and source-preview data are intentionally separate.

## Uninstall and recovery boundaries

```sh
sh scripts/run-dev.sh --uninstall --dry-run
sh scripts/run-dev.sh --uninstall
```

The installed archive also accepts --uninstall and --dry-run, so retaining the
source checkout is not required. Verification/removal does not depend on a valid
learner configuration. All four owned files must match the fixed manifest and
hashes and must not be symlinked/hardlinked. Changed, missing or unfamiliar files
stop removal. There is no recursive deletion or force option. Unrelated files
leave their directory in place. Projects, journals, configuration and state are
not installer-owned files and are never part of uninstall. Keep separate backups;
uninstall does not restore a previous application version or remove user data.

On collision or tampering, stop and inspect the exact paths with the parent;
do not delete a workspace, remove the manifest to bypass checks, change account
permissions, or overwrite another app. A missing/invalid manifest requires manual
investigation. No migration or upgrade automation is provided in this alpha.

Journal saving writes a private temporary file in the destination directory,
flushes and fsyncs it, then atomically replaces the journal after conflict checks.
Failed writes or replacement preserve the previous file and keep GUI edits open.
An OS-denied cleanup can leave a private temporary file and produces a clear
error. The parent directory is not fsynced; sudden-power-loss durability, storage
corruption and malicious same-user races are not guaranteed. Keep backups.

## Reproduce automated acceptance

```sh
python3 -B -m unittest discover -s tests -v
python3 -B scripts/accept_installer.py
python3 -B scripts/check_public_snapshot.py --snapshot
```

The acceptance harness requires an already installed Bubblewrap and supported
mount/PID namespaces; it stops if isolation fails. It hides real home directories,
makes host/source/legacy mounts read-only, and allows host writes only in a
fresh temporary tree. It performs synthetic install/verify/non-GUI smoke/uninstall
checks and regressions there. It does not launch Codex, Bambu, Prism, games,
browsers or printers. Network namespaces were unavailable in the tested tool
environment; filesystem isolation is verified without claiming network isolation.

The exact snapshot must be checked before adding Git history or runtime data.
The alpha remains unverified for installed menu/GUI acceptance, real external
app startup, other platforms/versions, upgrades, signatures, concurrent use,
and persistent Code Lab sessions. These limitations are intentional disclosures,
not features completed by an availability check.
