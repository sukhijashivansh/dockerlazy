PLUGIN_DIR = $(if $(DOCKER_CONFIG),$(DOCKER_CONFIG),$(HOME)/.docker)/cli-plugins
VERSION := $(shell ./docker-lazy lazy --version | cut -d' ' -f3)
ARCHIVE = dist/docker-lazy-$(VERSION).tar.gz

.PHONY: install test release
install:
	mkdir -p "$(PLUGIN_DIR)"
	install -m 755 docker-lazy "$(PLUGIN_DIR)/docker-lazy"

test:
	python3 -B -m unittest discover -s tests

release: test
	mkdir -p dist
	COPYFILE_DISABLE=1 tar -czf "$(ARCHIVE)" docker-lazy Makefile README.md tests/test_cli.py
	cd dist && shasum -a 256 "docker-lazy-$(VERSION).tar.gz" > "docker-lazy-$(VERSION).tar.gz.sha256"
