// Browser answers for the shell: preferences, teams, sprints, status, save and refresh.

import type { Api } from '../api';
import { refreshMock, saveMock, status } from './data';
import { demo, sprints } from './shared';

const coreMock: Partial<Api> = {
  async Info() {
    return { version: 'dev', os: 'browser', arch: '', dataDir: demo.prefs.dataDir, holidaysVersion: 'mock' };
  },
  async Prefs() {
    return { ...demo.prefs };
  },
  async SetLanguage(code) {
    demo.prefs = { ...demo.prefs, language: code };
  },
  async SetTheme(code) {
    demo.prefs = { ...demo.prefs, theme: code };
  },
  async Texts(lang) {
    // The catalog is bundled only where the mock is the whole program (npm run dev, tests); in
    // the program, texts always come from the core, also while the demo team is shown.
    if (lang !== 'de' || !(import.meta.env.DEV || import.meta.env.MODE === 'mock')) return {};
    // The files of the window texts, one per area (go/internal/i18n/data/de.ui*.json).
    const files = import.meta.glob<{ default: { texts: Record<string, string> } }>('../../../../../i18n/data/de.ui*.json');
    const texts: Record<string, string> = {};
    for (const load of Object.values(files)) Object.assign(texts, (await load()).default.texts);
    return texts;
  },
  async SetDataDir(path) {
    demo.prefs = { ...demo.prefs, dataDir: path };
  },
  async PickDataDir() {
    return '';
  },
  async Teams() {
    return [demo.team];
  },
  async Sprints() {
    return sprints;
  },
  async Status() {
    return status();
  },
  async Save() {
    return saveMock(false);
  },
  async Refresh() {
    return refreshMock();
  },
};

export default coreMock;
