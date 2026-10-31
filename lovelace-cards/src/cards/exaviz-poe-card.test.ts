/*
 * Copyright (c) 2026 Axzez LLC.
 * Licensed under the MIT License. See LICENSE for details.
 */

import { describe, expect, it } from 'vitest';
import { ExavizPoECard } from './exaviz-poe-card';

type States = Record<string, { state: string; attributes?: Record<string, unknown> }>;

// The card's helpers are private; the tests reach them through this view.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type CardInternals = any;

function makeCard(states: States, config: Record<string, unknown> = {}): CardInternals {
  const card = new ExavizPoECard() as CardInternals;
  card.hass = { states };
  card.setConfig({ type: 'custom:exaviz-poe-card', poe_set: 'onboard', ...config });
  return card;
}

function portStates(set: string, port: number, opts: {
  plugged?: boolean;
  powered?: boolean;
  watts?: string;
  status?: string;
  enabled?: boolean;
  allocated?: number;
} = {}): States {
  const base = `${set}_port${port}`;
  return {
    [`switch.${base}`]: { state: 'on', attributes: { linux_device: `poe${port}` } },
    [`sensor.${base}_current`]: {
      state: opts.watts ?? '0',
      attributes: {
        status: opts.status ?? '',
        enabled: opts.enabled ?? true,
        allocated_power_watts: opts.allocated,
      },
    },
    [`binary_sensor.${base}_powered`]: { state: opts.powered ? 'on' : 'off' },
    [`binary_sensor.${base}_plug`]: { state: opts.plugged ? 'on' : 'off' },
  };
}

describe('getStubConfig', () => {
  it('picks the first poe_set in sorted order', () => {
    const stub = ExavizPoECard.getStubConfig({
      states: { ...portStates('onboard', 0), ...portStates('addon_0', 1) },
    } as never);
    expect(stub).toEqual({ type: 'custom:exaviz-poe-card', poe_set: 'addon_0' });
  });

  it('falls back to addon_0 when there are no PoE switches', () => {
    expect(ExavizPoECard.getStubConfig({ states: {} } as never).poe_set).toBe('addon_0');
  });
});

describe('setConfig', () => {
  it('rejects a missing config', () => {
    expect(() => new ExavizPoECard().setConfig(undefined as never)).toThrow('Invalid configuration');
  });

  it('fills defaults and keeps what the user set', () => {
    const card = makeCard({}, { show_summary: false });
    expect(card.config).toMatchObject({
      poe_set: 'onboard',
      show_header: true,
      layout: 'auto',
      show_details: true,
      show_summary: false,
    });
  });
});

describe('port discovery', () => {
  it('orders ports like the jacks: even ports first, then odd', () => {
    const states: States = {};
    for (const p of [3, 0, 7, 2, 1, 6, 5, 4]) Object.assign(states, portStates('onboard', p));
    const card = makeCard(states);
    card._discoverPorts();
    expect(card._ports.map((p: { port: number }) => p.port)).toEqual([0, 2, 4, 6, 1, 3, 5, 7]);
  });

  it('only picks up ports from the configured poe_set', () => {
    const card = makeCard({ ...portStates('onboard', 0), ...portStates('addon_0', 1) });
    card._discoverPorts();
    expect(card._ports).toHaveLength(1);
    expect(card._ports[0]).toMatchObject({ port: 0, linux_device: 'poe0' });
  });

  it('auto-detects a poe_set with underscores when none is configured', () => {
    const card = makeCard(portStates('addon_1', 2), { poe_set: undefined });
    card._discoverPorts();
    expect(card._ports.map((p: { switchEntity: string }) => p.switchEntity)).toEqual(['switch.addon_1_port2']);
  });
});

describe('port status', () => {
  const statusOf = (opts: Parameters<typeof portStates>[2]) => {
    const card = makeCard(portStates('onboard', 0, opts));
    return card._getPortStatus(card._getPortConfig(0));
  };

  it.each([
    [{ status: 'power on', plugged: true, powered: true }, 'active'],
    [{ status: 'power on', enabled: false }, 'disabled'],
    [{ status: 'disabled', plugged: true, powered: true }, 'disabled'],
    [{ status: 'backoff' }, 'empty'],
    [{ status: 'start detection' }, 'empty'],
    [{ status: 'searching' }, 'empty'],
    [{ plugged: false }, 'empty'],
    [{ plugged: true, powered: true }, 'active'],
    [{ plugged: true, powered: false }, 'inactive'],
  ])('%j -> %s', (opts, expected) => {
    expect(statusOf(opts)).toBe(expected);
  });
});

describe('power display', () => {
  it('shows draw over allocation when the allocation is known', () => {
    const card = makeCard(portStates('onboard', 0, { watts: '6.25', allocated: 15.4 }));
    expect(card._formatPowerDisplay(card._getPortConfig(0))).toBe('6.3W / 15.4W');
  });

  it('shows draw alone without an allocation, and 0W with no sensor', () => {
    const card = makeCard(portStates('onboard', 0, { watts: 'abc' }));
    expect(card._formatPowerDisplay(card._getPortConfig(0))).toBe('0.0W');
    expect(card._formatPowerDisplay({ currentEntity: 'sensor.missing' })).toBe('0W');
  });

  it('sums the set', () => {
    const card = makeCard({
      ...portStates('onboard', 0, { watts: '4.5', status: 'power on' }),
      ...portStates('onboard', 1, { watts: '2', enabled: false }),
    });
    card._discoverPorts();
    expect(card._getPoeSetSummary()).toEqual({
      totalPorts: 2,
      enabledPorts: 1,
      activePorts: 1,
      totalPower: '6.5',
    });
  });
});

describe('card title', () => {
  it('names the board from sensor.board_status', () => {
    const card = makeCard({ 'sensor.board_status': { state: 'ok', attributes: { board_type: 'cruiser' } } });
    expect(card._getDefaultCardTitle()).toBe('Cruiser PoE Management');
  });

  it('falls back to the poe_set name', () => {
    expect(makeCard({}, { poe_set: 'addon_1' })._getDefaultCardTitle()).toBe('Add-on Board 1 PoE');
    expect(makeCard({}, { poe_set: 'addon_2' })._getDefaultCardTitle()).toBe('ADDON 2 PoE Management');
  });
});
