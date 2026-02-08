// Home Assistant types for Exaviz cards
export interface HassEntity {
  entity_id: string;
  state: string;
  attributes: { [key: string]: any };
  context: {
    id: string;
    parent_id?: string;
    user_id?: string;
  };
  last_changed: string;
  last_updated: string;
}

export interface HassEntities {
  [entity_id: string]: HassEntity;
}

export interface HomeAssistant {
  states: HassEntities;
  config: {
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
    allowlist_external_dirs: string[];
    allowlist_external_urls: string[];
    version: string;
    config_source: string;
    recovery_mode: boolean;
    safe_mode: boolean;
  };
  themes: {
    default_theme: string;
    themes: { [key: string]: any };
  };
  selectedTheme?: string | null;
  language: string;
  user: {
    id: string;
    name: string;
    is_owner: boolean;
    is_admin: boolean;
    credentials: Array<{
      type: string;
    }>;
    mfa_modules: Array<{
      id: string;
      name: string;
      enabled: boolean;
    }>;
  };
  callService: (domain: string, service: string, serviceData?: any) => Promise<any>;
  callApi: <T>(method: string, path: string, parameters?: any) => Promise<T>;
  fetchWithAuth: (path: string, init?: any) => Promise<Response>;
  sendMessage: (message: any) => void;
  connection: {
    subscribeEvents: (callback: Function, eventType?: string) => Function;
    subscribeMessage: (callback: Function, subscribeMessage: any) => Function;
  };
}

export interface LovelaceCard {
  hass?: HomeAssistant;
  config: any;
  setConfig(config: any): void;
  getCardSize?(): number;
}

export interface LovelaceCardConfig {
  type: string;
  [key: string]: any;
} 