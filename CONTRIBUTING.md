# Contributing to Instagram Vault & AI Studio

Thank you for your interest in contributing to **Instagram Vault & AI Studio**! We welcome bug reports, feature requests, documentation improvements, and pull requests.

## Development Workflow

### 1. Prerequisites
- Python 3.10+ (recommended 3.11)
- Node.js 18+ & npm 9+
- Git

### 2. Setting Up Backend
```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start backend dev server (FastAPI on http://127.0.0.1:8000)
python backend_entry.py
```

### 3. Setting Up Desktop Frontend
```bash
cd desktop

# Install dependencies
npm install

# Start Vite + Electron in development mode
npm run dev
```

### 4. Code Guidelines
- **TypeScript**: All frontend code must strictly pass `tsc -p tsconfig.app.json --noEmit`.
- **Translations (i18n)**: All new UI strings must be added to `desktop/src/i18n.tsx` with symmetrical Persian and English translations.
- **Python**: Follow PEP 8 guidelines and write clear docstrings.

### 5. Submitting Pull Requests
1. Fork the repository and create your branch from `main`:
   ```bash
   git checkout -b feature/my-new-feature
   ```
2. Commit your changes using conventional commit messages (`feat: ...`, `fix: ...`, `docs: ...`).
3. Ensure all tests and lint checks pass.
4. Open a Pull Request referencing any open issue.
