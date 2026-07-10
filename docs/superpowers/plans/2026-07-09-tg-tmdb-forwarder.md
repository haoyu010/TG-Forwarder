# TG TMDB Forwarder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Dockerized Telegram user-account forwarding service with TMDB classification, blacklist filtering, TMDB ids in forwarded headers, and a polished React dashboard.

**Architecture:** FastAPI serves JSON APIs and built dashboard assets. A Telethon worker listens to configured source channels, enriches messages through TMDB, applies rules, forwards approved posts, and records decisions in SQLite. React/Vite provides an operational dashboard for status, records, channel/filter settings, preview, and logs.

**Tech Stack:** Python 3.12, FastAPI, Telethon, httpx, aiosqlite, PyYAML, pytest, React, Vite, TypeScript, Lucide React, Docker Compose.

---

### Task 1: Backend Core Models And Rules

**Files:**
- Create: `app/models.py`
- Create: `app/rules.py`
- Test: `tests/test_rules.py`

- [ ] Write failing tests for title extraction, blacklist filtering, and header rendering.
- [ ] Run `python -m pytest tests/test_rules.py -v` and confirm missing module failures.
- [ ] Implement dataclasses and pure rule functions.
- [ ] Run `python -m pytest tests/test_rules.py -v` and confirm all tests pass.

### Task 2: Configuration And Database

**Files:**
- Create: `app/config.py`
- Create: `app/storage.py`
- Test: `tests/test_config_storage.py`
- Create: `config.example.yaml`

- [ ] Write failing tests for YAML config loading and SQLite event persistence.
- [ ] Run `python -m pytest tests/test_config_storage.py -v` and confirm failures.
- [ ] Implement config loading, defaults, and SQLite repository.
- [ ] Run `python -m pytest tests/test_config_storage.py -v` and confirm all tests pass.

### Task 3: TMDB Client And API

**Files:**
- Create: `app/tmdb.py`
- Create: `app/api.py`
- Create: `app/main.py`
- Test: `tests/test_tmdb_api.py`

- [ ] Write failing tests for TMDB result parsing and dashboard API status/records responses.
- [ ] Run `python -m pytest tests/test_tmdb_api.py -v` and confirm failures.
- [ ] Implement TMDB client parsing and FastAPI app factory.
- [ ] Run `python -m pytest tests/test_tmdb_api.py -v` and confirm all tests pass.

### Task 4: Telegram Worker

**Files:**
- Create: `app/telegram_worker.py`
- Test: `tests/test_worker.py`

- [ ] Write failing tests for processing one message through extractor, TMDB lookup, rules, storage, and sender abstraction.
- [ ] Run `python -m pytest tests/test_worker.py -v` and confirm failures.
- [ ] Implement worker pipeline with injectable Telegram/TMDB dependencies.
- [ ] Run `python -m pytest tests/test_worker.py -v` and confirm all tests pass.

### Task 5: Dashboard Frontend

**Files:**
- Create: `web/package.json`
- Create: `web/index.html`
- Create: `web/src/main.tsx`
- Create: `web/src/App.tsx`
- Create: `web/src/styles.css`
- Create: `web/tsconfig.json`
- Create: `web/vite.config.ts`

- [ ] Create React/Vite dashboard with overview, records, channels, filters, preview, and logs sections.
- [ ] Use Lucide icons, accessible labels, visible focus states, responsive tables, and restrained product UI styling.
- [ ] Run `npm --prefix web install`.
- [ ] Run `npm --prefix web run build` and confirm success.

### Task 6: Docker And Documentation

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `requirements.txt`
- Create: `README.md`

- [ ] Add backend and frontend build pipeline to Dockerfile.
- [ ] Add Compose service with persistent data volume and dashboard port.
- [ ] Document Telegram login, TMDB token, config, dashboard, and operational notes.
- [ ] Run backend tests, frontend build, and Docker build verification.
