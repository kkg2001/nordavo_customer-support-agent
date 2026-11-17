.PHONY: install run eval test
install:
	py -m pip install -e ".[dev]"
run:
	py -m agent.helpdesk_cli
eval:
	py -m agent.helpdesk_cli --eval-examples
test:
	py -m pytest -q
