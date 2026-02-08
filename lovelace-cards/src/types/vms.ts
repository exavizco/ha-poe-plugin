/*
 * Copyright (c) 2024 Axzez LLC.
 * Licensed under MIT with Commons Clause. See LICENSE for details.
 */

/**
 * Exaviz VMS TypeScript Definitions
 * Enhanced with client analysis data structures for type safety
 */

export interface Camera {
  id: number;
  name: string;
  unique_id: string;
  status: number;
  state: string;
  properties: Record<string, unknown>;
  place_name: string;
  gateway_name: string;
  gateway_status: number;
  place_id: number;
  config_id: number;
  is_online: boolean;
  status_name: string;
  protocol?: string; // ONVIF, RTSP, etc.
  resolution?: {
    width: number;
    height: number;
  };
  frame_rate?: number;
}

export interface Gateway {
  id: number;
  name: string;
  status: number;
  state: string;
  properties: Record<string, unknown>;
  place_name: string;
  is_online: boolean;
  status_name: string;
  device_count?: number; // Number of devices managed by this gateway
}

export interface SystemStatus {
  server_online: boolean;
  server_status: string;
  vms_version: string;
  uptime_seconds: number;
  total_cameras: number;
  online_cameras: number;
  offline_cameras: number;
  error_cameras: number;
  total_gateways: number;
  online_gateways: number;
  offline_gateways: number;
  error_gateways: number;
  cpu_usage: number;
  memory_usage: number;
  storage_used_gb: number;
  storage_total_gb: number;
  last_updated: string; // ISO date string
}

export interface SystemMetrics {
  cpu_usage_percent: number | null;
  memory_usage_percent: number | null;
  memory_used_gb: number | null;
  memory_total_gb: number | null;
  storage_used_gb: number | null;
  storage_total_gb: number | null;
  storage_usage_percent: number | null;
  uptime_seconds: number | null;
  process_count: number | null;
  load_average: number | null;
  temperature_celsius: number | null;
  disk_io_read_mb_s: number | null;
  disk_io_write_mb_s: number | null;
  network_rx_mb_s: number | null;
  network_tx_mb_s: number | null;
  last_updated: Date;
  
  // Computed properties
  memory_free_gb: number | null;
  storage_free_gb: number | null;
  is_healthy: boolean;
}

// Enhanced sensor data from client analysis
export interface EnhancedSensorData {
  // Device hierarchy (based on client device management)
  total_devices: number;
  onvif_devices: number;
  devices_per_gateway: number;
  
  // Real-time events (based on changeset analysis)
  recent_events: number;
  active_alerts: number;
  changeset_sequence: number;
  
  // Connection and protocol (based on tunnel analysis)
  connection_mode: string; // "Http Api" | "Database" | "Unknown"
  tunnel_servers: number;
  live_streams: number;
  
  // Performance and cache
  cache_hit_ratio: number; // Percentage
  database_operations: number;
  http_operations: number;
}

// Real-time event structures (based on client analysis)
export interface VmsEvent {
  id?: string;
  type: string; // motion, system, intrusion, etc.
  severity: 'info' | 'warning' | 'error' | 'critical';
  message: string;
  timestamp: string; // ISO date string
  recent: boolean;
  acknowledged: boolean;
  source_id?: string;
  camera_id?: string;
  gateway_id?: string;
}

export interface EventStreamData {
  total_events: number;
  event_types: Record<string, number>;
  severity_counts: Record<string, number>;
  recent_events_count: number;
  acknowledged_count: number;
  unacknowledged_count: number;
  websocket_connected: boolean;
  changeset_sequence: number;
  latest_events: VmsEvent[];
}

// Connection mode and performance data
export interface ConnectionModeData {
  connection_mode: string;
  auto_detection_enabled: boolean;
  http_api_available: boolean;
  database_available: boolean;
  last_connection_attempt?: string;
}

export interface CacheStatistics {
  cache_size: number;
  cache_hits: number;
  cache_misses: number;
  total_requests: number;
  avg_response_time: number;
  hit_ratio: number;
  database_preference: number;
  http_preference: number;
}

// Device hierarchy data (from client analysis)
export interface DeviceHierarchyData {
  device_types: Record<string, number>; // protocol -> count
  device_statuses: Record<string, number>; // status -> count
  gateway_breakdown: Record<string, number>; // gateway -> device count
  sample_devices: Array<{
    name: string;
    type: string;
    status: string;
    gateway: string;
  }>;
}

// Enhanced VMS data structure including all new sensors
export interface EnhancedVmsData {
  status: SystemStatus;
  cameras: {
    camera_count: number;
    active_cameras: number;
    cameras: Camera[];
  };
  gateways: {
    gateway_count: number;
    active_gateways: number;
    gateways: Gateway[];
  };
  events?: {
    events: VmsEvent[];
  };
  // Enhanced sensor data
  enhanced: EnhancedSensorData;
  event_stream?: EventStreamData;
  connection_info?: ConnectionModeData;
  cache_stats?: CacheStatistics;
  device_hierarchy?: DeviceHierarchyData;
  // PoE monitoring data (Axzez hardware only)
  hardware?: HardwareData;
  poe?: PoEData;
}

export interface VmsConfig {
  directory_port?: string;
  version?: string;
  [key: string]: string | undefined;
}

// Status constants matching Python
export const STATUS = {
  OFFLINE: 0,
  ONLINE: 1,
  ERROR: 2,
  MAINTENANCE: 3,
} as const;

export type StatusValue = typeof STATUS[keyof typeof STATUS];

// Event severity levels
export const EVENT_SEVERITY = {
  INFO: 'info',
  WARNING: 'warning',
  ERROR: 'error',
  CRITICAL: 'critical',
} as const;

export type EventSeverity = typeof EVENT_SEVERITY[keyof typeof EVENT_SEVERITY];

// Connection modes (from VMS client analysis)
export const CONNECTION_MODE = {
  HTTP_API: 'Http Api',
  DATABASE: 'Database',
  UNKNOWN: 'Unknown',
} as const;

export type ConnectionMode = typeof CONNECTION_MODE[keyof typeof CONNECTION_MODE];

// Home Assistant service types
export interface HomeAssistantService {
  domain: string;
  service: string;
  service_data?: Record<string, unknown>;
}

export interface ExavizServiceData {
  url?: string;
  camera_id?: number | string;
  source_id?: string;
  gateway_id?: string;
  device_id?: string;
  view?: string;
  launch_method?: 'auto' | 'native' | 'url' | 'tunnel';
  client_path?: string;
  tunnel_port?: number;
  background?: boolean;
}

// PoE (Power over Ethernet) monitoring types
export interface PoEPort {
  port_number: number;
  enabled: boolean;
  status: 'active' | 'inactive' | 'fault' | 'disabled';
  power_consumption_watts: number;
  voltage_volts: number;
  current_milliamps: number;
  connected_device?: {
    name: string;
    ip_address: string;
    mac_address: string;
    device_type: string;
    manufacturer: string;
    power_class: string;
  };
}

export interface PoEData {
  total_ports: number;
  active_ports: number;
  power_budget_watts: number;
  power_used_watts: number;
  power_available_watts: number;
  efficiency_percent: number;
  ports: PoEPort[];
  last_updated: string; // ISO date string
}

export interface HardwareData {
  hardware_type: string;
  poe_capable: boolean;
  capabilities: string[];
  model: string;
  serial_number?: string;
  firmware_version?: string;
}

// PoE status constants
export const POE_STATUS = {
  ACTIVE: 'active',
  INACTIVE: 'inactive',
  FAULT: 'fault',
  DISABLED: 'disabled',
} as const;

export type PoEStatus = typeof POE_STATUS[keyof typeof POE_STATUS];

// PoE power classes (IEEE 802.3 standard)
export const POE_POWER_CLASS = {
  CLASS_0: 'Class 0 (0.44-12.95W)',
  CLASS_1: 'Class 1 (0.44-3.84W)',
  CLASS_2: 'Class 2 (3.84-6.49W)',
  CLASS_3: 'Class 3 (6.49-12.95W)',
  CLASS_4: 'Class 4 (12.95-25.5W)',
  CLASS_5: 'Class 5 (25.5-40W)',
  CLASS_6: 'Class 6 (40-51W)',
  CLASS_7: 'Class 7 (51-62W)',
  CLASS_8: 'Class 8 (62-71.3W)',
} as const;

export type PoEPowerClass = typeof POE_POWER_CLASS[keyof typeof POE_POWER_CLASS]; 