#!/usr/bin/env bash
set -euo pipefail

streamlit run streamlit_app.py --server.port "${STREAMLIT_PORT:-8501}"
