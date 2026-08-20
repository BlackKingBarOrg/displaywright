PREFIX  ?= $(HOME)/.local
BIN     := $(PREFIX)/bin/displaywright
DESKTOP := $(HOME)/.local/share/applications/displaywright.desktop
ROOT    := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))

.PHONY: test run install uninstall lint plugin unplugin migrate validate-plugin publish-plugin

test:
	python3 -m unittest discover -t . -s tests

QMLLINT ?= /usr/lib/qt6/bin/qmllint
OMARCHY ?= $(or $(OMARCHY_PATH),/usr/share/omarchy)
QMLROOT := $(CURDIR)/build/qmlroot

lint:
	python3 -m compileall -q displaywright tests
	@# `qs.Commons` and `qs.Ui` are Omarchy's shell root under the alias
	@# Quickshell gives it at runtime; qmllint needs that alias on disk.
	@if [ -d "$(OMARCHY)/shell" ]; then \
	  mkdir -p $(QMLROOT) && ln -sfn $(OMARCHY)/shell $(QMLROOT)/qs; \
	  ARGS="-I /usr/lib/qt6/qml -I $(QMLROOT) -I plugin"; \
	else \
	  echo "omarchy not found, checking syntax only"; ARGS="--bare"; \
	fi; \
	fail=0; \
	for f in plugin/*.qml plugin/renderers/*.qml; do \
	  out=$$($(QMLLINT) $$ARGS "$$f" 2>&1 | grep -E '^Error'); \
	  if [ -n "$$out" ]; then echo "$$f"; echo "$$out"; fail=1; fi; \
	done; \
	[ $$fail -eq 0 ] && echo "qml ok"

run:
	./bin/displaywright

# Install the app only. The renderer is a separate step because it changes
# which plugin owns the desktop background.
install:
	mkdir -p $(dir $(BIN)) $(dir $(DESKTOP))
	ln -sf $(ROOT)/bin/displaywright $(BIN)
	sed 's|^Exec=displaywright$$|Exec=$(BIN)|' data/displaywright.desktop > $(DESKTOP)
	@echo "installed $(BIN)"
	@echo "installed $(DESKTOP)"
	@echo "now run 'make plugin' to let displaywright draw the wallpapers"

uninstall: unplugin
	rm -f $(BIN) $(DESKTOP)
	@echo "removed $(BIN) and $(DESKTOP)"

plugin:
	./bin/displaywright renderer install

unplugin:
	./bin/displaywright renderer uninstall

# Move a wallwright / hyprlayout installation over to displaywright.
migrate:
	./bin/displaywright migrate

# ---------------------------------------------------------------- publishing

# omarchy-plugin-validate mirrors the checks the shell itself runs. It only
# exists on an Omarchy machine; tests/test_plugin_spec.py re-implements the
# same rules so CI catches a broken manifest without one.
validate-plugin:
	omarchy-plugin-validate plugin
	@echo "manifest ok"

# `omarchy plugin add <url>` clones a repo straight into
# ~/.config/omarchy/plugins/<id>/, so manifest.json has to sit at a repository
# *root* -- and ours lives in a subdirectory, next to the preview arithmetic it
# has to stay in step with. Splitting the subtree out on publish gives the
# registry the shape it wants without breaking that pairing. The result is a
# generated mirror: never commit to it directly.
PLUGIN_REMOTE ?= git@github.com:BlackKingBarOrg/displaywright-shell-plugin.git
PLUGIN_BRANCH ?= main

publish-plugin: validate-plugin test
	@git diff --quiet || { echo "working tree is dirty; commit first"; exit 1; }
	git subtree split --prefix=plugin -b plugin-publish
	git push --force $(PLUGIN_REMOTE) plugin-publish:$(PLUGIN_BRANCH)
	git branch -D plugin-publish
	@echo "published plugin/ to $(PLUGIN_REMOTE) ($(PLUGIN_BRANCH))"
