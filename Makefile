.PHONY: install run eval test
install:
	pip install -e ".[dev]"
run:
	python -m agent.cli --csv data/tickets.csv --out logs/run.jsonl
eval:
	python eval/run_eval.py
test:
	pytest -q
