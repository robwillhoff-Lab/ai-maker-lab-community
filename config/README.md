# Private configuration from generic examples

`dashboard.example.json` is the current portable schema. All fields are optional;
omitted fields use defaults. `dashboard.appimage.example.json` is a smaller valid
home-relative executable choice, not a known installed path. Copy either example
yourself to ignored `config/local.json`, edit it, and pass --config explicitly.
The application never writes that configuration file.

Command fields are executable names on PATH. `application_launchers` optionally
selects reviewed absolute or `~/` executable/AppImage paths or installed Flatpak
IDs for Bambu/Prism. Freedoom supports native executables only. Paths are single
argv elements, not shell commands. Unknown fields and invalid explicit choices
produce errors rather than silent fallback. Private service destinations and
local paths should never be committed or copied into shared examples.

See the [alpha guide](../docs/alpha-guide.md) for fields, Flatpak scopes, preview
and installed behavior, missing dependencies, and safe installation boundaries.
