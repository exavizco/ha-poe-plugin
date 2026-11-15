/*
 * Copyright (c) 2026 Axzez LLC.
 * Licensed under the MIT License. See LICENSE for details.
 */

// Port actions through the rendered card: what a click sends to Home
// Assistant, and that a port's spinner always ends.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ExavizPoECard } from './exaviz-poe-card';

type States = Record<string, { state: string; attributes?: Record<string, unknown> }>;

function portStates(port: number, enabled: boolean): States {
  const base = `onboard_port${port}`;
  return {
    [`switch.${base}`]: { state: enabled ? 'on' : 'off', attributes: { linux_device: `poe${port}` } },
    [`sensor.${base}_current`]: {
      state: enabled ? '4.0' : '0',
      attributes: { status: enabled ? 'power on' : 'disabled', enabled },
    },
    [`binary_sensor.${base}_powered`]: { state: enabled ? 'on' : 'off' },
    [`binary_sensor.${base}_plug`]: { state: 'on' },
    [`button.${base}_reset`]: { state: 'unknown' },
  };
}

// Port 0 is enabled, port 1 is disabled.
const STATES: States = { ...portStates(0, true), ...portStates(1, false) };

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Card = any;

async function mount(callService: ReturnType<typeof vi.fn>): Promise<Card> {
  const card = new ExavizPoECard() as Card;
  card.setConfig({ type: 'custom:exaviz-poe-card', poe_set: 'onboard' });
  card.hass = { states: STATES, callService };
  document.body.appendChild(card);
  // Ports are discovered in firstUpdated, which can ask for one more render.
  while (!(await card.updateComplete));
  return card;
}

function portEl(card: Card, port: number): HTMLElement {
  const el = [...card.shadowRoot.querySelectorAll('.poe-port')].find(
    (e: Element) => e.querySelector('.port-number')?.textContent === `P${port}`,
  );
  if (!el) throw new Error(`port ${port} not rendered`);
  return el as HTMLElement;
}

async function click(card: Card, port: number, type: 'click' | 'contextmenu' = 'click'): Promise<Event> {
  const event = new MouseEvent(type, { bubbles: true, cancelable: true, composed: true });
  portEl(card, port).dispatchEvent(event);
  await card.updateComplete;
  return event;
}

// HA hands the card a new hass object on every state change.
function setSwitch(card: Card, port: number, state: string): void {
  card.hass = {
    ...card.hass,
    states: { ...card.hass.states, [`switch.onboard_port${port}`]: { state } },
  };
}

// Fake timers in every test, run out at the end, so no toggle's 10 s wait
// outlives its test.
beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(async () => {
  await vi.runAllTimersAsync();
  document.body.innerHTML = '';
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('port click', () => {
  it.each([
    [0, 'turn_off'],
    [1, 'turn_on'],
  ])('port %i: the first click only selects, the second sends switch.%s', async (port, service) => {
    const callService = vi.fn().mockResolvedValue(undefined);
    const card = await mount(callService);

    await click(card, port);
    expect(portEl(card, port).classList).toContain('selected');
    expect(callService).not.toHaveBeenCalled();

    await click(card, port);
    expect(callService).toHaveBeenCalledTimes(1);
    expect(callService).toHaveBeenCalledWith('switch', service, {
      entity_id: `switch.onboard_port${port}`,
    });
  });

  it('with one port selected, a click on another port only selects that one', async () => {
    const callService = vi.fn().mockResolvedValue(undefined);
    const card = await mount(callService);

    await click(card, 0);
    await click(card, 1);

    expect(callService).not.toHaveBeenCalled();
    expect(portEl(card, 1).classList).toContain('selected');
    expect(portEl(card, 0).classList).not.toContain('selected');
  });

  it('a right-click presses that port reset button and never switches it', async () => {
    const callService = vi.fn().mockResolvedValue(undefined);
    const card = await mount(callService);

    const event = await click(card, 0, 'contextmenu');

    expect(event.defaultPrevented).toBe(true); // no browser menu
    expect(callService).toHaveBeenCalledTimes(1);
    expect(callService).toHaveBeenCalledWith('button', 'press', {
      entity_id: 'button.onboard_port0_reset',
    });
  });

  it('a refused reset is logged, not thrown', async () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    const card = await mount(vi.fn().mockRejectedValue(new Error('refused')));

    await click(card, 0, 'contextmenu');
    await vi.waitFor(() => expect(error).toHaveBeenCalledWith('Error resetting port:', expect.any(Error)));
  });
});

describe('port spinner', () => {
  it('ends when Home Assistant refuses the switch call', async () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    const card = await mount(vi.fn().mockRejectedValue(new Error('unavailable')));

    await click(card, 0);
    await click(card, 0);

    await vi.waitFor(() => expect(error).toHaveBeenCalledWith('Error toggling port:', expect.any(Error)));
    await card.updateComplete;
    expect(portEl(card, 0).classList).not.toContain('loading');
    expect(portEl(card, 0).querySelector('.spinner')).toBeNull();
  });

  it('stays until the switch reports the new state', async () => {
    const card = await mount(vi.fn().mockResolvedValue(undefined));

    await click(card, 0);
    await click(card, 0);
    expect(portEl(card, 0).querySelector('.spinner')).not.toBeNull();
    expect(portEl(card, 1).querySelector('.spinner')).toBeNull();

    await vi.advanceTimersByTimeAsync(1000);
    await card.updateComplete;
    expect(portEl(card, 0).querySelector('.spinner')).not.toBeNull();

    setSwitch(card, 0, 'off');
    await vi.advanceTimersByTimeAsync(200);
    await card.updateComplete;
    expect(portEl(card, 0).querySelector('.spinner')).toBeNull();
  });

  it('gives up after 10 s when the switch never changes', async () => {
    const card = await mount(vi.fn().mockResolvedValue(undefined));

    await click(card, 0);
    await click(card, 0);

    await vi.advanceTimersByTimeAsync(9800);
    await card.updateComplete;
    expect(portEl(card, 0).classList).toContain('loading');

    await vi.advanceTimersByTimeAsync(200);
    await card.updateComplete;
    expect(portEl(card, 0).classList).not.toContain('loading');
  });
});
