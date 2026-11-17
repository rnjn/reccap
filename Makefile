test:
	python3 -m unittest discover -s tests -t .

lint:
	python3 -m compileall -q worklog tests
	uvx ruff check worklog tests

.PHONY: test lint
