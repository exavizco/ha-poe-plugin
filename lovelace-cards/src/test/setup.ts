/*
 * Copyright (c) 2026 Axzez LLC.
 * Licensed under MIT with Commons Clause. See LICENSE for details.
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

// Mock entity for PoE port testing
export const createMockPoEEntity = (overrides = {}) => ({
  entity_id: 'sensor.exaviz_poe_port_1',
  state: 'active',
  attributes: {
    port_number: 1,
    status: 'active',
    enabled: true,
    power_consumption_watts: 12.5,
    voltage_volts: 48.0,
    current_milliamps: 260,
    connected_device: {
      name: 'Test Camera',
      device_type: 'IP Camera',
      ip_address: '192.168.1.100',
      mac_address: '00:11:22:33:44:55',
      manufacturer: 'Test Corp',
      power_class: 'Class 0 - 15.4W',
    },
    ...overrides,
  },
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