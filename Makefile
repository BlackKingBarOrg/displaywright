PREFIX  ?= $(HOME)/.local
BIN     := $(PREFIX)/bin/displaywright
DESKTOP := $(HOME)/.local/share/applications/displaywright.desktop
ROOT    := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))

.PHONY: test run install uninstall lint plugin unplugin migrate

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
