import { html, TemplateResult } from 'lit';

/**
 * Logo variants available in the project
 */
export enum LogoVariant {
  WHITE = 'white',           // Original white on dark background
  GREEN = 'green',            // Exaviz brand green (#90FF80)
  GREEN_GRAY = 'green_gray', // Green main text, gray tagline (preferred)
  CUSTOMIZABLE = 'customizable',  // Uses CSS custom properties
  OUTLINED = 'outlined',     // Outlined version (white)
  PNG = 'png'               // PNG version from downloads
}

/**
 * Logo size presets
 */
export enum LogoSize {
  SMALL = 'small',   // 60x18
  MEDIUM = 'medium', // 100x30 (default)
  LARGE = 'large',   // 140x42
  XLARGE = 'xlarge'  // 200x60
}

/**
 * Theme-aware logo configuration
 */
export interface LogoConfig {
  variant?: LogoVariant;
  size?: LogoSize;
  color?: string;           // Override color for customizable variant
  taglineColor?: string;    // Override tagline color
  className?: string;       // Additional CSS classes
  style?: string;          // Inline styles
}

/**
 * ExavizLogoManager - Handles logo loading, theming, and rendering
 */
export class ExavizLogoManager {
  private static readonly LOGO_PATHS = {
    [LogoVariant.WHITE]: '/local/exaviz-cards/assets/images/exaviz_logo.svg',
    [LogoVariant.GREEN]: '/local/exaviz-cards/assets/images/exaviz_logo_green.svg',
    [LogoVariant.GREEN_GRAY]: '/local/exaviz-cards/assets/images/exaviz_logo_green_gray.svg',
    [LogoVariant.CUSTOMIZABLE]: '/local/exaviz-cards/assets/images/exaviz_logo_customizable.svg',
    [LogoVariant.OUTLINED]: '/local/exaviz-cards/assets/images/exaviz_logo_outlined.svg',
    [LogoVariant.PNG]: '/local/exaviz-cards/assets/images/exaviz.png'
  };

  private static readonly SIZE_DIMENSIONS = {
    [LogoSize.SMALL]: { width: '60px', height: '18px' },
    [LogoSize.MEDIUM]: { width: '100px', height: '30px' },
    [LogoSize.LARGE]: { width: '140px', height: '42px' },
    [LogoSize.XLARGE]: { width: '200px', height: '60px' }
  };

  /**
   * Render Exaviz logo as HTML template
   */
  static renderLogo(config: LogoConfig = {}): TemplateResult {
    const {
      variant = LogoVariant.GREEN_GRAY,  // Use preferred green/gray variant as default
      size = LogoSize.MEDIUM,
      color,
      taglineColor,
      className = '',
      style = ''
    } = config;

    const dimensions = this.SIZE_DIMENSIONS[size];
    const logoPath = this.LOGO_PATHS[variant];
    
    // Build CSS custom properties for customizable variant
    const cssVars = variant === LogoVariant.CUSTOMIZABLE ? 
      this.buildCSSVariables(color, taglineColor) : '';

    const combinedStyle = `
      ${cssVars}
      width: ${dimensions.width};
      height: ${dimensions.height};
      ${style}
    `.trim();

    return html`
      <img 
        src="${logoPath}"
        alt="Exaviz VMS"
        class="exaviz-logo ${className}"
        style="${combinedStyle}"
        loading="lazy"
      />
    `;
  }

  /**
   * Render logo as inline SVG for maximum customization
   */
  static async renderInlineLogo(config: LogoConfig = {}): Promise<TemplateResult> {
    const {
      variant = LogoVariant.GREEN,
      size = LogoSize.MEDIUM,
      color,
      taglineColor,
      className = '',
      style = ''
    } = config;

    try {
      const svgContent = await this.loadSVGContent(variant);
      const dimensions = this.SIZE_DIMENSIONS[size];
      
      // Apply color customizations if specified
      const processedSVG = this.processSVGContent(svgContent, color, taglineColor);
      
      const containerStyle = `
        width: ${dimensions.width};
        height: ${dimensions.height};
        display: inline-block;
        ${style}
      `.trim();

      return html`
        <div class="exaviz-logo-container ${className}" style="${containerStyle}">
          ${html([processedSVG] as any)}
        </div>
      `;
    } catch (error) {
      console.error('Failed to load inline logo:', error);
      // Fallback to img tag
      return this.renderLogo(config);
    }
  }

  /**
   * Get theme-appropriate logo variant based on Home Assistant theme
   */
  static getThemeVariant(haTheme?: any): LogoVariant {
    if (!haTheme) return LogoVariant.GREEN;

    const isDarkTheme = haTheme.dark || 
      (haTheme['primary-background-color'] && 
       this.isColorDark(haTheme['primary-background-color']));

    return isDarkTheme ? LogoVariant.WHITE : LogoVariant.GREEN;
  }

  /**
   * Generate CSS classes for logo integration
   */
  static getLogoCSS(): string {
    return `
      .exaviz-logo {
        vertical-align: middle;
        transition: opacity 0.3s ease, transform 0.3s ease;
      }
      
      .exaviz-logo:hover {
        opacity: 0.8;
        transform: scale(1.05);
      }
      
      .exaviz-logo-container {
        display: inline-flex;
        align-items: center;
        justify-content: center;
      }
      
      /* Theme-aware logo colors */
      .exaviz-logo-customizable {
        --exaviz-logo-color: var(--primary-color, #90FF80);
        --exaviz-tagline-color: var(--primary-color, #90FF80);
      }
      
      /* Dark theme adjustments */
      @media (prefers-color-scheme: dark) {
        .exaviz-logo-customizable {
          --exaviz-logo-color: var(--primary-color, #7394FF);
          --exaviz-tagline-color: var(--primary-color, #7394FF);
        }
      }
      
      /* Home Assistant theme integration */
      [data-theme="dark"] .exaviz-logo-customizable {
        --exaviz-logo-color: #7394FF;
        --exaviz-tagline-color: #7394FF;
      }
    `;
  }

  // Private helper methods
  private static buildCSSVariables(color?: string, taglineColor?: string): string {
    const vars: string[] = [];
    if (color) vars.push(`--exaviz-logo-color: ${color};`);
    if (taglineColor) vars.push(`--exaviz-tagline-color: ${taglineColor};`);
    return vars.join(' ');
  }

  private static async loadSVGContent(variant: LogoVariant): Promise<string> {
    const url = this.LOGO_PATHS[variant];
    const response = await fetch(url);
    if (!response.ok) throw new Error(`Failed to load SVG: ${response.status}`);
    return response.text();
  }

  private static processSVGContent(
    svgContent: string, 
    color?: string, 
    taglineColor?: string
  ): string {
    let processed = svgContent;
    
    if (color) {
      processed = processed.replace(/fill="#FFFFFF"/g, `fill="${color}"`);
    }
    
    // Additional processing for specific color overrides
    if (taglineColor && processed.includes('IoT + AI + Video')) {
      // More sophisticated SVG processing could go here
    }
    
    return processed;
  }

  private static isColorDark(color: string): boolean {
    // Simple color brightness detection
    const hex = color.replace('#', '');
    const r = parseInt(hex.substr(0, 2), 16);
    const g = parseInt(hex.substr(2, 2), 16);
    const b = parseInt(hex.substr(4, 2), 16);
    const brightness = (r * 299 + g * 587 + b * 114) / 1000;
    return brightness < 128;
  }
}

/**
 * Convenient helper functions for common logo usage
 */
export const renderExavizLogo = (config?: LogoConfig) => 
  ExavizLogoManager.renderLogo(config);

export const renderThemeLogo = (haTheme?: any, size?: LogoSize) => 
  ExavizLogoManager.renderLogo({
    variant: ExavizLogoManager.getThemeVariant(haTheme),
    size
  });

export const renderHeaderLogo = () => 
  ExavizLogoManager.renderLogo({
    variant: LogoVariant.CUSTOMIZABLE,
    size: LogoSize.MEDIUM,
    className: 'exaviz-header-logo'
  });

export const renderCardLogo = (size: LogoSize = LogoSize.SMALL) => 
  ExavizLogoManager.renderLogo({
    variant: LogoVariant.CUSTOMIZABLE,
    size,
    className: 'exaviz-card-logo'
  });

export const renderPreferredLogo = (size: LogoSize = LogoSize.MEDIUM) => 
  ExavizLogoManager.renderLogo({
    variant: LogoVariant.GREEN_GRAY,  // Green main text, gray tagline
    size,
    className: 'exaviz-preferred-logo'
  }); 