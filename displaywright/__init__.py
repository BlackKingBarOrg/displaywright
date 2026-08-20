"""displaywright — display arrangement and per-display wallpapers for Omarchy.

Two things about a multi-monitor desktop that no other tool on Hyprland does
together: where the displays are, and what is drawn on them. They share a model
(:mod:`displaywright.model`), a compositor (:mod:`displaywright.hypr`) and a
canvas (:mod:`displaywright.canvas`), so they live in one window with one
selection rather than in two apps that disagree about your desk.

* :mod:`displaywright.displays` arranges outputs and writes Omarchy's
  ``monitors.lua``.
* :mod:`displaywright.wallpapers` decides what each output draws, and ships the
  ``omarchy-shell`` plugin that draws it.
"""

__version__ = "0.1.0"
APP_ID = "ai.bkblab.displaywright"
APP_NAME = "displaywright"

__all__ = ["APP_ID", "APP_NAME", "__version__"]
