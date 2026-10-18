# SPDX-License-Identifier: EUPL-1.2
"""Einstieg der Weboberfläche (Streamlit). Start: `sprintforecast web`."""

from functools import partial

import streamlit as st

from sprintforecast.i18n import t
from sprintforecast.idle import start_idle_watch
from sprintforecast.plugins import web_pages
from sprintforecast.web.ui import (
    PAGES,
    apply_language,
    collect_sync_result,
    enabled_pages,
    page_path,
    repository,
    run_plugin_page,
    sidebar,
    sidebar_footer,
    stichtag_problem,
)

st.set_page_config(page_title="Sprint-Forecast", page_icon="📈", layout="wide")
start_idle_watch()
apply_language()
if problem := stichtag_problem():
    st.error(problem)  # vor allem Weiteren: Die Seitenleiste liest den Stichtag in jedem Lauf
    st.stop()
collect_sync_result()  # ein Abgleich eines gestoppten Durchlaufs: abwarten, Ergebnis übernehmen
repo = repository()
sidebar(repo)  # vor der Navigation: Die Teamwahl bestimmt, welche Seiten es gibt
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
    pages.setdefault(plugin_page.group, []).append(
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
