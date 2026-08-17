PREFIX ?= $(HOME)/.local
BIN    := $(PREFIX)/bin/hyprlayout
DESKTOP := $(HOME)/.local/share/applications/hyprlayout.desktop
ROOT   := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))

.PHONY: test run install uninstall lint

test:
	python3 -m unittest discover -t . -s tests

run:
	./bin/hyprlayout

install:
	mkdir -p $(dir $(BIN)) $(dir $(DESKTOP))
	ln -sf $(ROOT)/bin/hyprlayout $(BIN)
	sed 's|^Exec=hyprlayout$$|Exec=$(BIN)|' data/hyprlayout.desktop > $(DESKTOP)
	@echo "installed $(BIN)"
	@echo "installed $(DESKTOP)"

uninstall:
	rm -f $(BIN) $(DESKTOP)
	@echo "removed $(BIN) and $(DESKTOP)"

lint:
	python3 -m compileall -q hyprlayout tests
