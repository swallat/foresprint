# SPDX-License-Identifier: EUPL-1.2
"""Entry point of the web UI (Streamlit). Start: `sprintforecast web`."""

from functools import partial

import streamlit as st

from sprintforecast.i18n import t
from sprintforecast.icon import png as logo_png
from sprintforecast.idle import start_idle_watch
from sprintforecast.plugins import web_pages
from sprintforecast.web.ui import (
    PAGES,
    apply_language,
    apply_theme,
    as_of_problem,
    collect_sync_result,
    enabled_pages,
    page_path,
    repository,
    run_plugin_page,
    sidebar,
    sidebar_footer,
)

st.set_page_config(page_title="Sprint-Forecast", page_icon=logo_png(64), layout="wide")
start_idle_watch()
apply_language()
apply_theme()
if problem := as_of_problem():
    st.error(problem)  # before anything else: the sidebar reads the reference date on every run
    st.stop()
collect_sync_result()  # a sync from a stopped run: wait for it and take over the result
repo = repository()
sidebar(repo)  # before the navigation: the team choice determines which pages exist
enabled = enabled_pages(repo)
st.session_state["enabled-pages"] = enabled
pages = {
    t(group): [
        st.Page(page_path(key), title=t(title), icon=icon, default=key == "start")
        for key, (title, icon) in entries.items()
        if key in enabled
    ]
    for group, entries in PAGES.items()
}
pages = {group: entries for group, entries in pages.items() if entries}
for plugin_page in web_pages():
    pages.setdefault(t(plugin_page.group), []).append(
        st.Page(
            partial(run_plugin_page, plugin_page),
            title=plugin_page.title,
            icon=plugin_page.icon,
            url_path=plugin_page.key,
        )
    )
navigation = st.navigation(pages)
footer = st.sidebar.container()
navigation.run()
with footer:
    sidebar_footer(repo)
