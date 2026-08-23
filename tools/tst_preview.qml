// Regenerates plugin/preview.png -- the picture the marketplace card shows.
//
// It is a qmltestrunner scene rather than a screenshot someone remembered to
// take, so the card cannot drift away from the interface again. It shipped a
// shot of the GTK app the plugin replaced for a whole release.
//
//   make preview
//
// Theme backgrounds stand in for the wallpapers: they are what an Omarchy
// user recognises, and nobody's own pictures end up in a published image.
import QtQuick
import QtTest
import "../plugin" as Dw
import "../plugin/lib/geometry.mjs" as Geo
import "../plugin/lib/snapping.mjs" as Snap
import "../plugin/lib/luawriter.mjs" as Lua

TestCase {
  id: suite
  name: "preview"
  when: windowShown
  visible: true
  width: 1260
  height: 840

  readonly property string themes: "/usr/share/omarchy/themes/"
  readonly property var strip: [
    themes + "tokyo-night/backgrounds/5-oma-cityscape.jpg",
    themes + "tokyo-night/backgrounds/3-sunset-lake.png",
    themes + "nord/backgrounds/1-city-view.png",
    themes + "everforest/backgrounds/1-tree-tops.jpg",
    themes + "tokyo-night/backgrounds/0-winding-road.jpg",
    themes + "nord/backgrounds/2-night-hawks.png",
    themes + "catppuccin/backgrounds/2-waves.png",
    themes + "tokyo-night/backgrounds/2-swirl-buck.jpg",
  ]

  function monitor(name, w, h, x, y, scale, transform) {
    return Geo.stateFromHyprctl({
      name: name, description: name, make: "Acme", model: name,
      physicalWidth: 340, physicalHeight: 220,
      width: w, height: h, refreshRate: 60,
      x: x, y: y, scale: scale === undefined ? 1 : scale,
      transform: transform === undefined ? 0 : transform,
      disabled: false, mirrorOf: "none", focused: false,
      availableModes: [w + "x" + h + "@60.00Hz", w + "x" + h + "@144.00Hz",
                       "1920x1080@60.00Hz", "1280x720@60.00Hz"],
    })
  }

  Component {
    id: fake
    QtObject {
      property var geo: Geo
      property var snap: Snap
      property var lua: Lua
      property var states: []
      property var liveStates: []
      property string selectedName: ""
      property int revision: 0
      property string busy: ""
      property string notice: ""
      property int countdown: 0
      property bool suspended: false
      property var wallpapers: ({ version: 1, monitors: {} })
      property var wallpaperFiles: []
      property int wallpaperRevision: 0
      property string wallpaperHome: "/home/you/Pictures/Displaywright"
      function wallpaperFor(name) {
        wallpaperRevision
        if (!name || !wallpapers.monitors) return ""
        var e = wallpapers.monitors[name]
        return e && e.path ? String(e.path) : ""
      }
      function setWallpaper(p) {}
      function clearWallpaper() {}
      function addWallpaper() {}
      function removeWallpaper(p) {}
      function touch() { revision += 1 }
      function hide() {}
      function apply() {}
      function keep() {}
      function revert() {}
      function autoArrange() {}
      readonly property var selected: {
        revision
        for (var i = 0; i < states.length; i++)
          if (states[i].name === selectedName) return states[i]
        return null
      }
      readonly property bool dirty: { revision; return true }
      readonly property var problems: { revision; return [] }
    }
  }

  Component { id: paletteComp; Dw.ArrangePalette {} }
  Component { id: viewComp; Dw.ArrangeView {} }

  function test_shoot() {
    const c = fake.createObject(suite)
    c.states = [
      monitor("eDP-1", 2880, 1800, 0, 720, 2),
      monitor("DP-1", 3840, 2160, 1440, 0, 1.5),
      monitor("DP-2", 2560, 1440, 4000, 0, 1, 1),
    ]
    c.liveStates = c.states.map(Geo.copyState)
    c.selectedName = "DP-1"
    c.wallpaperFiles = strip
    c.wallpapers = { version: 1, monitors: {
      "eDP-1": { kind: "image", path: strip[3], fit: "fill" },
      "DP-1":  { kind: "image", path: strip[0], fit: "fill" },
      "DP-2":  { kind: "image", path: strip[1], fit: "fill" },
    } }

    const v = viewComp.createObject(suite, {
      controller: c, pal: paletteComp.createObject(suite),
      width: suite.width, height: suite.height,
    })
    // Every thumbnail and tile is an async Image; a grab taken before they
    // decode is a picture of empty rectangles.
    wait(3000)
    const shot = grabImage(v)
    shot.save(Qt.resolvedUrl("../plugin/preview.png").toString().replace("file://", ""))
    verify(true)
  }
}
