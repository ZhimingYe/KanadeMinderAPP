# KanadeMinder macOS build pipeline
# Usage:
#   make all       — full pipeline: icon + build + dmg
#   make icon      — generate assets/icon.icns
#   make build     — build dist/KanadeMinder.app
#   make dmg       — package dist/KanadeMinder-0.1.0.dmg
#   make install   — copy .app to /Applications
#   make clean     — remove build artifacts

VERSION := 0.3.5
APP_NAME := KanadeMinder
DIST_DIR := dist
BUILD_DIR := build
SPEC_FILE := KanadeMinder.spec
APP_PATH  := $(DIST_DIR)/$(APP_NAME).app
DMG_PATH  := $(DIST_DIR)/$(APP_NAME)-$(VERSION).dmg
ICON_PATH := assets/icon.icns

.PHONY: all icon build dmg install clean

all: icon build dmg

icon:
	@echo "→ Generating icon..."
	@mkdir -p assets
	uv run --with pillow python scripts/make_icon.py
	@echo "✓ Icon created: $(ICON_PATH)"

build: $(ICON_PATH)
	@echo "→ Building $(APP_NAME).app..."
	uv run --with pyinstaller pyinstaller --noconfirm $(SPEC_FILE)
	@echo "✓ App bundle: $(APP_PATH)"

dmg: $(APP_PATH)
	@echo "→ Creating DMG..."
	bash scripts/make_dmg.sh "$(APP_NAME)" "$(VERSION)" "$(APP_PATH)" "$(DMG_PATH)"
	@echo "✓ DMG created: $(DMG_PATH)"

install: $(APP_PATH)
	@echo "→ Installing to /Applications..."
	cp -r "$(APP_PATH)" /Applications/
	@echo "✓ Installed: /Applications/$(APP_NAME).app"

clean:
	@echo "→ Cleaning build artifacts..."
	rm -rf "$(BUILD_DIR)" "$(DIST_DIR)" assets/*.iconset
	@echo "✓ Clean complete"
