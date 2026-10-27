pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "model.js" as Model

// The bar icon and panel for git-fleetlog. bin/git-fleetlog decides which
// commits count and what is left off, and says so in --json; this only shows
// it, sorted by what needs doing (model.js). See SPEC.md, The panel.
//
// Opening it shows the latest weekly recap from the main machine (one ssh
// call); refresh reads every machine now. What it read stays while the shell
// runs, so opening it again asks no machine anything, except that a weekly
// recap is fetched again after an hour, to pick up a new week's.
//
// left = the panel · right = the full recap in a terminal.
// In the panel: r refresh, t the full recap, j/k or arrows scroll, Esc close.
Panel {
  id: root
  moduleName: "io.github.frestina.fleetlog"
  ipcTarget: "io.github.frestina.fleetlog"

  readonly property string command: decodeURIComponent(
    Qt.resolvedUrl("../bin/git-fleetlog").toString().replace(/^file:\/\//, ""))
  readonly property string fontFamily: root.bar ? root.bar.fontFamily : Style.font.family

  readonly property string glyphCommit: String.fromCodePoint(0xF0718)
  readonly property string glyphRefresh: String.fromCodePoint(0xF0450)
  readonly property string glyphTerminal: String.fromCodePoint(0xF018D)
  readonly property string glyphOpen: String.fromCodePoint(0xF0140)
  readonly property string glyphClosed: String.fromCodePoint(0xF0142)
  readonly property string glyphAlert: String.fromCodePoint(0xF0026)
  readonly property string glyphCheck: String.fromCodePoint(0xF012C)

  // What the panel shows (Model.view), and where it came from: "weekly" for
  // `latest --json`, "now" for `--json`.
  property var view: null
  property string source: ""
  property bool loading: false
  property string loadingSource: ""
  property string error: ""
  property real triedAt: 0
  // Per run: a binary that fails to start only flips proc.running, with no
  // exited or stream signals, so finish() keys off running and these.
  property bool procStarted: false
  property int procExitCode: 0

  // Projects opened to show their commits, by key; kept across reads.
  property var openProjects: ({})

  // Left-off work in the theme's orange (or yellow), which the shell's
  // palette lacks; its accent can be any hue, red included.
  property color warnColor: Color.accent

  readonly property string tooltipText: {
    if (!root.view) return "git-fleetlog: your commits and where you left off"
    var n = root.view.attentionCount
    return "git-fleetlog: " + (n === 0 ? "all pushed and committed"
      : n + (n === 1 ? " project needs" : " projects need") + " attention")
      + " (" + root.view.header + ")"
  }

  function load(which) {
    if (proc.running) return
    root.loading = true
    root.loadingSource = which
    root.procStarted = false
    root.procExitCode = 0
    root.triedAt = Date.now()
    proc.command = which === "now" ? [root.command, "--json"] : [root.command, "latest", "--json"]
    proc.running = true
  }

  function refresh() { root.load("now") }

  function finish() {
    root.loading = false
    if (!root.procStarted) {
      root.error = "could not run " + root.command
      return
    }
    // 0: every machine was read; 1: one was not, which the JSON says; 2: an error.
    if (root.procExitCode !== 0 && root.procExitCode !== 1) {
      const reason = Model.clean(errOut.text.trim().split("\n").pop()).replace(/^git-fleetlog: /, "")
      root.error = (reason || "git-fleetlog exited " + root.procExitCode).slice(0, 300)
      return
    }
    try {
      root.view = Model.view(Model.parse(out.text), root.loadingSource, new Date())
      root.source = root.loadingSource
      root.error = ""
    } catch (e) {
      root.error = String(e.message).slice(0, 300)
    }
  }

  // The full Markdown recap in a terminal: the same weekly recap, or every
  // machine read again. The command and its words go to bash as arguments.
  function openRecap() {
    root.close()
    var args = root.source === "now" ? [] : ["latest"]
    Quickshell.execDetached(["omarchy-launch-tui", "--app-id=org.omarchy.terminal",
                             "bash", "-c", "\"$0\" \"$@\" | less", root.command].concat(args))
  }

  function toggleProject(key) {
    var open = Object.assign({}, root.openProjects)
    open[key] = !open[key]
    root.openProjects = open
  }

  function scroll(dy) {
    var most = Math.max(0, flick.contentHeight - flick.height)
    flick.contentY = Math.max(0, Math.min(most, flick.contentY + dy * Style.space(48)))
  }

  // Muted text as see-through bar foreground, so it recedes on light and dark
  // themes alike (Qt.darker only mutes light-on-dark).
  function dim(alpha) {
    return Qt.rgba(root.barForeground.r, root.barForeground.g, root.barForeground.b, alpha)
  }

  // The first of orange, yellow and ANSI yellow that colors.toml has.
  function loadWarnColor(raw) {
    var found = {}
    String(raw || "").split("\n").forEach(function(line) {
      var match = line.match(/^\s*([A-Za-z0-9_-]+)\s*=\s*["']?(#[0-9A-Fa-f]{6})/)
      if (match) found[match[1]] = match[2]
    })
    root.warnColor = found.orange || found.yellow || found.color3 || Color.accent
  }

  onOpenedChanged: {
    if (!root.opened || proc.running) return
    var age = Date.now() - root.triedAt
    // Nothing shown: fetch, but not again within a minute of a failure.
    if (!root.view) {
      if (age > 60000) root.load("weekly")
    } else if (root.source === "weekly" && age > 3600000) {
      root.load("weekly")
    }
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  // Both streams finish and exited fires before running drops, so finish()
  // sees this run's complete output.
  Process {
    id: proc
    onStarted: root.procStarted = true
    onExited: function(exitCode) { root.procExitCode = exitCode }
    onRunningChanged: if (!running) root.finish()
    stdout: StdioCollector { id: out; waitForEnd: true }
    stderr: StdioCollector { id: errOut; waitForEnd: true }
  }

  FileView {
    id: themeColors
    path: Color.currentThemePath + "/colors.toml"
    printErrors: false
    onLoaded: root.loadWarnColor(text())
    onLoadFailed: root.loadWarnColor("")
  }

  // A theme switch reaches the shell's palette over IPC, without a file
  // change to watch; read the new theme when the palette changes.
  Connections {
    target: Color
    function onAccentChanged() { themeColors.reload() }
    function onUrgentChanged() { themeColors.reload() }
    function onBackgroundChanged() { themeColors.reload() }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.glyphCommit
    tooltipText: root.opened ? "" : root.tooltipText
    onPressed: function(b) {
      if (b === Qt.RightButton) root.openRecap()
      else root.toggle()
    }
  }

  // One project: its name, account and commit count, what is left off, and
  // on a click its commits and the machines it is on.
  Component {
    id: projectRow

    Rectangle {
      id: row
      required property var modelData
      readonly property bool needsWork: modelData.left.length > 0
      readonly property bool expanded: !!root.openProjects[modelData.key]

      width: list.width
      implicitHeight: rowColumn.implicitHeight + Style.space(10)
      radius: Style.cornerRadius
      color: rowMouse.containsMouse ? root.dim(0.06) : "transparent"

      MouseArea {
        id: rowMouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.toggleProject(row.modelData.key)
      }

      Column {
        id: rowColumn
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.leftMargin: Style.space(6)
        anchors.rightMargin: Style.space(6)
        spacing: Style.space(3)

        RowLayout {
          width: parent.width
          spacing: Style.space(8)

          Text {
            text: row.needsWork ? root.glyphAlert : root.glyphCheck
            color: row.needsWork ? root.warnColor : root.dim(0.45)
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }

          Text {
            Layout.fillWidth: true
            textFormat: Text.PlainText
            text: row.modelData.name
            color: root.barForeground
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            font.bold: true
            elide: Text.ElideRight
          }

          Text {
            visible: row.modelData.account !== ""
            textFormat: Text.PlainText
            text: row.modelData.account
            color: root.dim(0.45)
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }

          Text {
            textFormat: Text.PlainText
            text: row.modelData.countText
            color: root.dim(0.6)
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }

          Text {
            text: row.expanded ? root.glyphOpen : root.glyphClosed
            color: root.dim(0.45)
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
        }

        Repeater {
          model: row.modelData.left

          delegate: Text {
            required property string modelData
            width: rowColumn.width
            leftPadding: Style.space(18)
            textFormat: Text.PlainText
            text: "• " + modelData
            wrapMode: Text.Wrap
            color: root.barForeground
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }
        }

        Repeater {
          model: row.expanded ? row.modelData.commits : []

          delegate: Text {
            required property string modelData
            width: rowColumn.width
            leftPadding: Style.space(18)
            textFormat: Text.PlainText
            text: modelData
            elide: Text.ElideRight
            color: root.dim(0.75)
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }
        }

        Text {
          visible: row.expanded && row.modelData.more > 0
          width: rowColumn.width
          leftPadding: Style.space(18)
          textFormat: Text.PlainText
          text: "and " + row.modelData.more + " more"
          color: root.dim(0.5)
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
        }

        Repeater {
          model: row.expanded ? row.modelData.machines : []

          delegate: Text {
            required property string modelData
            width: rowColumn.width
            leftPadding: Style.space(18)
            textFormat: Text.PlainText
            text: "On " + modelData
            elide: Text.ElideMiddle
            color: root.dim(0.5)
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
        }
      }
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(440))
    contentHeight: panel.fittedContentHeight(content.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onMoveRequested: function(dx, dy) { root.scroll(dy) }
      onTextKey: function(t) {
        if (t === "r") root.refresh()
        else if (t === "t") root.openRecap()
      }

      Column {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        spacing: Style.space(10)

        // Everything but the list, so the list can take the height left.
        readonly property real chromeHeight: hero.implicitHeight + topRule.height
          + bottomRule.height + footer.implicitHeight + content.spacing * 4
          + (errorText.visible ? errorText.implicitHeight + content.spacing : 0)

        // ---------- Hero: icon · title and what is shown · actions ----------
        RowLayout {
          id: hero
          width: parent.width
          spacing: Style.space(12)

          Text {
            text: root.glyphCommit
            color: root.view && root.view.attentionCount > 0 ? root.warnColor : root.barForeground
            font.family: root.fontFamily
            font.pixelSize: Style.font.display
          }

          Column {
            Layout.fillWidth: true
            spacing: Style.space(2)

            Text {
              text: "Fleetlog"
              color: root.barForeground
              font.family: root.fontFamily
              font.pixelSize: Style.font.title
              font.bold: true
            }

            Text {
              width: parent.width
              textFormat: Text.PlainText
              text: (root.loading
                ? (root.loadingSource === "now" ? "Reading every machine…" : "Fetching the weekly recap…")
                : root.view ? root.view.header : "").toUpperCase()
              color: root.dim(0.6)
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              font.bold: true
              font.letterSpacing: 1.2
              elide: Text.ElideRight
            }

            Text {
              visible: !!root.view
              width: parent.width
              textFormat: Text.PlainText
              text: root.view ? root.view.window + ". " + root.view.readLine : ""
              color: root.view && root.view.gaps.length > 0 ? Color.urgent : root.dim(0.5)
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.Wrap
            }
          }

          PanelActionButton {
            iconText: root.glyphRefresh
            tooltipText: "Read every machine now (r)"
            foreground: root.barForeground
            fontFamily: root.fontFamily
            enabled: !root.loading
            onClicked: root.refresh()
          }

          PanelActionButton {
            iconText: root.glyphTerminal
            tooltipText: "The full recap in a terminal (t)"
            foreground: root.barForeground
            fontFamily: root.fontFamily
            onClicked: root.openRecap()
          }
        }

        Text {
          id: errorText
          visible: root.error !== ""
          width: parent.width
          textFormat: Text.PlainText
          text: root.error + (root.view ? ". Showing what was read before."
                                        : ". Refresh reads every machine now.")
          wrapMode: Text.Wrap
          color: Color.urgent
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
        }

        PanelSeparator { id: topRule; foreground: root.barForeground }

        Flickable {
          id: flick
          width: parent.width
          height: Math.min(list.implicitHeight, Math.max(Style.space(120),
            panel.availableCardHeight - panel.verticalContentInset - content.chromeHeight))
          contentHeight: list.implicitHeight
          clip: true
          boundsBehavior: Flickable.StopAtBounds

          Column {
            id: list
            width: flick.width
            spacing: Style.space(4)

            // ---------- Machines not read: first, so a gap is never missed ----------
            PanelSectionHeader {
              visible: !!root.view && root.view.gaps.length > 0
              text: "NOT FULLY READ"
              foreground: root.barForeground
              fontFamily: root.fontFamily
            }

            Repeater {
              model: root.view ? root.view.gaps : []

              delegate: Text {
                required property var modelData
                width: list.width
                leftPadding: Style.space(6)
                textFormat: Text.PlainText
                text: "• " + modelData.machine + ": " + modelData.text
                wrapMode: Text.Wrap
                color: Color.urgent
                font.family: root.fontFamily
                font.pixelSize: Style.font.bodySmall
              }
            }

            PanelSectionHeader {
              visible: !!root.view && root.view.attention.length > 0
              text: "NEEDS ATTENTION"
              foreground: root.barForeground
              fontFamily: root.fontFamily
            }

            Repeater {
              model: root.view ? root.view.attention : []
              delegate: projectRow
            }

            PanelSectionHeader {
              visible: !!root.view && root.view.worked.length > 0
              text: "THIS WEEK, ALL PUSHED"
              foreground: root.barForeground
              fontFamily: root.fontFamily
            }

            Repeater {
              model: root.view ? root.view.worked : []
              delegate: projectRow
            }

            Text {
              visible: !!root.view && root.view.attention.length === 0 && root.view.worked.length === 0
              width: list.width
              textFormat: Text.PlainText
              text: "No commits of yours in this time, and nothing left off."
              wrapMode: Text.Wrap
              color: root.dim(0.6)
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
            }

            Text {
              visible: !!root.view && root.view.quiet > 0
              width: list.width
              topPadding: Style.space(4)
              textFormat: Text.PlainText
              text: root.view ? root.view.quiet + (root.view.quiet === 1 ? " other project" : " other projects")
                + " with no commits in this time and nothing left off" : ""
              wrapMode: Text.Wrap
              color: root.dim(0.45)
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
          }
        }

        PanelSeparator { id: bottomRule; foreground: root.barForeground }

        Text {
          id: footer
          width: parent.width
          textFormat: Text.PlainText
          text: "Click a project for its commits · r refresh · t full recap"
          horizontalAlignment: Text.AlignHCenter
          wrapMode: Text.Wrap
          color: root.dim(0.45)
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }
      }
    }
  }
}
