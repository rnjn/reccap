test:
	python3 -m unittest discover -s tests -t .

lint:
	python3 -m compileall -q reccap tests utils
	uvx ruff check reccap tests utils

.PHONY: test lint
