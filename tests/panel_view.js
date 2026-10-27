// Runs panel/model.js under node as the panel does in the shell: git-fleetlog's
// --json on stdin, {view} or {error} on stdout.
//
//   node tests/panel_view.js <now, ms since the epoch>
//
// The shell loads model.js as a QML library, whose first line node cannot
// parse, so it is dropped here and the rest runs in a context of its own.
"use strict"
const fs = require("fs")
const path = require("path")
const vm = require("vm")

const file = path.join(__dirname, "..", "panel", "model.js")
const code = fs.readFileSync(file, "utf8").replace(/^\.pragma library\n/, "")
const model = vm.createContext({})
vm.runInContext(code, model, { filename: file })

let out
try {
  const data = model.parse(fs.readFileSync(0, "utf8"))
  out = { view: model.view(data, new Date(Number(process.argv[2]))) }
} catch (e) {
  out = { error: e.message }
}
process.stdout.write(JSON.stringify(out))
