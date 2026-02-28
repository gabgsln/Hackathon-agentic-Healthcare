.PHONY: install dev test lint format clean run dashboard

# --- Setup ---
install:
	pip install -e ".[dev]"

# --- Dev server ---
dev:
	uvicorn src.app.main:app --reload --port 8000

run:
	uvicorn src.app.main:app --port 8000

# --- Dashboard ---
dashboard:
	streamlit run src/viz/dashboard.py

# --- Tests ---
test:
	pytest tests/ -v

test-cov:
	pytest tests/ -v --cov=src --cov-report=html

# --- Lint / Format ---
lint:
	ruff check src/ tests/
	mypy src/

format:
	ruff format src/ tests/
	ruff check --fix src/ tests/

# --- Cleanup ---
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	find . -type d -name "htmlcov" -exec rm -rf {} +
	rm -rf dist/ build/ *.egg-info/

# --- Demo (single DICOM file bundled with pydicom) ---
demo:
	@python -c "import pydicom; import pathlib; p=pathlib.Path(pydicom.__file__).parent/'data'/'test_files'/'CT_small.dcm'; print('DICOM:', p)"
	python -m src.pipelines.run_case \
		--dicom "$$(python -c \"import pydicom, pathlib; print(pathlib.Path(pydicom.__file__).parent/'data'/'test_files'/'CT_small.dcm')\")" \
		--case-id DEMO \
		--out data/processed/DEMO/
