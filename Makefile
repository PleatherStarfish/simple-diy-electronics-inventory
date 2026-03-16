VENV ?= .venv
PYTHON := $(VENV)/bin/python
PIP := $(PYTHON) -m pip

.PHONY: install install-dev run test lint clean dmg release

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

release:
ifndef VERSION
	$(error Usage: make release VERSION=0.2.1)
endif
	@echo "==> Bumping version to $(VERSION)"
	sed -i '' 's/^version = ".*"/version = "$(VERSION)"/' pyproject.toml
	sed -i '' 's/^__version__ = ".*"/__version__ = "$(VERSION)"/' src/eurorack_inventory/__init__.py
	sed -i '' "s/'CFBundleShortVersionString': '.*'/'CFBundleShortVersionString': '$(VERSION)'/" EurorackInventory.spec
	@echo "==> Committing and tagging v$(VERSION)"
	git add pyproject.toml src/eurorack_inventory/__init__.py EurorackInventory.spec
	git commit -m "Bump version to $(VERSION)"
	git tag "v$(VERSION)"
	@echo "==> Pushing to origin"
	git push origin main "v$(VERSION)"
	@echo "==> Done — release workflow will build and publish the DMG"
