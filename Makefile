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

# --- Sample run ---
demo:
	@echo "Running demo report generation..."
	python -m src.agents.orchestrator --sample data/samples/patient_001.xlsx
