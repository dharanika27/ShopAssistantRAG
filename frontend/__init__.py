"""Streamlit frontend application (E8 — Frontend).

Talks to the FastAPI backend only over HTTP (see ``api_client``); it never
imports backend Python modules, per the one-way import rule in
``specs/design/folder-structure.md``.
"""
