#!/usr/bin/env bash
# Links bin/fleetlog into ~/.local/bin as fleetlog and git-fleetlog, so
# `git fleetlog` works too. Safe to run again.
set -euo pipefail

src="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/bin/fleetlog"
dir="$HOME/.local/bin"

status=0
for name in fleetlog git-fleetlog; do
  dest="$dir/$name"
  old=""
  if [[ -L $dest ]]; then
    old="$(readlink "$dest")"
    if [[ $old == "$src" ]]; then
      echo "$dest already links to $src"
      continue
    fi
  elif [[ -e $dest ]]; then
    echo "install.sh: $dest exists and is not a link, leaving it alone" >&2
    status=1
    continue
  fi

  mkdir -p "$dir"
  ln -sfn "$src" "$dest"
  if [[ -n $old ]]; then
    echo "replaced link to $old"
  fi
  echo "linked $dest -> $src"
done

case ":$PATH:" in
  *":$dir:"*) ;;
  *) echo "note: $dir is not on your PATH" ;;
esac
exit "$status"
