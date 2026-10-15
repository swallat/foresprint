# SPDX-License-Identifier: EUPL-1.2
"""Einstieg der Weboberfläche (Streamlit). Start: `sprintforecast web`."""

from functools import partial

import streamlit as st

from sprintforecast.plugins import web_pages
from sprintforecast.web.ui import (
    PAGES,
    page_path,
    repository,
    run_plugin_page,
    sidebar,
    sidebar_footer,
)

st.set_page_config(page_title="Sprint-Forecast", page_icon="📈", layout="wide")
pages = {
    group: [
        st.Page(page_path(key), title=title, icon=icon, default=key == "forecast")
        for key, (title, icon) in entries.items()
    ]
    for group, entries in PAGES.items()
}
for plugin_page in web_pages():
    pages.setdefault(plugin_page.group, []).append(
        st.Page(
            partial(run_plugin_page, plugin_page),
            title=plugin_page.title,
            icon=plugin_page.icon,
            url_path=plugin_page.key,
        )
    )
navigation = st.navigation(pages)
repo = repository()
sidebar(repo)
footer = st.sidebar.container()
navigation.run()
with footer:
    sidebar_footer(repo)
