import { describe, expect, it } from 'vitest';
import { dayPlaceholder, formatDayInput, parseDayInput } from './format';

describe('day input in the form of the language', () => {
  // The window starts in English; the order of an en-US day is month first.
  it('reads and writes a day in the order of the language', () => {
    const typed = formatDayInput('2026-10-20');
    expect(parseDayInput(typed)).toBe('2026-10-20');
    expect(parseDayInput('2026-10-20')).toBe('2026-10-20');
  });
  it('refuses what is no day', () => {
    expect(parseDayInput('')).toBe('');
    expect(parseDayInput('31.02.2026')).toBe('');
    expect(parseDayInput('20.10.26')).toBe('');
    expect(parseDayInput('hallo')).toBe('');
  });
  it('shows the format as a hint', () => {
    expect(dayPlaceholder({ day: 'DD', month: 'MM', year: 'YYYY' })).toMatch(/^(DD|MM|YYYY)[./-](DD|MM|YYYY)[./-](DD|MM|YYYY)$/);
  });
});
