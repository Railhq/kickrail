.PHONY: setup backend web test check

setup:
	cd backend && python3.13 -m venv .venv && .venv/bin/pip install -q -r requirements.txt -r requirements-dev.txt
	cd web && npm install
	@test -f backend/.env || (cp backend/.env.example backend/.env && echo "created backend/.env: fill in KR_APP_SECRET and KR_INTERNAL_TOKEN")
	@test -f web/.env.local || (cp web/.env.example web/.env.local && echo "created web/.env.local: set INTERNAL_TOKEN to match backend")

backend:
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

web:
	cd web && npm run dev

test:
	cd backend && .venv/bin/pytest -q

check: test
	cd web && npm run typecheck && npm run lint
