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
// The icon reads every machine once an hour, at :20, clear of Fleet doctor's
// runs and git-fleetlog's own timers, and shows how many projects need
// attention. Every monitor has an icon of its own; they share one read
// through `--reuse-from`, which the command answers from its cache once one
// of them has read. Opening the panel shows that read and asks no machine
// anything; refresh reads every machine now, once for all monitors.
//
// left = the panel · right = the full recap in a terminal.
// In the panel: r refresh, t the full recap, s settings, j/k or arrows
// scroll, Esc close. Settings opens the config (`git-fleetlog config`), and
// saving it reads every machine again.
Panel {
  id: root
  moduleName: "io.github.frestina.fleetlog"
  ipcTarget: "io.github.frestina.fleetlog"

  readonly property string command: decodeURIComponent(
    Qt.resolvedUrl("../bin/git-fleetlog").toString().replace(/^file:\/\//, ""))
  readonly property string fontFamily: root.bar ? root.bar.fontFamily : Style.font.family
  // Matches config_path() in fleetlog/config.py.
  readonly property string configPath: (Quickshell.env("XDG_CONFIG_HOME")
    || Quickshell.env("HOME") + "/.config") + "/git-fleetlog/config"

  readonly property string glyphCommit: String.fromCodePoint(0xF0718)
  readonly property string glyphRefresh: String.fromCodePoint(0xF0450)
  readonly property string glyphTerminal: String.fromCodePoint(0xF018D)
  readonly property string glyphOpen: String.fromCodePoint(0xF0140)
  readonly property string glyphClosed: String.fromCodePoint(0xF0142)
  readonly property string glyphAlert: String.fromCodePoint(0xF0026)
  readonly property string glyphCheck: String.fromCodePoint(0xF012C)
  readonly property string glyphSettings: String.fromCodePoint(0xF0493)

  // The last read (parsed --json), what the panel shows of it (Model.view,
  // worded again on each open, so "Read at" turns into a day when it should),
  // and when its machines were read (Unix seconds). The hourly read is due at
  // the latest :20; dueTried keeps a failed one from being tried again every
  // minute until the next.
  property var lastRead: null
  property var now: new Date()
  readonly property var view: root.lastRead ? Model.view(root.lastRead, root.now) : null
  property real readAt: 0
  property real dueTried: 0
  property bool loading: false
  property string error: ""
  property real triedAt: 0
  // A refresh that came mid-read (Unix seconds), asked for once it ends.
  property real pendingFrom: 0
  readonly property int count: root.view ? root.view.attentionCount : 0
  // Per run: a binary that fails to start only flips proc.running, with no
  // exited or stream signals, so finish() keys off running and these.
  property bool procStarted: false
  property int procExitCode: 0

  // When the config was saved (Unix seconds), and whether it was there to
  // watch; see configSaved().
  property real savedAt: 0
  property bool configFound: false

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
      + " (" + root.view.header.charAt(0).toLowerCase() + root.view.header.slice(1) + ")"
  }

  // The last 7 days, from the last read if it started at or after `from`
  // (Unix seconds), else from a new one that the other monitors then share.
  function load(from) {
    if (proc.running) return
    root.loading = true
    root.procStarted = false
    root.procExitCode = 0
    root.triedAt = Date.now()
    proc.command = [root.command, "--json", "--reuse-from", String(Math.floor(from))]
    proc.running = true
  }

  // The latest :20 at or before now, in Unix seconds.
  function due() {
    var d = new Date()
    var at = new Date(d.getFullYear(), d.getMonth(), d.getDate(), d.getHours(), 20)
    if (at > d) at = new Date(at.getTime() - 3600000)
    return Math.floor(at.getTime() / 1000)
  }

  // Every minute: read once a :20 has passed since the last read. Checking,
  // instead of waiting for the next :20, also catches up after a suspend.
  function tick() {
    var at = root.due()
    if (proc.running || root.readAt >= at || root.dueTried === at) return
    root.dueTried = at
    root.load(at)
  }

  // Read every machine now, or since `from` (Unix seconds), for this
  // monitor's icon and the others: they all ask from the same moment, so the
  // first reads and the rest reuse it.
  function refresh(from) {
    if (from === undefined) from = Math.floor(Date.now() / 1000)
    var items = root.bar && typeof root.bar.moduleWidgets === "function"
      ? root.bar.moduleWidgets(root.moduleName) : []
    if (items.indexOf(root) < 0) items = items.concat([root])
    for (var i = 0; i < items.length; i++)
      if (items[i] && typeof items[i].refreshFrom === "function") items[i].refreshFrom(from)
  }

  function refreshFrom(from) {
    if (proc.running) root.pendingFrom = Math.max(root.pendingFrom, from)
    else root.load(from)
  }

  function finish() {
    root.loading = false
    if (root.pendingFrom > 0) {
      var from = root.pendingFrom
      root.pendingFrom = 0
      Qt.callLater(root.load, from)
    }
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
      const read = Model.parse(out.text)
      root.now = new Date()
      root.lastRead = read
      root.readAt = Math.floor(new Date(read.until).getTime() / 1000)
      root.error = ""
    } catch (e) {
      root.error = String(e.message).slice(0, 300)
    }
  }

  // The full Markdown recap in a terminal, of the same read, from the
  // command's cache. The command and its words go to bash as arguments.
  function openRecap() {
    root.close()
    var from = root.readAt > 0 ? root.readAt : root.due()
    Quickshell.execDetached(["omarchy-launch-tui", "--app-id=org.omarchy.terminal",
                             "bash", "-c", "\"$0\" \"$@\" | less", root.command,
                             "--reuse-from", String(from)])
  }

  // The config in Omarchy's editor; the command writes a commented guide
  // there first when there is none.
  function editConfig() {
    root.close()
    Quickshell.execDetached([root.command, "config"])
    configRetry.restart()
  }

  // Every monitor's icon sees the save, at the same moment; reading since
  // then lets them share one read once the editor is done writing.
  function configSaved() {
    if (!saveSettle.running) root.savedAt = Math.floor(Date.now() / 1000)
    saveSettle.restart()
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

  // Opening shows the last read. Only with nothing to show does it read, and
  // not again within a minute of a failure.
  onOpenedChanged: {
    if (!root.opened) return
    root.now = new Date()
    if (!root.view && !proc.running && Date.now() - root.triedAt > 60000) root.load(root.due())
  }

  Timer {
    interval: 60000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.tick()
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

  // A watch takes on a missing file only when its folder is there, so once
  // the command has had time to write the config, watch it again.
  FileView {
    id: configFile
    path: root.configPath
    watchChanges: true
    printErrors: false
    onLoaded: root.configFound = true
    onLoadFailed: root.configFound = false
    onFileChanged: root.configSaved()
  }

  Timer {
    id: configRetry
    interval: 2000
    onTriggered: if (!root.configFound) configFile.reload()
  }

  // Editors save in several steps; read once they are done.
  Timer {
    id: saveSettle
    interval: 1000
    onTriggered: root.refresh(root.savedAt)
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
    // The count beside the glyph, on a horizontal bar; a vertical one has no
    // room, and the tooltip says it.
    readonly property bool counted: root.count > 0 && !vertical
    text: counted ? root.glyphCommit + " " + root.count : root.glyphCommit
    slotSize: Style.bar.iconSlot * (counted ? 1.1 + 0.5 * String(root.count).length : 1)
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
        else if (t === "s") root.editConfig()
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
              text: (root.loading ? "Reading every machine…"
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

        // ---------- Footer: settings, then the keys on a line of their own ----------
        Column {
          id: footer
          width: parent.width
          spacing: Style.space(6)

          RowLayout {
            width: parent.width

            Item { Layout.fillWidth: true }

            Button {
              iconText: root.glyphSettings
              text: "Settings"
              tooltipText: "Include or exclude projects, folders and machines (s)"
              foreground: root.barForeground
              fontFamily: root.fontFamily
              fontSize: Style.font.bodySmall
              onClicked: root.editConfig()
            }
          }

          Text {
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
}
