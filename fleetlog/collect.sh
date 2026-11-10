# Runs on every machine, local or over ssh, fed on stdin to
#
#   nice -n 19 bash -s -- <since> <until> <folder>...
#
# with since and until as unix times. It finds the git repos under the
# folders and prints what fleetlog needs about each, one record a line,
# fields split by the unit separator (0x1f). The first field says what the
# record is:
#
#   M  hostname, time now, HOME          once, first
#   N  folder                            a folder that is not on this machine
#   R  path, root, user.email, synced, remotes, common dir
#                                        a repo; the records below belong to it.
#                                        Worktrees share a common dir, and with
#                                        it their branches and stashes
#   H  branch                            what HEAD is on, empty when detached
#   B  branch, upstream, track, unpushed, upstream's tip, its commit time,
#      its branch on the remote, the remote
#                                        one per local branch. The remote is
#                                        the last two names of its URL
#   U  hash, parents                     the last 200 commits of an upstream,
#                                        after the first branch that tracks it:
#                                        what this clone has fetched, so the
#                                        recap can tell what another has not
#   C  hash, author email, time, subject a commit in the window
#   L  hash, reflog subject              HEAD's reflog, to see where a commit
#                                        was made
#   D  changed, untracked                uncommitted files
#   S  stashes
#   X  path, reason                      a repo that could not be read
#   E                                    once, last: nothing was cut off
#
# It only reads. Nothing fetches, and GIT_OPTIONAL_LOCKS=0 keeps git status
# from writing the index.

set -u
export GIT_OPTIONAL_LOCKS=0 GIT_TERMINAL_PROMPT=0 GIT_PAGER=cat LC_ALL=C
if command -v ionice >/dev/null; then
  ionice -c 3 -p $$ >/dev/null 2>&1
fi

US=$'\x1f'
DEPTH=200 # commits of an upstream's history sent
# As dates, since git reads a small @<unix time> as something else.
since=$(date -u -d "@$1" '+%Y-%m-%d %H:%M:%S +0000')
until=$(date -u -d "@$2" '+%Y-%m-%d %H:%M:%S +0000')
shift 2

rec() {
  local IFS=$US
  printf '%s\n' "$*"
}

# The newest of FETCH_HEAD and the remote-tracking reflogs, which a fetch, a
# pull and a push all touch: when this clone last heard from its remotes.
synced() {
  find "$1/FETCH_HEAD" "$1/logs/refs/remotes" -type f -printf '%T@\n' 2>/dev/null |
    sort -n | tail -n 1 | cut -d . -f 1
}

# The last two names of a remote's URL, owner/repo on a forge: the same on
# every machine whatever scheme or ssh alias each uses, and without the host,
# user or token a URL may hold.
remote_key() {
  local url=${1%/} name
  url=${url%.git}
  url=${url%/}
  [[ -n $url ]] || return
  name=${url##*[/:]}
  url=${url%"$name"}
  url=${url%[/:]}
  printf '%s\n' "${url##*[/:@]}/$name"
}

repo() {
  local path=$1 root email common remotes branch up track n line
  local upref remote uptip uptime there key seen=" "
  local g=(git -C "$path" -c core.fsmonitor=false)

  if ! common=$("${g[@]}" rev-parse --path-format=absolute --git-common-dir 2>&1); then
    rec X "$path" "${common##*$'\n'}"
    return
  fi
  root=$("${g[@]}" rev-list --max-parents=0 HEAD 2>/dev/null | sort | head -n 1)
  email=$("${g[@]}" config user.email 2>/dev/null)
  remotes=$("${g[@]}" remote 2>/dev/null | wc -l)
  rec R "$path" "$root" "$email" "$(synced "$common")" "$remotes" "$common"
  rec H "$("${g[@]}" symbolic-ref -q --short HEAD 2>/dev/null)"

  while IFS=$US read -r branch up track upref; do
    n=$("${g[@]}" rev-list --count "refs/heads/$branch" --not --remotes 2>/dev/null)
    remote='' uptip='' uptime='' there='' key=''
    if [[ $upref == refs/remotes/* ]]; then
      remote=$("${g[@]}" config --get "branch.$branch.remote" 2>/dev/null)
      read -r uptip uptime < <("${g[@]}" log -1 --format='%H %ct' "$upref" -- 2>/dev/null)
      if [[ -n $remote && $upref == "refs/remotes/$remote/"* ]]; then
        there=${upref#"refs/remotes/$remote/"}
        key=$(remote_key "$("${g[@]}" config --get "remote.$remote.url" 2>/dev/null)")
      fi
    fi
    rec B "$branch" "$up" "$track" "$n" "$uptip" "$uptime" "$there" "$key"
    if [[ -n $uptip && $seen != *" $uptip "* ]]; then
      seen+="$uptip "
      "${g[@]}" log -n "$DEPTH" --format="U%x1f%H%x1f%P" "$uptip" -- 2>/dev/null
    fi
  done < <("${g[@]}" for-each-ref refs/heads \
    --format="%(refname:short)%1f%(upstream:short)%1f%(upstream:track,nobracket)%1f%(upstream)" \
    2>/dev/null)

  "${g[@]}" log HEAD --branches --remotes --tags --no-merges \
    --since="$since" --until="$until" \
    --format="C%x1f%H%x1f%ae%x1f%ct%x1f%s" 2>/dev/null
  "${g[@]}" log -g HEAD -n 500 --format="L%x1f%H%x1f%gs" 2>/dev/null

  local changed=0 untracked=0
  while IFS= read -r line; do
    if [[ $line == '??'* ]]; then
      untracked=$((untracked + 1))
    else
      changed=$((changed + 1))
    fi
  done < <("${g[@]}" status --porcelain=v1 2>/dev/null)
  rec D "$changed" "$untracked"
  rec S "$("${g[@]}" stash list 2>/dev/null | wc -l)"
}

rec M "$(hostname 2>/dev/null || cat /etc/hostname)" "$(date +%s)" "$HOME"

if ! command -v git >/dev/null; then
  rec X "" "git is not installed"
  rec E
  exit 0
fi

declare -A visited=()
for folder in "$@"; do
  # A literal ~ from the command line, expanded here, on this machine.
  case $folder in
    \~) folder=$HOME ;;
    \~/*) folder=$HOME/${folder#\~/} ;;
  esac
  if [[ ! -d $folder ]]; then
    rec N "$folder"
    continue
  fi
  while IFS= read -r -d '' dotgit; do
    path=${dotgit%/.git}
    if [[ $path == *[$'\n'"$US"]* ]]; then
      rec X "" "skipped a repo whose path holds a line break"
      continue
    fi
    real=$(realpath -- "$path" 2>/dev/null) || real=$path
    [[ -n ${visited[$real]:-} ]] && continue
    visited[$real]=1
    repo "$path"
  done < <(find "$folder" -maxdepth 4 \( -name node_modules -o -name .cache \) -prune \
    -o -name .git -print0 -prune 2>/dev/null)
done

rec E
