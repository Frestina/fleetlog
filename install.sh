#!/usr/bin/env bash
# Links bin/git-fleetlog into ~/.local/bin. Safe to run again.
set -euo pipefail

src="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/bin/git-fleetlog"
dir="$HOME/.local/bin"
dest="$dir/git-fleetlog"

old=""
if [[ -L $dest ]]; then
  old="$(readlink "$dest")"
  if [[ $old == "$src" ]]; then
    echo "$dest already links to $src"
    exit 0
  fi
elif [[ -e $dest ]]; then
  echo "install.sh: $dest exists and is not a link, leaving it alone" >&2
  exit 1
fi

mkdir -p "$dir"
ln -sfn "$src" "$dest"
if [[ -n $old ]]; then
  echo "replaced link to $old"
fi
echo "linked $dest -> $src"

case ":$PATH:" in
  *":$dir:"*) ;;
  *) echo "note: $dir is not on your PATH" ;;
esac
