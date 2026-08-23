// Regenerates plugin/icon.png -- the launcher icon.
//
//   make icon
//
// Drawn rather than sourced so there is nothing to lose track of, and kept to
// three shapes because the launcher renders it at 32px as often as 256.

import QtQuick
import QtTest

TestCase {
  id: suite
  name: "icon"
  when: windowShown
  visible: true
  width: 256
  height: 256

  Component {
    id: art
    Rectangle {
      width: 256; height: 256
      radius: 56
      gradient: Gradient {
        GradientStop { position: 0.0; color: "#4a90e2" }
        GradientStop { position: 1.0; color: "#2b5fa8" }
      }

      // Two landscape displays side by side and one turned portrait: the
      // arrangement is the product, so the icon is an arrangement.
      Rectangle {
        x: 34; y: 96; width: 92; height: 60; radius: 7
        color: "#ffffff"; opacity: 0.95
      }
      Rectangle {
        x: 134; y: 74; width: 88; height: 56; radius: 7
        color: "#ffffff"; opacity: 0.72
      }
      Rectangle {
        x: 150; y: 140; width: 44; height: 68; radius: 7
        color: "#ffffff"; opacity: 0.45
      }
    }
  }

  function test_shoot() {
    const item = art.createObject(suite)
    wait(300)
    const shot = grabImage(item)
    shot.save(String(Qt.resolvedUrl("../plugin/icon.png")).replace("file://", ""))
    verify(true)
  }
}
