# 🎨 Frontend Development Guide

## 🔒 Backend Integration: LOCKED & STABLE

The Python integration (`custom_components/exaviz/`) is **LOCKED** and should **NOT** be modified:

- ✅ **921 tests passing** - All backend functionality stable
- ✅ **Entity structure locked** - `sensor.exaviz_*` pattern stable
- ✅ **Local board management** - Direct PoE control on Cruiser/Interceptor boards
- ✅ **Zero configuration** - Auto-detects board type and PoE ports
- ✅ **Production ready** - Working on Cruiser board

**Tag**: `v1.0.0-backend-stable` - marks the locked backend state

## ✅ Frontend Cards: ACTIVE DEVELOPMENT

Continue developing and enhancing the frontend cards:

### 🎯 Current Working Cards

1. **ExavizStatusCard** - VMS server status with beautiful dark theming
2. **ExavizCameraStatusCard** - Camera system overview with counts
3. **ExavizGaugeCard** - Animated circular progress indicators
4. **ExavizSystemMetricsCard** - Performance charts and metrics
5. **ExavizPoEPortCard** - Individual PoE port monitoring

### 🚧 Development Templates

1. **ExavizEventsCard** - Event timeline (ready for customization)
2. **ExavizPoEManagementCard** - Full PoE switch management

## 🛠️ Development Workflow

### Setup
```bash
cd lovelace-cards/
npm install
```

### Development Commands
```bash
npm run dev          # Development server with hot reload
npm run build        # Build for production deployment
npm run type-check   # TypeScript validation
npm run test         # Run component tests
npm run lint         # ESLint validation
```

### File Structure
```
lovelace-cards/
├── src/
│   ├── cards/           # 🎨 ACTIVE: Card components
│   │   ├── exaviz-status-card.ts
│   │   ├── exaviz-camera-status-card.ts
│   │   ├── exaviz-gauge-card.ts
│   │   ├── exaviz-system-metrics-card.ts
│   │   ├── exaviz-poe-port-card.ts
│   │   ├── exaviz-events-card.ts      # Template
│   │   └── exaviz-poe-management-card.ts # Template
│   ├── types/           # TypeScript definitions
│   ├── test/            # Test utilities
│   └── index.ts         # Card registration
├── package.json         # Dependencies
├── rollup.config.js     # Build configuration
└── tsconfig.json        # TypeScript config
```

## 🎨 Theming & Design

### Brand Colors
- **Primary**: #90FF80 (Exaviz blue)
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
import { ExavizStatusCard } from '../cards/exaviz-status-card';

describe('ExavizStatusCard', () => {
  it('should render with valid config', () => {
    const card = new ExavizStatusCard();
    const config = { type: 'custom:exaviz-status-card' };
    
    expect(() => card.setConfig(config)).not.toThrow();
  });
});
```

## 🚀 Deployment

### Build & Deploy
```bash
# Build optimized bundle
npm run build

# Copy to Home Assistant
cp dist/exaviz-cards.js ~/homeassistant/www/custom_components/exaviz/www/

# Or deploy to Cruiser board (use deploy script, not manual scp)
# ./scripts/deploy-unified.sh
```

### Development Testing
Use `frontend-development-dashboard.yaml` for testing cards:
```bash
# Copy to HA for testing
cp frontend-development-dashboard.yaml ~/homeassistant/homeassistant-config/
```

## 🎯 Development Goals

### Immediate Goals
- [ ] Complete ExavizEventsCard implementation
- [ ] Build full PoE management interface
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
// Add to any card for debugging
console.log('Card config:', this.config);
console.log('Home Assistant state:', this.hass);
```

## 📋 Backend Integration Reference

### Entity ids
Per port, where `{set}` is `onboard`, `addon_0`, `addon_1`, ... and `{N}` is the port number:
- `switch.{set}_port{N}` - PoE power for the port; the PoE card finds ports by this name
- `sensor.{set}_port{N}_current` - port current
- `binary_sensor.{set}_port{N}_powered`, `binary_sensor.{set}_port{N}_plug` - power and link
- `button.{set}_port{N}_reset` - power-cycle the port

Board-wide: `sensor.board_status` (the PoE card reads it) and `sensor.board_temperature`;
`binary_sensor.zigbee_coordinator` on a Cruiser; `sensor.zigbee_radio` for a board on the network.

The full entity list for each setup the tests cover is in `tests_ha/golden/*.json`.

### Actions
See "Actions" in the top-level `README.md`.

**🚨 DO NOT RENAME**: users' dashboards and automations use these entity ids.

---

**Happy Frontend Development! 🎨**

Keep the cards beautiful, the animations smooth, and the user experience amazing! 