# Development and candidate checks

`sh scripts/run-dev.sh --system-check` reports dependencies read-only.
`sh scripts/run-dev.sh` previews the dashboard from repository source. External
apps stay closed unless a parent explicitly passes --launch-external.

`python3 -B scripts/check_public_snapshot.py --source` checks the public allowlist
inside the private development tree without selecting its extra records.
`python3 -B scripts/check_public_snapshot.py --snapshot` checks an exact candidate
and refuses extra files or Git metadata. Neither command initializes a repository
or changes file permissions. See the [alpha guide](../docs/alpha-guide.md).

`python3 -B scripts/accept_installer.py` performs the filesystem-sandboxed
installer lifecycle and regressions in temporary synthetic homes. It requires an
existing Bubblewrap, fails closed if isolation is unavailable, and never installs
into the real account. Apply installation/uninstall commands only in a separately
authorized acceptance environment. No system package provisioner is included.
