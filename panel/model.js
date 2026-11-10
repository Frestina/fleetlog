.pragma library
// What the panel shows, from fleetlog's --json. The command decides
// which commits count and what is left off; this only sorts its facts for
// the panel and words them, the way the Markdown recap does.
//
//   view(data, now) -> {
//     header     "Read at 14:20" today, or "Read Tue 14:20" on another day
//     window     "Oct 16 to Oct 23"
//     readLine   "Read from a and b. Not reached: c."
//     gaps       [{machine, text}]: not reached, cut off, repos that did not read,
//                folders named for a machine that are not there, and notices
//                about this machine's setup
//     attention  [project]: something left off, newest commit first
//     worked     [project]: commits and nothing left off, newest first
//     machines   [row]: the same left-off lines by machine instead, in the
//                order the machines are listed: each machine with something
//                left off, its lines named by project, and the commits made
//                there. A row has a project's shape, so the panel draws both
//                alike
//     week       [project]: every project with commits, newest first, without
//                its left-off lines, to go under machines
//     quiet      projects with neither, counted
//     attentionCount
//     group      "machine" or "project": what the config has the panel group
//                left-off work by when it starts ([panel] group)
//     onlyThisMachine  no machine listed yet but the one the panel runs on
//   }
//   project: {key, name, account, count, countText, needs, on: [machine],
//             left: [{text, icon, ask, project, machine, group}],
//             commits: [line], more, machines: [line]}
//   needs: something is left off, whether or not left lists it
//   group: what ask is on the first line of its machine and project, on
//          every line of them, so the button can move when lines are
//          filtered away
//
//   filter(view, text) -> the view with only the lines and projects that
//   every word of text names, by project or by machine
//   icon: what the line is about, which the panel draws in front of it: push,
//         pull, fetch, commit, stash, no-remote, gone or unknown, or "" for a
//         kind of line this version does not know
//   ask: on the first left-off line of each machine, what its agent button
//        passes to `fleetlog ask-agent`: {machine, path, lines: [text]}
//
// Text from other machines (subjects, paths, branch names, errors) is
// stripped of control characters here, and the panel shows it as plain text.
// It runs in the shell as a QML library and in tests under node.

var SCHEMA = 1
var COMMITS = 50 // listed when a project is opened; the rest are counted
var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
var DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
// What a left-off line is about, by its kind in the JSON.
var ABOUT = {
  "unpushed": "push", "never-pushed": "push", "no-remote": "no-remote",
  "behind": "pull", "not-fetched": "fetch", "gone": "gone",
  "uncommitted": "commit", "unknown": "unknown", "stash": "stash",
}

function clean(text) {
  return String(text === undefined || text === null ? "" : text)
    .replace(/[\x00-\x1f\x7f-\x9f]/g, "")
}

// The --json output, if it has the shape this version reads; throws why not.
function parse(text) {
  var data
  try {
    data = JSON.parse(text)
  } catch (e) {
    throw new Error("fleetlog gave no JSON")
  }
  if (!data || data.schema !== SCHEMA)
    throw new Error("fleetlog gave JSON of another version (schema "
                    + clean(data && data.schema) + "); update the panel and the command together")
  if (data.kind !== "recap" || !Array.isArray(data.machines) || !Array.isArray(data.projects))
    throw new Error("fleetlog gave JSON this panel does not read")
  return data
}

function n(count, one, many) {
  return count + " " + (count === 1 ? one : (many || one + "s"))
}

function list(words) {
  if (words.length <= 1) return words.join("")
  return words.slice(0, -1).join(", ") + " and " + words[words.length - 1]
}

function pad(x) {
  return (x < 10 ? "0" : "") + x
}

function day(date) {
  return MONTHS[date.getMonth()] + " " + date.getDate()
}

function clock(date) {
  return pad(date.getHours()) + ":" + pad(date.getMinutes())
}

function sameDay(a, b) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth()
    && a.getDate() === b.getDate()
}

function header(data, now) {
  var until = new Date(data.until)
  return "Read " + (sameDay(until, now) ? "at " : DAYS[until.getDay()] + " ") + clock(until)
}

function gaps(data) {
  var out = []
  data.machines.forEach(function(m) {
    var label = clean(m.label)
    if (!m.reached) {
      var tried = m.tries > 1 ? ", tried " + m.tries + " times" : ""
      out.push({ machine: label, text: "not reached: " + clean(m.error || "no answer") + tried })
      return
    }
    if (!m.complete)
      out.push({ machine: label, text: clean(m.error || "the output was cut off") })
    var problems = m.problems || []
    problems.forEach(function(p) {
      out.push({ machine: label, text: (p.path ? clean(p.path) + ": " : "") + clean(p.reason) })
    })
    var unfound = m.folders_not_found || []
    unfound.forEach(function(f) {
      out.push({ machine: label, text: "folder not found: " + clean(f) })
    })
  })
  // About this machine's setup, such as timers the config has changed.
  var here = data.machines.filter(function(m) { return m.local === true })[0]
  var notices = Array.isArray(data.notices) ? data.notices : []
  notices.forEach(function(text) {
    out.push({ machine: here ? clean(here.label) : "", text: clean(String(text)) })
  })
  return out
}

function about(kind) {
  return typeof kind === "string" && Object.prototype.hasOwnProperty.call(ABOUT, kind)
    ? ABOUT[kind] : ""
}

// The left-off lines, with an agent button on each machine's first. The
// path goes to the command as an argument, exact, since the agent starts in
// it; it is never shown.
function leftOff(p) {
  var entries = p.left_off || []
  var name = clean(p.name)
  var group = null
  return entries.map(function(e, i) {
    var first = i === 0 || entries[i - 1].machine !== e.machine
    if (first) {
      var mine = entries.filter(function(o) { return o.machine === e.machine })
      var named = mine.filter(function(o) { return typeof o.path === "string" })[0]
      var path = named ? named.path : ((p.paths || {})[e.machine] || [])[0]
      group = typeof path === "string" && path !== ""
        ? { machine: String(e.machine), path: path,
            lines: mine.map(function(o) { return clean(o.text) }) }
        : null
    }
    return { text: clean(e.text), icon: about(e.kind), ask: first ? group : null,
             project: name, machine: clean(e.machine), group: group }
  })
}

// The lines with the agent button on the first of each group that is left.
function buttons(lines) {
  var seen = []
  return lines.map(function(line) {
    var first = line.group !== null && seen.indexOf(line.group) < 0
    if (first) seen.push(line.group)
    return Object.assign({}, line, { ask: first ? line.group : null })
  })
}

// The commits a machine's row lists when it is opened, and how many more.
function listed(row, made) {
  return Object.assign({}, row, {
    made: made,
    commits: made.slice(0, COMMITS).map(function(c) { return c.line }),
    more: Math.max(0, made.length - COMMITS),
  })
}

function project(p) {
  var commits = p.commits || []
  var shown = commits.slice(0, COMMITS).map(function(c) {
    var on = (c.made_on || []).map(clean).join("+")
    return day(new Date(c.time)) + (on ? " " + on : "") + ": " + clean(c.subject)
  })
  var machines = Object.keys(p.paths || {}).map(function(label) {
    return clean(label) + ": " + p.paths[label].map(clean).join(", ")
  })
  return {
    key: clean(p.root || p.name + " " + JSON.stringify(p.paths)),
    name: clean(p.name),
    account: clean(p.account),
    count: commits.length,
    countText: commits.length ? n(commits.length, "commit") : "no commits",
    needs: (p.left_off || []).length > 0,
    on: Object.keys(p.paths || {}).map(clean),
    left: leftOff(p),
    commits: shown,
    more: commits.length - shown.length,
    machines: machines,
  }
}

// A left-off line that starts with its project instead of its machine:
// "desktop: 1 stash" is "tool: 1 stash", and "desktop (~/tool): 1 stash",
// one of several clones there, is "tool (~/tool): 1 stash".
function named(project, machine, text) {
  var label = clean(machine)
  if (text.indexOf(label + ": ") === 0 || text.indexOf(label + " (") === 0)
    return project + text.slice(label.length)
  return project + ": " + text
}

// The left-off lines by machine: a row for each machine with something left
// off, in the order the machines are listed. Its lines start with the
// project instead of the machine, with the agent button on each project's
// first, and its commits are the ones made there, newest first (made, each
// with its project, so they can be filtered).
function byMachine(data) {
  var rows = {}, order = []
  function row(machine) {
    var id = "machine " + String(machine)
    if (!rows[id]) {
      rows[id] = { key: id, name: clean(machine), account: "", left: [], made: [] }
      order.push(id)
    }
    return rows[id]
  }
  data.machines.forEach(function(m) { row(m.label) })
  data.projects.forEach(function(p) {
    var name = clean(p.name)
    var lines = leftOff(p)
    var entries = p.left_off || []
    entries.forEach(function(e, i) {
      row(e.machine).left.push(Object.assign({}, lines[i], {
        text: named(name, e.machine, lines[i].text) }))
    })
    var commits = p.commits || []
    commits.forEach(function(c) {
      var when = new Date(c.time)
      var on = c.made_on || []
      on.forEach(function(machine) {
        row(machine).made.push({ at: when.getTime(), project: name,
                                 line: day(when) + " " + name + ": " + clean(c.subject) })
      })
    })
  })
  return order.map(function(id) { return rows[id] })
    .filter(function(r) { return r.left.length > 0 })
    .map(function(r) {
      r.made.sort(function(a, b) { return b.at - a.at })
      return listed({
        key: r.key, name: r.name, account: r.account,
        count: r.made.length,
        countText: r.made.length ? n(r.made.length, "commit") : "no commits",
        needs: true,
        on: [r.name],
        left: r.left,
        machines: [],
      }, r.made)
    })
}

// The view with only what every word of text names, by project or by
// machine, whatever the case: "desk" keeps what is on desktop, "dot" the
// dotfiles, "desk dot" the dotfiles on desktop. A row with left-off lines
// keeps the lines that match and goes when none does; a machine's row lists
// only the matching projects' commits. A project with none stays when its
// name or a machine it is on matches. The counts and the gaps are untouched:
// a filter never hides a machine that was not read.
function filter(v, text) {
  var words = clean(text).toLowerCase().split(/\s+/)
    .filter(function(w) { return w !== "" })
  if (!words.length) return v
  function hit(project, machines) {
    return words.every(function(w) {
      return project.toLowerCase().indexOf(w) >= 0
        || machines.some(function(m) { return m.toLowerCase().indexOf(w) >= 0 })
    })
  }
  function lines(rows) {
    var out = []
    rows.forEach(function(r) {
      var left = buttons(r.left.filter(function(l) { return hit(l.project, [l.machine]) }))
      if (!left.length) return
      var row = Object.assign({}, r, { left: left })
      out.push(r.made ? listed(row, r.made.filter(function(c) {
        return hit(c.project, r.on) })) : row)
    })
    return out
  }
  function projects(rows) {
    return rows.filter(function(r) { return hit(r.name, r.on) })
  }
  return Object.assign({}, v, {
    attention: lines(v.attention), machines: lines(v.machines),
    worked: projects(v.worked), week: projects(v.week),
  })
}

function view(data, now) {
  var read = [], missed = []
  data.machines.forEach(function(m) { (m.reached ? read : missed).push(clean(m.label)) })
  var readLine = read.length ? "Read from " + list(read) + "." : "No machine could be read."
  if (missed.length) readLine += " Not reached: " + list(missed) + "."

  // The command lists projects newest commit first, then by name.
  var attention = [], worked = [], week = [], quiet = 0
  data.projects.forEach(function(p) {
    if ((p.left_off || []).length) attention.push(project(p))
    else if ((p.commits || []).length) worked.push(project(p))
    else quiet++
    if ((p.commits || []).length) {
      var row = project(p)
      row.left = []
      week.push(row)
    }
  })

  return {
    header: header(data, now),
    window: day(new Date(data.since)) + " to " + day(new Date(data.until)),
    readLine: readLine,
    gaps: gaps(data),
    attention: attention,
    worked: worked,
    machines: byMachine(data),
    week: week,
    quiet: quiet,
    attentionCount: attention.length,
    group: data.panel && data.panel.group === "project" ? "project" : "machine",
    onlyThisMachine: data.machines.length > 0
      && data.machines.every(function(m) { return m.local === true }),
  }
}
