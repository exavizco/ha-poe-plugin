// Home Assistant TypeScript Definitions
// Based on Home Assistant frontend types

export interface HomeAssistant {
  states: { [entity_id: string]: HassEntity };
  services: HassServices;
  config: HassConfig;
  themes: Themes;
  selectedTheme: string | null;
  panels: Panels;
  panelUrl: string;
  // Service call method
  callService: (domain: string, service: string, serviceData?: any, target?: any) => Promise<ServiceCallResponse>;
  // Add other properties as needed
}

export interface HassEntity {
  entity_id: string;
  state: string;
  attributes: HassEntityAttributeBase & { [key: string]: any };
  context: Context;
  last_changed: string;
  last_updated: string;
}

export interface HassEntityAttributeBase {
  friendly_name?: string;
  unit_of_measurement?: string;
  icon?: string;
  entity_picture?: string;
  supported_features?: number;
  hidden?: boolean;
  assumed_state?: boolean;
  device_class?: string;
  state_class?: string;
  restored?: boolean;
}

export interface Context {
  id: string;
  parent_id?: string;
  user_id?: string;
}

export interface HassServices {
  [domain: string]: {
    [service: string]: {
      name?: string;
      description?: string;
      target?: any;
      fields?: any;
    };
  };
}

export interface HassConfig {
  latitude: number;
  longitude: number;
  elevation: number;
  unit_system: {
    length: string;
    mass: string;
    temperature: string;
    volume: string;
  };
  location_name: string;
  time_zone: string;
  components: string[];
  config_dir: string;
  whitelist_external_dirs: string[];
  allowlist_external_dirs: string[];
  allowlist_external_urls: string[];
  version: string;
  config_source: string;
  safe_mode: boolean;
  state: string;
  external_url?: string;
  internal_url?: string;
}

export interface Themes {
  default_theme: string;
  themes: { [key: string]: any };
  // Add more theme properties as needed
}

export interface Panels {
  [name: string]: {
    component_name: string;
    config: { [key: string]: any } | null;
    icon: string | null;
    title: string | null;
    url_path: string;
  };
}

// Lovelace Card Interface
export interface LovelaceCard extends HTMLElement {
  hass?: HomeAssistant;
  config?: any;
  setConfig(config: any): void;
  getCardSize?(): number;
  getConfigElement?(): HTMLElement;
}

export interface LovelaceCardConfig {
  type: string;
  [key: string]: any;
}

// Card Editor Interface
export interface LovelaceCardEditor extends HTMLElement {
  hass?: HomeAssistant;
  config?: any;
  setConfig(config: any): void;
}

// Event Interfaces
export interface HassEvent {
  event_type: string;
  data: { [key: string]: any };
  origin: string;
  time_fired: string;
  context: Context;
}

// Service Call Interface
export interface ServiceCallResponse {
  context: Context;
}

// Custom Event Types
export interface CustomEvent<T = any> extends Event {
  detail: T;
}

// Theme-related interfaces
export interface Theme {
  modes: {
    light: { [key: string]: string };
    dark: { [key: string]: string };
  };
}

// Card Helpers
export interface CardHelpers {
  importMoreInfoControl: (tagName: string) => Promise<unknown>;
  createCardElement: (config: LovelaceCardConfig) => LovelaceCard;
  createHeaderFooterElement: (config: any) => HTMLElement;
  // Add more helpers as needed
}

// Lovelace Configuration
export interface LovelaceConfig {
  title?: string;
  views: LovelaceViewConfig[];
  resources?: LovelaceResourceConfig[];
}

export interface LovelaceViewConfig {
  title?: string;
  badges?: (string | LovelaceCardConfig)[];
  cards?: LovelaceCardConfig[];
  path?: string;
  icon?: string;
  theme?: string;
  panel?: boolean;
  background?: string;
  visible?: boolean | any[];
}

export interface LovelaceResourceConfig {
  url: string;
  type: "css" | "js" | "module" | "html";
}

// Authentication
export interface Auth {
  accessToken: string;
  expires: number;
  hassUrl: string;
  clientId: string;
  refresh_token: string;
}

// Connection
export interface Connection {
  options: ConnectionOptions;
  socket: WebSocket;
  connected: boolean;
}

export interface ConnectionOptions {
  setupRetry: number;
  auth?: Auth;
  createSocket: () => Promise<WebSocket>;
}

// Utility Types
export type EntityDomain = string;
export type EntityId = string;
export type ServiceDomain = string;
export type ServiceAction = string; 