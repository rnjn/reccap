test:
	python3 -m unittest discover -s tests -t .

lint:
	python3 -m compileall -q reccap tests
	uvx ruff check reccap tests

.PHONY: test lint
