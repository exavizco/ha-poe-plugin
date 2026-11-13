/*
 * Copyright (c) 2026 Axzez LLC.
 * Licensed under the MIT License. See LICENSE for details.
 */

import { describe, expect, it, vi } from 'vitest';

// The card file can load twice in one page, for example when a resource
// with an old ?v= query is still listed next to the new one.
describe('card registration', () => {
  it('loads a second time without error and lists the card once', async () => {
    await import('./exaviz-poe-card');
    const first = customElements.get('exaviz-poe-card');
    expect(first).toBeDefined();

    vi.resetModules();
    await expect(import('./exaviz-poe-card')).resolves.toBeDefined();

    expect(customElements.get('exaviz-poe-card')).toBe(first);
    expect(
      window.customCards.filter((card) => card.type === 'exaviz-poe-card'),
    ).toHaveLength(1);
  });
});
