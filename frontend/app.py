"""Streamlit entrypoint for ShopAssistant (E8-S1, E8-S2, E8-S3).

Composes the three frontend stories into one app: a conversational chat tab
(E8-S3, the primary feature) and a browse-and-filter catalog tab combining the
product grid (E8-S1) with the traditional filter controls (E8-S2). All data is
fetched over HTTP via :class:`ApiClient`; this module imports no backend code.

The backend base URL is read from the ``BACKEND_URL`` environment variable so
the same image works in local dev and the Docker stack, defaulting to the dev
backend address.
"""

import os

import streamlit as st
from api_client import DEFAULT_BASE_URL, ApiClient, ApiUnavailableError
from components.catalog_grid import render_catalog_grid
from components.chat import render_chat
from components.filters import render_filter_controls, selection_to_query

_PAGE_TITLE = "ShopAssistant"


def build_client() -> ApiClient:
    """Construct the backend HTTP client from environment configuration."""
    base_url = os.environ.get("BACKEND_URL", DEFAULT_BASE_URL)
    return ApiClient(base_url=base_url)


def render_browse_tab(client: ApiClient) -> None:
    """Render the catalog grid driven by the traditional filter controls."""
    try:
        options = client.get_filters()
    except ApiUnavailableError as error:
        st.error(str(error))
        return
    with st.sidebar:
        selection = render_filter_controls(options)
    query = selection_to_query(selection, options)
    render_catalog_grid(client, query)


def render_chat_tab(client: ApiClient) -> None:
    """Render the conversational assistant (primary feature)."""
    render_chat(client)


def main() -> None:
    """Configure the page and render the chat and browse tabs."""
    st.set_page_config(page_title=_PAGE_TITLE, layout="wide")
    st.title(_PAGE_TITLE)
    client = build_client()
    chat_tab, browse_tab = st.tabs(["Chat", "Browse & Filter"])
    with chat_tab:
        render_chat_tab(client)
    with browse_tab:
        render_browse_tab(client)


if __name__ == "__main__":
    main()
