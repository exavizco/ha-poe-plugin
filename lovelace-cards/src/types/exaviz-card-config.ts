import { LovelaceCardConfig } from 'custom-card-helpers';

export interface ExavizPoEPortCardConfig extends LovelaceCardConfig {
  entity: string;
  name?: string;
  compact?: boolean;
  enable_pro_icons?: boolean;  // Enable Font Awesome Pro icons
  fallback_to_mdi?: boolean;   // Fallback to MDI if FA fails
  icon_style?: 'mdi-only' | 'fa-only' | 'contextual';
}

export interface ExavizStatusCardConfig extends LovelaceCardConfig {
  entity: string;
  name?: string;
  show_details?: boolean;
  enable_pro_icons?: boolean;
  fallback_to_mdi?: boolean;
  icon_style?: 'mdi-only' | 'fa-only' | 'contextual';
  pro_features?: {
    analytics?: boolean;
    advanced_poe?: boolean;
    vms_server?: boolean;
  };
}

// Icon mapping for contextual usage
export const EXAVIZ_ICON_MAP = {
  // Basic features - always MDI
  'camera': 'mdi:camera',
  'server': 'mdi:server',
  'storage': 'mdi:harddisk',
  'ethernet': 'mdi:ethernet',
  'chart': 'mdi:chart-line',
  
  // Professional features - Font Awesome Pro when available
  'poe-advanced': {
    pro: 'fal fa-ethernet',
    fallback: 'mdi:ethernet'
  },
  'analytics': {
    pro: 'far fa-chart-network',
    fallback: 'mdi:chart-line'
  },
  'vms-server': {
    pro: 'fad fa-server-rack',
    fallback: 'mdi:server'
  },
  'tunnel-secure': {
    pro: 'fas fa-shield-keyhole',
    fallback: 'mdi:shield'
  },
  'camera-ptz': {
    pro: 'fal fa-video-plus',
    fallback: 'mdi:camera-control'
  },
  'storage-raid': {
    pro: 'fad fa-hdd-stack',  
    fallback: 'mdi:harddisk'
  }
}; 