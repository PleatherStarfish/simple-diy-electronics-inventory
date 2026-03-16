VENV ?= .venv
PYTHON := $(VENV)/bin/python
PIP := $(PYTHON) -m pip

.PHONY: install install-dev run test lint clean dmg

install:
	$(PIP) install -e '.[bom-pdf]'

install-dev:
	$(PIP) install -e '.[dev,bom-pdf]'

run:
	$(PYTHON) -m eurorack_inventory

test:
	$(PYTHON) -m pytest

clean:
	rm -rf build dist

dmg: install-dev
	bash scripts/build_macos.sh
