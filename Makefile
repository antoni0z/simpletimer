PYTHON ?= python3
BUMP ?= patch

.DEFAULT_GOAL := help

.PHONY: help run test build version check-clean publish publish-patch publish-minor publish-major

help:
	@printf "Commands:\n"
	@printf "  make run                  Run the app\n"
	@printf "  make test                 Run unit tests\n"
	@printf "  make build                Build the macOS app bundle\n"
	@printf "  make version              Print the current version\n"
	@printf "  make publish BUMP=patch   Bump patch/minor/major, tag, and push\n"

run:
	$(PYTHON) timer.py

test:
	$(PYTHON) -m unittest discover -s tests

build:
	$(PYTHON) -m PyInstaller --clean --noconfirm deep_work_timer.spec

version:
	@$(PYTHON) -c "from version import __version__; print(__version__)"

check-clean:
	@test -z "$$(git status --porcelain)" || (printf "Working tree must be clean before publishing.\n"; exit 1)

publish: check-clean test
	@set -e; \
	new_version="$$($(PYTHON) scripts/bump_version.py --dry-run $(BUMP))"; \
	if git rev-parse -q --verify "refs/tags/v$$new_version" >/dev/null; then \
		printf "Tag v%s already exists.\n" "$$new_version"; \
		exit 1; \
	fi; \
	$(PYTHON) scripts/bump_version.py $(BUMP) >/dev/null; \
	git add version.py; \
	git commit -m "chore: release v$$new_version"; \
	git tag "v$$new_version"; \
	git push origin HEAD; \
	git push origin "v$$new_version"; \
	printf "Published v%s. GitHub Actions will attach the downloadable app to the release.\n" "$$new_version"

publish-patch:
	$(MAKE) publish BUMP=patch

publish-minor:
	$(MAKE) publish BUMP=minor

publish-major:
	$(MAKE) publish BUMP=major
