export interface AlertEvent {
  id: string;
  severity: string;
  message: string;
  triggered_at: string;
  acknowledged: boolean;
  acknowledged_at?: string;
}

export interface AlertThreshold {
  id: string;
  name: string;
  entity_id: string;
  condition: string;
  value: string | number;
  severity: string;
  enabled: boolean;
  cooldown_minutes: number;
  message_template: string;
}

export interface AlertSummaryData {
  active_alerts: number;
  critical_alerts: number;
  warning_alerts: number;
  recent_alerts: number;
  alert_summary_status: string;
  recent_events: AlertEvent[];
  alert_details: AlertEvent[];
  system_health: string;
  last_updated: string;
} 