// Regenerates plugin/icon.png -- the launcher icon.
//
//   make icon
//
// Drawn rather than sourced so there is nothing to lose track of. The app
// menu shows it at around 24px, so it is one silhouette: two display frames
// standing in front of a dusk wallpaper, each framing its own piece of it.

import QtQuick
import QtTest

TestCase {
  id: suite
  name: "icon"
  when: windowShown
  visible: true
  width: 256
  height: 256

  Canvas {
    id: art
    width: 256; height: 256
    renderStrategy: Canvas.Immediate
    renderTarget: Canvas.Image

    function roundRect(ctx, x, y, w, h, r) {
      ctx.beginPath()
      ctx.moveTo(x + r, y)
      ctx.arcTo(x + w, y, x + w, y + h, r)
      ctx.arcTo(x + w, y + h, x, y + h, r)
      ctx.arcTo(x, y + h, x, y, r)
      ctx.arcTo(x, y, x + w, y, r)
      ctx.closePath()
    }

    // A display: glass that lifts the scene behind it, a bright bezel, and a
    // stand. Drawn heavy on purpose -- at 24px anything thinner vanishes.
    function display(ctx, x, y, w, h) {
      ctx.save()
      ctx.shadowColor = "rgba(20, 10, 40, 0.45)"
      ctx.shadowBlur = 18
      ctx.shadowOffsetY = 8
      roundRect(ctx, x, y, w, h, 12)
      ctx.fillStyle = "rgba(255, 255, 255, 0.2)"
      ctx.fill()
      ctx.restore()

      roundRect(ctx, x, y, w, h, 12)
      ctx.lineWidth = 11
      ctx.strokeStyle = "#fff8f0"
      ctx.stroke()

      // stand
      var cx = x + w / 2
      roundRect(ctx, cx - 5, y + h + 4, 10, 14, 4)
      ctx.fillStyle = "#fff8f0"
      ctx.fill()
      roundRect(ctx, cx - 22, y + h + 16, 44, 9, 4.5)
      ctx.fill()
    }

    onPaint: {
      var ctx = getContext("2d")
      ctx.reset()
      ctx.clearRect(0, 0, width, height)

      // The plate, and everything after it clipped to it.
      roundRect(ctx, 0, 0, 256, 256, 58)
      ctx.clip()

      // The wallpaper: night at the top down to a warm horizon.
      var sky = ctx.createLinearGradient(0, 0, 0, 256)
      sky.addColorStop(0.00, "#1b1f5e")
      sky.addColorStop(0.45, "#6a3fb5")
      sky.addColorStop(0.72, "#e9647a")
      sky.addColorStop(1.00, "#ffb05a")
      ctx.fillStyle = sky
      ctx.fillRect(0, 0, 256, 256)

      // The sun, framed by the wide display, with its glow.
      var glow = ctx.createRadialGradient(96, 122, 10, 96, 122, 70)
      glow.addColorStop(0, "rgba(255, 225, 150, 0.5)")
      glow.addColorStop(1, "rgba(255, 225, 150, 0)")
      ctx.fillStyle = glow
      ctx.fillRect(0, 0, 256, 256)
      ctx.beginPath()
      ctx.arc(96, 122, 24, 0, Math.PI * 2)
      ctx.fillStyle = "#ffe08a"
      ctx.fill()

      // Hills along the bottom.
      ctx.fillStyle = "#2a1a4a"
      ctx.beginPath()
      ctx.moveTo(0, 256)
      ctx.lineTo(0, 212)
      ctx.bezierCurveTo(50, 190, 110, 228, 168, 200)
      ctx.bezierCurveTo(200, 184, 232, 196, 256, 214)
      ctx.lineTo(256, 256)
      ctx.closePath()
      ctx.fill()

      // Two displays: one landscape, one turned portrait. The arrangement is
      // the product, so the icon is an arrangement.
      display(ctx, 30, 76, 124, 84)
      display(ctx, 170, 52, 58, 108)
    }
  }

  function test_shoot() {
    art.requestPaint()
    wait(300)
    const shot = grabImage(art)
    shot.save(String(Qt.resolvedUrl("../plugin/icon.png")).replace("file://", ""))
    verify(true)
  }
}
