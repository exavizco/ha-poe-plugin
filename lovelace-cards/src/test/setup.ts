/*
 * Copyright (c) 2026 Axzez LLC.
 * Licensed under the MIT License. See LICENSE for details.
 */

import { vi } from 'vitest';

// Simple mock Home Assistant object for testing
export const createMockHass = () => ({
  states: {},
  callService: vi.fn(),
  callWS: vi.fn(),
  localize: vi.fn((key: string) => key),
  connected: true,
  language: 'en',
});

// Setup DOM environment for Lit Element testing
if (typeof window !== 'undefined') {
  // Basic Web Components support for testing
  if (!window.customElements) {
    (window as any).customElements = {
      define: vi.fn(),
      get: vi.fn(),
      whenDefined: vi.fn(() => Promise.resolve()),
    };
  }
} 