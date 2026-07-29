SELF_TEST_SRCS := export_gemini_cookie.py gemini_cookie_watchdog.py
UNIT_TESTS := tests.test_gemini_export

.PHONY: self-test unit-test test lint format

self-test:
	python3 export_gemini_cookie.py --self-test
	python3 gemini_cookie_watchdog.py --self-test

unit-test:
	python3 -m unittest $(UNIT_TESTS) -v

test: self-test unit-test

lint:
	python3 -m py_compile $(SELF_TEST_SRCS) gemini_export/_common.py tests/test_gemini_export.py

format:
	python3 -m pip install -q black
	black export_gemini_cookie.py gemini_cookie_watchdog.py gemini_export/_common.py tests/test_gemini_export.py

HEADROOM_DIR ?= /root/headroom
HEADROOM_VENV := .venv-headroom
UV_CACHE_DIR ?= /tmp/uv-cache
UV_PYTHON_INSTALL_DIR ?= /tmp/uv-python

.PHONY: headroom-install headroom

headroom-install:
	@if [ ! -d "$(HEADROOM_DIR)" ]; then \
		echo "Missing headroom checkout at HEADROOM_DIR=$(HEADROOM_DIR)" >&2; \
		exit 1; \
	fi
	UV_CACHE_DIR="$(UV_CACHE_DIR)" UV_PYTHON_INSTALL_DIR="$(UV_PYTHON_INSTALL_DIR)" uv venv "$(HEADROOM_VENV)" >/dev/null
	@if HEADROOM_VENV="$(HEADROOM_VENV)" ./scripts/headroom --help >/dev/null 2>&1; then \
		:; \
	else \
		UV_CACHE_DIR="$(UV_CACHE_DIR)" UV_PYTHON_INSTALL_DIR="$(UV_PYTHON_INSTALL_DIR)" uv pip install --python "$(HEADROOM_VENV)/bin/python" -e "$(HEADROOM_DIR)[all]"; \
	fi
	@HEADROOM_VENV="$(HEADROOM_VENV)" ./scripts/headroom --help >/dev/null 2>&1 || \
		(echo 'headroom install failed: provide network or offline wheels' >&2; exit 1)

headroom:
	@if HEADROOM_VENV="$(HEADROOM_VENV)" ./scripts/headroom --help >/dev/null 2>&1; then \
		exit 0; \
	fi
	@echo 'headroom is not installed in $(HEADROOM_VENV)' >&2
	@echo 'Run `make headroom-install` after preparing network access or offline wheels.' >&2
	@exit 1
