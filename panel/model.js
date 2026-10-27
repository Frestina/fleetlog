.pragma library
// What the panel shows, from git-fleetlog's --json. The command decides
// which commits count and what is left off; this only sorts its facts for
// the panel and words them, the way the Markdown recap does.
//
//   view(data, now) -> {
//     header     "Read at 14:20" today, or "Read Tue 14:20" on another day
//     window     "Oct 16 to Oct 23"
//     readLine   "Read from a and b. Not reached: c."
//     gaps       [{machine, text}]: not reached, cut off, repos that did not read
//     attention  [project]: something left off, newest commit first
//     worked     [project]: commits and nothing left off, newest first
//     quiet      projects with neither, counted
//     attentionCount
//   }
//   project: {key, name, account, count, countText, left: [text],
//             commits: [line], more, machines: [line]}
//
// Text from other machines (subjects, paths, branch names, errors) is
// stripped of control characters here, and the panel shows it as plain text.
// It runs in the shell as a QML library and in tests under node.

var SCHEMA = 1
var COMMITS = 50 // listed when a project is opened; the rest are counted
var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
var DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

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
    throw new Error("git-fleetlog gave no JSON")
  }
  if (!data || data.schema !== SCHEMA)
    throw new Error("git-fleetlog gave JSON of another version (schema "
                    + clean(data && data.schema) + "); update the panel and the command together")
  if (data.kind !== "recap" || !Array.isArray(data.machines) || !Array.isArray(data.projects))
    throw new Error("git-fleetlog gave JSON this panel does not read")
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
  })
  return out
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
    left: (p.left_off || []).map(function(e) { return clean(e.text) }),
    commits: shown,
    more: commits.length - shown.length,
    machines: machines,
  }
}

function view(data, now) {
  var read = [], missed = []
  data.machines.forEach(function(m) { (m.reached ? read : missed).push(clean(m.label)) })
  var readLine = read.length ? "Read from " + list(read) + "." : "No machine could be read."
  if (missed.length) readLine += " Not reached: " + list(missed) + "."

  // The command lists projects newest commit first, then by name.
  var attention = [], worked = [], quiet = 0
  data.projects.forEach(function(p) {
    if ((p.left_off || []).length) attention.push(project(p))
    else if ((p.commits || []).length) worked.push(project(p))
    else quiet++
  })

  return {
    header: header(data, now),
    window: day(new Date(data.since)) + " to " + day(new Date(data.until)),
    readLine: readLine,
    gaps: gaps(data),
    attention: attention,
    worked: worked,
    quiet: quiet,
    attentionCount: attention.length,
  }
}
