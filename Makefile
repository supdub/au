PYTHON ?= python3

.PHONY: run test dist install-local

run:
	$(PYTHON) -m agent_usage_cli --pretty

test:
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py'

dist:
	$(PYTHON) scripts/build_zipapp.py

install-local:
	./install.sh --from-local
