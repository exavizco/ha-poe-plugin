# 🎨 Frontend Development Guide

## ✅ Frontend Cards: ACTIVE DEVELOPMENT

Continue developing and enhancing the frontend cards:

### 🎯 Current Card

The bundle registers one card, **ExavizPoECard** (`custom:exaviz-poe-card`, source
`src/cards/exaviz-poe-card.ts`): the PoE port grid, port detail panel, power toggle and reset.

## 🛠️ Development Workflow

### Setup
```bash
cd lovelace-cards/
npm install
```

### Development Commands
```bash
npm run dev          # Rebuild the bundle on every change (no server)
npm run build        # Build for production deployment
npm run type-check   # TypeScript validation
npm run test         # Run component tests
npm run lint         # ESLint validation
```

### File Structure
```
lovelace-cards/
├── src/
│   ├── cards/           # 🎨 ACTIVE: the PoE card and its tests
│   │   ├── exaviz-poe-card.ts
│   │   └── exaviz-poe-card*.test.ts   # Vitest tests
│   ├── assets/images/   # Logos, copied next to the bundle at build time
│   ├── types/           # TypeScript definitions (homeassistant.ts)
│   ├── test/            # Test setup and fixtures
│   └── index.ts         # Card registration
├── package.json         # Dependencies
├── rollup.config.js     # Build configuration
└── tsconfig.json        # TypeScript config
```

## 🎨 Theming & Design

### Brand Colors
- **Primary**: #90FF80 (Exaviz green)
- **Success**: #4CAF50 (green)
- **Warning**: #FF9800 (orange)
- **Error**: #F44336 (red)

### Design Principles
- **Dark theme first** - Primary focus on dark UI
- **Smooth animations** - CSS transitions and transforms
- **Responsive design** - Mobile-friendly layouts
- **Consistent spacing** - 8px grid system
- **Material Design icons** - `mdi:` icon set

### Example Card Styling
```css
:host {
  display: block;
}

.card-content {
  padding: 16px;
  background: var(--ha-card-background, #1f1f1f);
  color: var(--primary-text-color);
}

.metric-value {
  color: var(--accent-color, #90FF80);
  font-weight: bold;
  transition: all 0.3s ease;
}
```

## 🧪 Testing

### Component Testing
- Uses **Vitest** for fast unit testing
- **Mock Home Assistant** objects in `src/test/setup.ts`
- Test card configuration, rendering, and interactions

### Test Examples
```typescript
import { describe, it, expect } from 'vitest';
import './exaviz-poe-card';

describe('exaviz-poe-card', () => {
  it('accepts a valid config', () => {
    const card = document.createElement('exaviz-poe-card') as any;

    expect(() => card.setConfig({ type: 'custom:exaviz-poe-card' })).not.toThrow();
  });
});
```

## 🚀 Deployment

### Build & Deploy
```bash
# Build the bundle into custom_components/exaviz/www/exaviz-cards.js
npm run build
```

Commit the rebuilt bundle with the source change. The integration serves it and, when
dashboards use storage mode (the default), registers it as a Lovelace resource. In YAML mode
it logs a message (level info) asking you to add the resource by hand.

## 🎯 Development Goals

### Immediate Goals
- [ ] Add more animation effects
- [ ] Enhance mobile responsiveness

### Future Enhancements
- [ ] Card configuration UI
- [ ] Theme customization options
- [ ] Interactive chart controls
- [ ] Real-time data updates
- [ ] Card size optimization

## 🔧 Troubleshooting

### Common Issues

1. **TypeScript Errors**:
   ```bash
   npm run type-check
   ```

2. **Import Issues**:
   - Use `import type` for type-only imports
   - Check `src/types/homeassistant.ts` for HA types

3. **Card Not Showing**:
   - Verify card is imported in `src/index.ts`
   - Check browser console for errors
   - Ensure entity exists in Home Assistant

### Debug Mode
```typescript
// Temporary debugging only: lint warns on console.log (no-console)
console.log('Card config:', this.config);
console.log('Home Assistant state:', this.hass);
```

## 📋 Backend Integration Reference

### Entity ids
Per port, where `{set}` is `onboard`, `addon_0`, `addon_1`, ... and `{N}` is the port number (from 0):
- `switch.{set}_port{N}` - PoE power for the port; the PoE card finds ports by this name
- `sensor.{set}_port{N}_current` - power draw in W (the id says current; the milliamps are
  the `current_milliamps` attribute)
- `binary_sensor.{set}_port{N}_powered`, `binary_sensor.{set}_port{N}_plug` - power drawn, and something
  plugged in
- `button.{set}_port{N}_reset` - power-cycle the port

Board-wide: `sensor.board_status` (the PoE card reads it) and `sensor.board_temperature`;
`binary_sensor.zigbee_coordinator` on a Cruiser; `sensor.zigbee_radio` only for a board paired over the network
(Home Assistant on another computer), not for a board running Home Assistant itself.

The full entity list for each setup the tests cover is in `tests_ha/golden/*.json`.

### Actions
See "Actions" in the top-level `README.md`.

**🚨 DO NOT RENAME**: users' dashboards and automations use these entity ids.

---

**Happy Frontend Development! 🎨**

Keep the cards beautiful, the animations smooth, and the user experience amazing! 