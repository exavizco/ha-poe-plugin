import { EXAVIZ_ICON_MAP } from '../types/exaviz-card-config';

export class ExavizIconManager {
  private fontAwesomeLoaded = false;
  private fontAwesomeURL = 'https://axzez-build.nyc3.digitaloceanspaces.com/fonts/fontawesome-pro-6.7.2-web/css/all.min.css';

  constructor(
    private enableProIcons: boolean = false,
    private fallbackToMdi: boolean = true
  ) {}

  /**
   * Load Font Awesome Pro from Axzez CDN
   */
  async loadFontAwesome(): Promise<boolean> {
    if (this.fontAwesomeLoaded) return true;

    try {
      // Check if already loaded
      if (document.querySelector('#exaviz-fontawesome')) {
        this.fontAwesomeLoaded = true;
        return true;
      }

      // Create and load stylesheet
      const link = document.createElement('link');
      link.id = 'exaviz-fontawesome';
      link.rel = 'stylesheet';
      link.href = this.fontAwesomeURL;
      link.crossOrigin = 'anonymous';

      const loadPromise = new Promise<boolean>((resolve) => {
        link.onload = () => {
          this.fontAwesomeLoaded = true;
          resolve(true);
        };
        link.onerror = () => {
          console.warn('Failed to load Font Awesome Pro from Axzez CDN');
          resolve(false);
        };
      });

      document.head.appendChild(link);
      return await loadPromise;
    } catch (error) {
      console.error('Error loading Font Awesome Pro:', error);
      return false;
    }
  }

  /**
   * Get appropriate icon for feature with fallback strategy
   */
  getIcon(iconKey: string): string {
    const iconDef = EXAVIZ_ICON_MAP[iconKey as keyof typeof EXAVIZ_ICON_MAP];

    // Simple MDI icon
    if (typeof iconDef === 'string') {
      return iconDef;
    }

    // Complex icon with pro/fallback options
    if (typeof iconDef === 'object' && iconDef !== null) {
      // Use Font Awesome Pro if enabled and loaded
      if (this.enableProIcons && this.fontAwesomeLoaded && iconDef.pro) {
        return iconDef.pro;
      }

      // Fallback to MDI
      if (this.fallbackToMdi && iconDef.fallback) {
        return iconDef.fallback;
      }
    }

    // Default fallback
    console.warn(`Unknown icon key: ${iconKey}, using default`);
    return 'mdi:help-circle';
  }

  /**
   * Render icon HTML based on type
   */
  renderIcon(iconKey: string): string {
    const iconString = this.getIcon(iconKey);

    // Font Awesome icon
    if (iconString.startsWith('fa')) {
      return `<i class="${iconString}"></i>`;
    }

    // MDI icon (Home Assistant standard)
    return `<ha-icon icon="${iconString}"></ha-icon>`;
  }

  /**
   * Check if feature requires Font Awesome Pro
   */
  isProFeature(iconKey: string): boolean {
    const iconDef = EXAVIZ_ICON_MAP[iconKey as keyof typeof EXAVIZ_ICON_MAP];
    return typeof iconDef === 'object' && iconDef !== null && 'pro' in iconDef;
  }

  /**
   * Get all required Font Awesome classes for subset loading
   */
  getRequiredFAClasses(features: string[]): string[] {
    return features
      .map(feature => {
        const iconDef = EXAVIZ_ICON_MAP[feature as keyof typeof EXAVIZ_ICON_MAP];
        if (typeof iconDef === 'object' && iconDef?.pro) {
          return iconDef.pro;
        }
        return null;
      })
      .filter(Boolean) as string[];
  }

  /**
   * Initialize icon system based on required features
   */
  async initialize(requiredFeatures: string[]): Promise<void> {
    const proFeatures = requiredFeatures.filter(feature => this.isProFeature(feature));

    if (this.enableProIcons && proFeatures.length > 0) {
      console.log(`Loading Font Awesome Pro for features: ${proFeatures.join(', ')}`);
      await this.loadFontAwesome();
    }
  }
}

/**
 * Factory function for creating icon manager instances
 */
export function createIconManager(config: {
  enable_pro_icons?: boolean;
  fallback_to_mdi?: boolean;
}): ExavizIconManager {
  return new ExavizIconManager(
    config.enable_pro_icons ?? false,
    config.fallback_to_mdi ?? true
  );
}

/**
 * Convenient helper for quick icon rendering
 */
export function renderExavizIcon(
  iconKey: string,
  enableProIcons: boolean = false
): string {
  const manager = new ExavizIconManager(enableProIcons, true);
  return manager.renderIcon(iconKey);
} 