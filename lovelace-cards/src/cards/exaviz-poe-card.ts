import { LitElement, html, css, TemplateResult } from 'lit';
import { customElement, property, state } from 'lit/decorators.js';
import type { HomeAssistant } from '../types/homeassistant';

// Extend window interface for custom card registration
declare global {
  interface Window {
    customCards: Array<{
      type: string;
      name: string;
      description: string;
    }>;
  }
}

interface ExavizPoECardConfig {
  type: string;
  name?: string;
  poe_set: string;
  show_header?: boolean;
  layout?: 'auto' | '4-per-row' | '8-per-row';
  show_details?: boolean;
  show_summary?: boolean;
}

@customElement('exaviz-poe-card')
export class ExavizPoECard extends LitElement {
  @property({ attribute: false }) public hass!: HomeAssistant;
  @property() public config!: ExavizPoECardConfig;
  @state() private _ports: any[] = [];
  @state() private _selectedPort: number | null = null;
  @state() private _tooltipVisible: boolean = false;
  @state() private _tooltipContent: string = '';
  @state() private _tooltipX: number = 0;
  @state() private _tooltipY: number = 0;
  @state() private _loadingPorts: Set<number> = new Set();

  /**
   * Called by Lovelace when the user adds a new card.  Provides a
   * sensible default config so the card renders immediately.
   */
  public static getStubConfig(hass: HomeAssistant): Record<string, unknown> {
    // Auto-detect available poe_set values from switch entities
    const sets = new Set<string>();
    Object.keys(hass.states).forEach(entityId => {
      const match = entityId.match(/^switch\.(.+?)_port\d+$/);
      if (match) {
        sets.add(match[1]);
      }
    });
    const available = Array.from(sets).sort();
    return {
      type: 'custom:exaviz-poe-card',
      poe_set: available.length > 0 ? available[0] : 'addon_0',
    };
  }

  public setConfig(config: ExavizPoECardConfig): void {
    if (!config) {
      throw new Error('Invalid configuration');
    }
    // poe_set is optional — auto-detected from entities when omitted
    this.config = {
      show_header: true,
      layout: 'auto',
      show_details: true,
      show_summary: true,
      ...config,
    };
  }

  public getCardSize(): number {
    const baseSize = this.config.show_header ? 1 : 0;
    const portsSize = Math.ceil(this._ports.length / (this._getPortLayout() === '8-per-row' ? 8 : 4));
    const detailsSize = this.config.show_details && this._selectedPort !== null ? 2 : 0;
    const summarySize = this.config.show_summary ? 1 : 0;
    return baseSize + portsSize + detailsSize + summarySize + 1;
  }

  protected firstUpdated(): void {
    this._discoverPorts();
  }

  /**
   * Scan HA entity registry for all poe_set values that have switch entities.
   * Returns sorted array of unique poe_set strings (e.g. ["addon_0", "onboard"]).
   */
  private _detectAvailablePoeSets(): string[] {
    const sets = new Set<string>();
    Object.keys(this.hass.states).forEach(entityId => {
      // Match: switch.{poeSet}_port{N}  (poeSet may contain underscores)
      const match = entityId.match(/^switch\.(.+?)_port\d+$/);
      if (match) {
        sets.add(match[1]);
      }
    });
    return Array.from(sets).sort();
  }

  private _discoverPorts(): void {
    if (!this.hass) return;

    // poe_set config maps directly to backend entity names:
    //   "onboard", "addon_0", "addon_1"
    // When omitted, auto-detect the first available poe_set.
    let poeSet = this.config.poe_set;
    if (!poeSet) {
      const available = this._detectAvailablePoeSets();
      if (available.length > 0) {
        poeSet = available[0];
      } else {
        this._ports = [];
        return;
      }
    }

    const ports: any[] = [];

    // Scan entity registry for switch entities matching our PoE set pattern
    // Backend creates entities like: switch.onboard_port0, switch.addon_0_port3
    Object.keys(this.hass.states).forEach(entityId => {
      if (entityId.startsWith(`switch.${poeSet}_port`)) {
        // Match pattern: switch.{poeSet}_port{number} — poeSet may contain underscores
        const match = entityId.match(/^switch\.(.+?)_port(\d+)$/);
        if (match) {
          const portNumber = parseInt(match[2], 10);
          const portConfig = this._getPortConfig(portNumber, poeSet);
          if (portConfig) {
            ports.push(portConfig);
          }
        }
      }
    });

    // Sort ports to match physical layout: 0,2,4,6 on top row, 1,3,5,7 on bottom row
    ports.sort((a, b) => {
      // Even ports (0,2,4,6) come before odd ports (1,3,5,7)
      const aIsEven = a.port % 2 === 0;
      const bIsEven = b.port % 2 === 0;
      if (aIsEven && !bIsEven) return -1;
      if (!aIsEven && bIsEven) return 1;
      return a.port - b.port;
    });
    this._ports = ports;
  }

  private _getPortConfig(portNumber: number, poeSet?: string): any | null {
    // poe_set values map directly to backend entity names:
    //   "onboard", "addon_0", "addon_1"
    const resolvedPoeSet = poeSet || this.config.poe_set;
    const switchEntity = `switch.${resolvedPoeSet}_port${portNumber}`;
    const currentEntity = `sensor.${resolvedPoeSet}_port${portNumber}_current`;
    const poweredEntity = `binary_sensor.${resolvedPoeSet}_port${portNumber}_powered`;
    const pluggedEntity = `binary_sensor.${resolvedPoeSet}_port${portNumber}_plug`;
    const resetEntity = `button.${resolvedPoeSet}_port${portNumber}_reset`;

    // Check if switch entity exists (required)
    if (!this.hass.states[switchEntity]) {
      return null;
    }

    // Get linux device name from switch entity attributes
    const switchState = this.hass.states[switchEntity];
    const linuxDevice = switchState?.attributes?.linux_device || `${resolvedPoeSet}-${portNumber}`;

    return {
      port: portNumber,
      linux_device: linuxDevice,
      switchEntity,
      currentEntity,
      poweredEntity,
      pluggedEntity,
      resetEntity,
    };
  }

  private async _togglePort(portConfig: any): Promise<void> {
    const portNumber = portConfig.port;
    
    // Add to loading set
    this._loadingPorts.add(portNumber);
    this.requestUpdate();
    
    try {
      // Read enabled state from backend abstraction (sensor entity attributes)
      const currentState = this.hass.states[portConfig.currentEntity];
      const isEnabled = currentState?.attributes?.enabled ?? false;
      const service: string = isEnabled ? 'turn_off' : 'turn_on';
      const expectedState = isEnabled ? 'off' : 'on';
      
      // Use correct Home Assistant service call
      await this.hass.callService('switch', service, {
        entity_id: portConfig.switchEntity,
      });
      
      // Wait for actual state change (poll every 200ms, max 10 seconds)
      const maxAttempts = 50; // 10 seconds
      let attempts = 0;
      while (attempts < maxAttempts) {
        await new Promise(resolve => setTimeout(resolve, 200));
        const newState = this.hass.states[portConfig.switchEntity];
        if (newState?.state === expectedState) {
          // State changed successfully
          break;
        }
        attempts++;
      }
    } catch (error) {
      console.error('Error toggling port:', error);
    } finally {
      // Remove from loading set
      this._loadingPorts.delete(portNumber);
      this.requestUpdate();
    }
  }

  private async _resetPort(portConfig: any): Promise<void> {
    try {
      // Use correct Home Assistant service call  
      await this.hass.callService('button', 'press', {
        entity_id: portConfig.resetEntity,
      });
    } catch (error) {
      console.error('Error resetting port:', error);
    }
  }

  private _getPortStatus(portConfig: any): string {
    const pluggedState = this.hass.states[portConfig.pluggedEntity];
    const poweredState = this.hass.states[portConfig.poweredEntity];
    const currentState = this.hass.states[portConfig.currentEntity];
    
    const isPlugged = pluggedState?.state === 'on';
    const isPowered = poweredState?.state === 'on';
    
    // Use actual PoE hardware status from sensor (e.g., "power on", "disabled", "backoff", "searching")
    const hardwareStatus = currentState?.attributes?.status || '';
    const isEnabled = currentState?.attributes?.enabled ?? true;
    
    // CRITICAL: Admin-disabled overrides everything. The TPS23861 PSE chip
    // may still report "power on" even after `ip link set down` because
    // there's no software path to cut PoE power on Cruiser yet.
    if (!isEnabled || hardwareStatus === 'disabled') return 'disabled';
    
    // Map hardware status to UI status
    if (hardwareStatus === 'power on') return 'active';
    if (hardwareStatus.includes('backoff')) return 'empty';  // IP808AR: Port enabled, no device found (waiting for retry)
    if (hardwareStatus.includes('detection')) return 'empty';  // TPS23861: "start detection" = searching for device
    if (hardwareStatus.includes('searching')) return 'empty';  // Enabled but no device connected
    if (!isPlugged) return 'empty';
    if (isPlugged && isPowered) return 'active';
    if (isPlugged && !isPowered) return 'inactive';
    return 'unknown';
  }

  private _getPortCurrent(portConfig: any): number {
    const currentState = this.hass.states[portConfig.currentEntity];
    return currentState ? parseFloat(currentState.state) || 0 : 0;
  }

  private _getPortLayout(): string {
    if (this.config.layout && this.config.layout !== 'auto') {
      return this.config.layout;
    }
    
    // Auto-detect layout based on port count
    return this._ports.length <= 15 ? '4-per-row' : '8-per-row';
  }

  private _handlePortClick(event: Event, portConfig: any): void {
    event.preventDefault();
    event.stopPropagation();
    
    if (event.type === 'contextmenu') {
      // Right-click: reset port
      this._resetPort(portConfig);
    } else {
      // Left-click: select port for details or toggle
      if (this._selectedPort === portConfig.port) {
        // Second click: toggle port
        this._togglePort(portConfig);
      } else {
        // First click: show details
        this._selectedPort = portConfig.port;
      }
    }
  }

  private _getDefaultCardTitle(): string {
    // Try to read the board type from the board_status sensor
    const boardStatus = this.hass?.states?.['sensor.board_status'];
    const boardType = boardStatus?.attributes?.board_type;
    if (boardType && boardType !== 'unknown') {
      // "cruiser" → "Cruiser", "interceptor" → "Interceptor"
      const boardName = boardType.charAt(0).toUpperCase() + boardType.slice(1);
      return `${boardName} PoE Management`;
    }
    // Fallback: derive from poe_set config
    const poeSet = this.config.poe_set || 'onboard';
    const nameMap: { [key: string]: string } = {
      'onboard': 'Onboard PoE Management',
      'addon_0': 'Add-on Board 0 PoE',
      'addon_1': 'Add-on Board 1 PoE',
    };
    return nameMap[poeSet] || `${poeSet.replace(/_/g, ' ').toUpperCase()} PoE Management`;
  }

  private _getPoeSetSummary(): any {
    let totalPower = 0;
    let activePorts = 0;
    let enabledPorts = 0;
    
    this._ports.forEach(portConfig => {
      const current = this._getPortCurrent(portConfig);
      const status = this._getPortStatus(portConfig);
      // Read enabled state from backend abstraction (sensor entity attributes)
      const currentState = this.hass.states[portConfig.currentEntity];
      const isEnabled = currentState?.attributes?.enabled ?? false;
      
      totalPower += current;
      if (status === 'active') activePorts++;
      if (isEnabled) enabledPorts++;
    });
    
    return {
      totalPorts: this._ports.length,
      enabledPorts,
      activePorts,
      totalPower: totalPower.toFixed(1),
    };
  }

  private _getSelectedPortDetails(): any | null {
    if (this._selectedPort === null) return null;
    
    const portConfig = this._ports.find(p => p.port === this._selectedPort);
    if (!portConfig) return null;
    
    const switchState = this.hass.states[portConfig.switchEntity];
    const currentState = this.hass.states[portConfig.currentEntity];
    const poweredState = this.hass.states[portConfig.poweredEntity];
    const pluggedState = this.hass.states[portConfig.pluggedEntity];
    
    // Check if switch entity is available (for add-on boards, switches are unavailable)
    const switchAvailable = switchState && switchState.state !== 'unavailable';
    
    return {
      port: this._selectedPort,
      entityId: portConfig.currentEntity,  // Store entity ID for accessing attributes
      // Use backend's enabled attribute (abstracted hardware differences)
      enabled: currentState?.attributes?.enabled ?? false,
      switchAvailable: switchAvailable,  // Flag to show/hide enable/disable button
      current: parseFloat(currentState?.state) || 0,
      powered: poweredState?.state === 'on',
      plugged: pluggedState?.state === 'on',
      status: this._getPortStatus(portConfig),
      // Extract device info from sensor entity attributes (sensors have the device info, switches may be unavailable)
      deviceInfo: {
        device_name: currentState?.attributes?.device_name,
        device_type: currentState?.attributes?.device_type,
        ip_address: currentState?.attributes?.device_ip,
        mac_address: currentState?.attributes?.device_mac,
        manufacturer: currentState?.attributes?.device_manufacturer,
        hostname: currentState?.attributes?.device_hostname,
      },
    };
  }

  protected render(): TemplateResult {
    if (!this.config || !this.hass) {
      return html`<ha-card><div class="card-content">Configuration required</div></ha-card>`;
    }

    if (this._ports.length === 0) {
      // Scan for available poe_set values
      const suggestions = this._detectAvailablePoeSets();
      
      return html`
        <ha-card>
          <div class="card-content">
            <div class="no-ports">
              <h3>No PoE ports found for "${this.config.poe_set}"</h3>
              ${suggestions.length > 0 ? html`
                <p>Available PoE systems detected:</p>
                <ul style="text-align: left; padding-left: 20px;">
                  ${suggestions.map(set => html`<li><code>${set}</code></li>`)}
                </ul>
                <p>Update your card configuration to use one of the above values for <code>poe_set</code>.</p>
              ` : html`
                <p>No PoE switch entities found. Make sure the Exaviz integration is configured.</p>
              `}
            </div>
          </div>
        </ha-card>
      `;
    }

    const layout = this._getPortLayout();
    // Derive a user-friendly title from poe_set or board_status entity
    const cardTitle = this.config.name || this._getDefaultCardTitle();
    const summary = this._getPoeSetSummary();
    const selectedPortDetails = this._getSelectedPortDetails();

    return html`
      <ha-card>
        ${this.config.show_header ? html`
          <div class="card-header">
            <img 
              class="exaviz-logo-header" 
              src="/exaviz_static/assets/exaviz_logo_plain.svg?v=20260211" 
              alt="Exaviz"
            />
            <div class="name">${cardTitle}</div>
          </div>
        ` : ''}
        
        <div class="card-content">
          ${this.config.show_summary ? html`
            <div class="poe-summary">
              <div class="summary-item">
                <span class="label">Total Ports:</span>
                <span class="value">${summary.totalPorts}</span>
              </div>
              <div class="summary-item">
                <span class="label">Enabled:</span>
                <span class="value">${summary.enabledPorts}</span>
              </div>
              <div class="summary-item">
                <span class="label">Active:</span>
                <span class="value">${summary.activePorts}</span>
              </div>
              <div class="summary-item">
                <span class="label">Total Power:</span>
                <span class="value">${summary.totalPower}W</span>
              </div>
            </div>
          ` : ''}
          
          ${this._renderServerStatus()}
          
          <div class="poe-grid layout-${layout}">
            ${this._ports.map(portConfig => this._renderPort(portConfig))}
          </div>
          
          ${this.config.show_details && selectedPortDetails ? html`
            <div class="port-details">
              <div class="details-header">
                <h3>Port ${selectedPortDetails.port + 1} Details</h3>
                <button @click=${() => this._selectedPort = null} class="close-btn">×</button>
              </div>
              <div class="details-content">
                <div class="detail-row">
                  <span>Status:</span>
                  <span class="status-${selectedPortDetails.status}">${selectedPortDetails.status}</span>
                </div>
                <div class="detail-row">
                  <span>Power Draw:</span>
                  <span>${this._formatDetailedPowerDisplay(selectedPortDetails)}</span>
                </div>
                <div class="detail-row">
                  <span>Enabled:</span>
                  <span>${selectedPortDetails.enabled ? 'Yes' : 'No'}</span>
                </div>
                <div class="detail-row">
                  <span>Device Plugged:</span>
                  <span>${selectedPortDetails.plugged ? 'Yes' : 'No'}</span>
                </div>
                <div class="detail-row">
                  <span>Device Powered:</span>
                  <span>${selectedPortDetails.powered ? 'Yes' : 'No'}</span>
                </div>
                ${selectedPortDetails.deviceInfo.manufacturer || selectedPortDetails.deviceInfo.mac_address || selectedPortDetails.deviceInfo.ip_address ? html`
                  ${selectedPortDetails.deviceInfo.manufacturer ? html`
                    <div class="detail-row">
                      <span>Manufacturer:</span>
                      <span><strong>${selectedPortDetails.deviceInfo.manufacturer}</strong></span>
                    </div>
                  ` : ''}
                  ${selectedPortDetails.deviceInfo.ip_address ? html`
                    <div class="detail-row">
                      <span>IP Address:</span>
                      <span style="font-family: monospace;">${selectedPortDetails.deviceInfo.ip_address}</span>
                    </div>
                  ` : selectedPortDetails.deviceInfo.manufacturer ? html`
                    <div class="detail-row">
                      <span 
                        class="tooltip-trigger"
                        @mouseenter=${(e: Event) => this._showTooltip(e, 'Device detected but has no IP address. Possible causes: DHCP server not running, static IP configuration, or network issue.')}
                        @mouseleave=${() => this._hideTooltip()}
                      >IP Address:</span>
                      <span style="color: var(--warning-color, #FF9800);">Not assigned</span>
                    </div>
                  ` : ''}
                  ${selectedPortDetails.deviceInfo.mac_address ? html`
                    <div class="detail-row">
                      <span>MAC Address:</span>
                      <span style="font-family: monospace;">${selectedPortDetails.deviceInfo.mac_address}</span>
                    </div>
                  ` : ''}
                  ${selectedPortDetails.deviceInfo.hostname ? html`
                    <div class="detail-row">
                      <span>Hostname:</span>
                      <span>${selectedPortDetails.deviceInfo.hostname}</span>
                    </div>
                  ` : ''}
                ` : ''}
              </div>
              <div class="details-actions">
                ${selectedPortDetails.switchAvailable ? html`
                  <button @click=${() => this._togglePort(this._ports.find(p => p.port === this._selectedPort))} 
                          class="action-btn ${selectedPortDetails.enabled ? 'disable' : 'enable'}">
                    ${selectedPortDetails.enabled ? 'Disable Port' : 'Enable Port'}
                  </button>
                ` : html`
                  <button disabled 
                          class="action-btn disabled" 
                          title="Enable/Disable not supported for add-on boards (kernel driver limitation)">
                    Enable/Disable Unavailable
                  </button>
                `}
                <button @click=${() => this._resetPort(this._ports.find(p => p.port === this._selectedPort))} 
                        class="action-btn reset">
                  Reset Port
                </button>
              </div>
            </div>
          ` : ''}
        </div>
        
        <!-- Custom Tooltip -->
        ${this._tooltipVisible ? html`
          <div 
            class="custom-tooltip" 
            style="left: ${this._tooltipX}px; top: ${this._tooltipY}px;"
          >
            <div class="tooltip-content">
              ${this._tooltipContent.split('\n').map(line => html`
                ${line}<br/>
              `)}
            </div>
          </div>
        ` : ''}
      </ha-card>
    `;
  }

  private _renderPort(portConfig: any): TemplateResult {
    const status = this._getPortStatus(portConfig);
    const current = this._getPortCurrent(portConfig);
    // Read enabled state from backend abstraction (sensor entity attributes)
    const currentState = this.hass.states[portConfig.currentEntity];
    const isEnabled = currentState?.attributes?.enabled ?? false;
    const isSelected = this._selectedPort === portConfig.port;
    const isLoading = this._loadingPorts.has(portConfig.port);

    return html`
      <div 
        class="poe-port port-${status} ${isEnabled ? 'enabled' : 'disabled'} ${isSelected ? 'selected' : ''} ${isLoading ? 'loading' : ''}"
        @click=${(e: Event) => this._handlePortClick(e, portConfig)}
        @contextmenu=${(e: Event) => this._handlePortClick(e, portConfig)}
        title="Port ${portConfig.port + 1}: ${status} (${this._formatPowerDisplay(portConfig)})
Click to select, click again to toggle on/off
Right-click to reset"
      >
        ${isLoading ? html`
          <div class="loading-overlay">
            <div class="spinner"></div>
          </div>
        ` : ''}
        <div class="port-number">P${portConfig.port + 1}</div>
        <div class="port-device">${portConfig.linux_device || `${this.config.poe_set}-${portConfig.port}`}</div>
        <div class="ethernet-connector">
          <div class="connector-body">
            <div class="connector-opening">
              <div class="pin-contacts">
                <div class="pin-group">
                  <div class="pin"></div>
                  <div class="pin"></div>
                  <div class="pin"></div>
                  <div class="pin"></div>
                </div>
                <div class="pin-group">
                  <div class="pin"></div>
                  <div class="pin"></div>
                  <div class="pin"></div>
                  <div class="pin"></div>
                </div>
              </div>
            </div>
            <div class="connector-latch"></div>
          </div>
        </div>
        <div class="port-info">
          <div class="port-current">${this._formatPowerDisplay(portConfig)}</div>
          <div class="port-status">${status}</div>
        </div>
      </div>
    `;
  }

  private _formatPowerDisplay(portConfig: any): string {
    const currentState = this.hass.states[portConfig.currentEntity];
    if (!currentState) {
      return '0W';
    }

    const current = parseFloat(currentState.state) || 0;
    const allocatedPower = currentState.attributes?.allocated_power_watts;

    if (allocatedPower && allocatedPower > 0) {
      return `${current.toFixed(1)}W / ${allocatedPower.toFixed(1)}W`;
    }

    // Fallback to just current if no allocated power available
    return `${current.toFixed(1)}W`;
  }

  private _getPoeClassDescription(poeClass: string): string {
    // PoE class descriptions with power limits
    const descriptions: Record<string, string> = {
      '0': 'Class 0: Unclassified (legacy device, may draw up to port maximum)',
      '1': 'Class 1: 0.44-3.84W (low power devices)',
      '2': 'Class 2: 3.84-6.49W (medium power devices)',
      '3': 'Class 3: 6.49-12.95W (high power devices)',
      '4': 'Class 4: 12.95-25.5W (PoE+ devices, requires 802.3at)',
      '5': 'Class 5: 40-45W (PoE++ Type 3)',
      '6': 'Class 6: 51-60W (PoE++ Type 4)',
      '7': 'Class 7: 62-71.3W (PoE++ Type 4)',
      '8': 'Class 8: 71.3-90W (PoE++ Type 4, maximum)',
      '?': 'Class Unknown: Device not classified'
    };
    return descriptions[poeClass] || `Class ${poeClass}: Unknown power class`;
  }

  private _formatDetailedPowerDisplay(portDetails: any): TemplateResult {
    const current = portDetails.current || 0;
    const currentState = this.hass.states[portDetails.entityId];
    const allocatedPower = currentState?.attributes?.allocated_power_watts;
    const poeClass = currentState?.attributes?.poe_class;

    if (allocatedPower && allocatedPower > 0) {
      const utilization = allocatedPower > 0 ? ((current / allocatedPower) * 100).toFixed(0) : '0';
      
      if (poeClass !== '?') {
        const classTooltip = this._getPoeClassDescription(poeClass);
        return html`
          ${current.toFixed(1)}W / ${allocatedPower.toFixed(1)}W
          <span 
            class="poe-class-label tooltip-trigger"
            @mouseenter=${(e: Event) => this._showTooltip(e, classTooltip)}
            @mouseleave=${() => this._hideTooltip()}
            title="${classTooltip}"
          >
            Class ${poeClass}
          </span>
          - ${utilization}% utilized
        `;
      } else {
        return html`${current.toFixed(1)}W / ${allocatedPower.toFixed(1)}W - ${utilization}% utilized`;
      }
    }

    // Fallback to just current if no allocated power available
    return html`${current.toFixed(1)}W`;
  }

  private _renderServerStatus(): TemplateResult {
    // Check if we have any Exaviz server status sensor
    const serverStatusEntity = this.hass.states['sensor.exaviz_vms_vms_server_status'];
    
    if (!serverStatusEntity) {
      return html``;
    }

    const serverStatus = serverStatusEntity?.state || 'unknown';
    const lastUpdated = serverStatusEntity?.last_updated;
    const attributes = serverStatusEntity?.attributes || {};
    
    // Extract server connection details
    const serverHost = attributes.server_host || 'unknown';
    const serverPort = attributes.server_port || 'unknown';
    const connectionDetails = attributes.connection_details || {};
    const updateInterval = attributes.update_interval || 30;
    const lastUpdateSuccess = attributes.last_update_success;
    
    // Determine overall status and detailed information
    let statusClass = 'unknown';
    let statusText = 'Unknown';
    let statusIcon = '🔸';
    let detailedInfo = '';
    
    if (serverStatus === 'connected') {
      statusClass = 'connected';
      statusText = 'Exaviz Server Connected';
      statusIcon = '🟢';
      detailedInfo = `Real server at ${serverHost}:${serverPort}`;
    } else if (serverStatus === 'mock_poe_data') {
      statusClass = 'mock-poe';
      statusText = 'Exaviz Server Connected (PoE mocked)';
      statusIcon = '🔵';
      detailedInfo = `Real server at ${serverHost}:${serverPort} (mock PoE data)`;
    } else if (serverStatus === 'disconnected') {
      statusClass = 'disconnected';
      statusText = 'Exaviz Server Disconnected';
      statusIcon = '🔴';
      detailedInfo = `Connection to ${serverHost}:${serverPort} failed`;
    } else if (serverStatus === 'mock') {
      statusClass = 'mock';
      statusText = 'Mock Server';
      statusIcon = '🟡';
      detailedInfo = 'Full mock mode - demo data only';
    }

    // Build detailed tooltip content
    const tooltipContent = this._buildServerTooltip(attributes, connectionDetails, serverStatus);
    
    // Connection health indicator
    const isHealthy = lastUpdateSuccess && (
      serverStatus === 'connected' || 
      serverStatus === 'mock_poe_data' || 
      serverStatus === 'mock'
    );
    
    const timeSinceUpdate = lastUpdated ? 
      Math.floor((Date.now() - new Date(lastUpdated).getTime()) / 1000) : null;
    
    const isStale = timeSinceUpdate && timeSinceUpdate > (updateInterval * 2);

    return html`
      <div class="server-status">
        <div class="status-item">
          <span class="label">Server Status:</span>
          <span 
            class="value status-${statusClass} ${isStale ? 'stale' : ''} tooltip-trigger" 
            @mouseenter=${(e: Event) => this._showTooltip(e, tooltipContent)}
            @mouseleave=${() => this._hideTooltip()}
          >
            ${statusIcon} ${statusText}
            ${!isHealthy ? html`<span class="health-indicator">⚠️</span>` : ''}
          </span>
        </div>
        <div class="status-item">
          <span class="label">Connection:</span>
          <span 
            class="value connection-info tooltip-trigger" 
            @mouseenter=${(e: Event) => this._showTooltip(e, detailedInfo)}
            @mouseleave=${() => this._hideTooltip()}
          >
            ${serverHost}:${serverPort}
            ${serverStatus === 'mock_poe_data' ? html`<span class="mock-indicator">(PoE mocked)</span>` : ''}
          </span>
        </div>
        ${lastUpdated ? html`
          <div class="status-item">
            <span class="label">Last Check:</span>
            <span class="value ${isStale ? 'stale' : ''}">
              ${new Date(lastUpdated).toLocaleTimeString()}
              ${isStale ? html`<span class="stale-indicator">⏰</span>` : ''}
            </span>
          </div>
        ` : ''}
        ${this._renderServerHealthIndicator(attributes, timeSinceUpdate, updateInterval)}
      </div>
    `;
  }

  private _buildServerTooltip(
    attributes: any, 
    connectionDetails: any, 
    serverStatus: string
  ): string {
    const lines = [];
    
    // Server connection info
    lines.push(`🌐 Server: ${attributes.server_host || 'unknown'}:${attributes.server_port || 'unknown'}`);
    
    if (serverStatus === 'mock') {
      lines.push('🎭 Mode: Full mock server (demo data)');
      lines.push('📊 PoE Data: Simulated (8 ports, realistic power consumption)');
      lines.push('⚡ Hardware: Mock PoE+ capable hardware');
      lines.push('🔄 Updates: Every 30 seconds with dynamic data');
    } else if (serverStatus === 'mock_poe_data') {
      lines.push('🎭 Mode: Real server + mock PoE data');
      lines.push('✅ VMS Connected: Real Exaviz server');
      lines.push('📊 PoE Data: Simulated (real server lacks PoE implementation)');
      lines.push('⚡ Hardware: Mock 2x8 PoE+ ports configuration');
    } else if (serverStatus === 'connected') {
      lines.push('✅ Mode: Fully connected to real server');
      lines.push('📊 PoE Data: Real hardware data');
      lines.push('⚡ Hardware: Physical PoE+ switches');
    } else {
      lines.push('❌ Status: Connection failed or unavailable');
    }
    
    // Connection details
    if (connectionDetails.connected !== undefined) {
      lines.push(`🔗 Connected: ${connectionDetails.connected ? 'Yes' : 'No'}`);
    }
    if (connectionDetails.authenticated !== undefined) {
      lines.push(`🔐 Authenticated: ${connectionDetails.authenticated ? 'Yes' : 'No'}`);
    }
    if (connectionDetails.update_count) {
      lines.push(`📈 Updates: ${connectionDetails.update_count}`);
    }
    if (connectionDetails.error_count) {
      lines.push(`❌ Errors: ${connectionDetails.error_count}`);
    }
    
    // Update info
    if (attributes.update_interval) {
      lines.push(`⏱️ Update Interval: ${attributes.update_interval}s`);
    }
    if (attributes.last_update_success !== undefined) {
      lines.push(`✅ Last Update: ${attributes.last_update_success ? 'Success' : 'Failed'}`);
    }
    
    return lines.join('\n');
  }

  private _renderServerHealthIndicator(
    attributes: any, 
    timeSinceUpdate: number | null, 
    updateInterval: number
  ): TemplateResult {
    const errorCount = attributes.connection_details?.error_count || 0;
    const updateCount = attributes.connection_details?.update_count || 0;
    const successRate = updateCount > 0 ? ((updateCount - errorCount) / updateCount * 100).toFixed(1) : '100.0';
    
    if (errorCount > 0 || (timeSinceUpdate && timeSinceUpdate > updateInterval * 2)) {
      return html`
        <div class="status-item health-warning">
          <span class="label">Health:</span>
          <span 
            class="value tooltip-trigger" 
            @mouseenter=${(e: Event) => this._showTooltip(e, "Connection health information\nErrors may indicate network issues or server problems")}
            @mouseleave=${() => this._hideTooltip()}
          >
            ${errorCount > 0 ? html`${errorCount} errors` : ''}
            ${timeSinceUpdate && timeSinceUpdate > updateInterval * 2 ? 
              html`(${timeSinceUpdate}s since update)` : ''}
            Success: ${successRate}%
          </span>
        </div>
      `;
    }
    
    return html``;
  }

  private _showTooltip(event: Event, content: string): void {
    const target = event.target as HTMLElement;
    const rect = target.getBoundingClientRect();
    
    this._tooltipContent = content;
    this._tooltipX = rect.left + (rect.width / 2);
    this._tooltipY = rect.top - 10;
    this._tooltipVisible = true;
  }

  private _hideTooltip(): void {
    this._tooltipVisible = false;
  }

  static get styles() {
    return css`
      @import url('https://fonts.googleapis.com/css2?family=Bruno+Ace+SC&display=swap');
      
      :host {
        display: block;
      }

      ha-card {
        overflow: hidden;
      }

      .card-header {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 16px;
        border-bottom: 1px solid var(--divider-color);
        background: #5F6461; /* Exaviz Gray */
      }

      .exaviz-logo-header {
        height: 32px;
        width: auto;
        opacity: 1.0;
      }

      .card-header .name {
        font-size: 18px;
        font-weight: 600;
        color: #ffffff; /* Exaviz White for visibility on gray background */
        flex: 1;
      }

      .card-content {
        padding: 16px;
      }

      /* PoE Summary */
      .poe-summary {
        display: grid;
        grid-template-columns: repeat(2, 1fr);  /* Force 2 columns for consistent narrow layout */
        gap: 8px;
        margin-bottom: 16px;
        padding: 8px;
        background: var(--secondary-background-color);
        border-radius: 8px;
      }

      .summary-item {
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
      }

      .summary-item .label {
        font-size: 12px;
        color: var(--secondary-text-color);
        margin-bottom: 4px;
      }

      .summary-item .value {
        font-size: 16px;
        font-weight: bold;
        color: var(--primary-text-color);
      }

      /* Server Status */
      .server-status {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 12px;
        margin-bottom: 16px;
        padding: 10px 14px;
        background: var(--secondary-background-color);
        border-radius: 6px;
        font-size: 14px;
      }

      .server-status .status-item {
        display: flex;
        align-items: center;
        gap: 6px;
        white-space: nowrap;
        min-width: 0;
        flex-shrink: 0;
      }

      .server-status .label {
        color: var(--secondary-text-color);
        flex-shrink: 0;
      }

      .server-status .value {
        font-weight: 500;
        text-overflow: ellipsis;
        overflow: hidden;
      }

      .server-status .status-connected {
        color: var(--success-color, #4caf50);
      }

      .server-status .status-disconnected {
        color: var(--error-color, #f44336);
      }

      .server-status .status-mock {
        color: var(--warning-color, #ff9800);
      }

      .server-status .status-mock-poe {
        color: var(--primary-color, #4f7cff);
      }

      .server-status .status-unknown {
        color: var(--secondary-text-color);
      }

      /* Enhanced server status indicators */
      .server-status .stale {
        opacity: 0.7;
        color: var(--warning-color, #ff9800) !important;
      }

      .server-status .health-indicator {
        margin-left: 4px;
        font-size: 12px;
      }

      .server-status .stale-indicator {
        margin-left: 4px;
        font-size: 12px;
        color: var(--warning-color, #ff9800);
      }

      .server-status .mock-indicator {
        font-size: 12px;
        color: var(--secondary-text-color);
        font-style: italic;
        margin-left: 4px;
      }

      .server-status .connection-info {
        font-family: monospace;
        font-size: 13px;
      }

      .server-status .health-warning {
        color: var(--warning-color, #ff9800);
      }

      .server-status .health-warning .value {
        font-size: 13px;
      }

      /* Custom Tooltip */
      .tooltip-trigger {
        cursor: help;
        position: relative;
      }

      .tooltip-trigger:hover {
        text-decoration: underline dotted;
      }

      .poe-class-label {
        color: var(--primary-color, #4F7CFF);
        font-weight: 500;
        cursor: help;
        border-bottom: 1px dotted currentColor;
      }

      .poe-class-label:hover {
        border-bottom-style: solid;
      }

      .custom-tooltip {
        position: fixed;
        z-index: 9999;
        background: rgba(0, 0, 0, 0.95);
        color: white;
        padding: 8px 12px;
        border-radius: 8px;
        font-size: 11px;
        line-height: 1.1;
        max-width: 280px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
        pointer-events: none;
        transform: translateX(-50%) translateY(-100%);
        border: 1px solid rgba(255, 255, 255, 0.1);
        backdrop-filter: blur(10px);
        animation: tooltipFadeIn 0.2s ease-out;
      }

      .tooltip-content {
        white-space: pre-line;
        word-wrap: break-word;
      }

      @keyframes tooltipFadeIn {
        from {
          opacity: 0;
          transform: translateX(-50%) translateY(-100%) scale(0.9);
        }
        to {
          opacity: 1;
          transform: translateX(-50%) translateY(-100%) scale(1);
        }
      }

      /* Responsive design for smaller screens */
      @media (max-width: 480px) {
        .server-status {
          flex-direction: column;
          align-items: flex-start;
          gap: 8px;
        }
        
        .server-status .status-item {
          width: 100%;
          justify-content: space-between;
        }
      }

      /* Port Grid */
      .poe-grid {
        display: grid;
        gap: 12px;
        margin-bottom: 16px;
      }

      .poe-grid.layout-4-per-row {
        grid-template-columns: repeat(4, 1fr);
      }

      .poe-grid.layout-8-per-row {
        grid-template-columns: repeat(4, 1fr);
      }

      /* Port Styling */
      .poe-port {
        display: flex;
        flex-direction: column;
        align-items: center;
        padding: 12px 6px;
        border-radius: 12px;
        cursor: pointer;
        transition: all 0.3s ease;
        border: 2px solid transparent;
        background: var(--card-background-color);
        user-select: none;
        position: relative;
      }

      .poe-port:hover {
        transform: translateY(-3px);
        box-shadow: 0 6px 12px rgba(0, 0, 0, 0.15);
      }

      .poe-port.selected {
        border-width: 3px;
        box-shadow: 0 0 8px rgba(33, 150, 243, 0.3);
        background: rgba(33, 150, 243, 0.05);
      }

      /* Removed opacity on disabled class - port status is already visually indicated by port-disabled, port-empty, etc. */
      /* This was making Interceptor cards look foggy since switch entities are unavailable for add-on boards */

      /* Loading state */
      .poe-port.loading {
        pointer-events: none;
      }

      .loading-overlay {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.5);
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 12px;
        z-index: 10;
      }

      .spinner {
        width: 32px;
        height: 32px;
        border: 3px solid rgba(255, 255, 255, 0.3);
        border-top-color: white;
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
      }

      @keyframes spin {
        to { transform: rotate(360deg); }
      }

      /* Status Colors */
      .poe-port.port-on {
        background: linear-gradient(135deg, #4CAF50 0%, #2E7D32 100%);
        border: 2px solid #33691E;
      }

      .poe-port.port-off {
        background: linear-gradient(135deg, #FF9800 0%, #EF6C00 100%);
        border: 2px solid #E65100;
      }

      .poe-port.port-active {
        background: linear-gradient(135deg, rgba(76,175,80,0.2) 0%, rgba(46,125,50,0.2) 100%);
        border: 2px solid #33691E;
      }

      .poe-port.port-inactive {
        background: linear-gradient(135deg, rgba(255,152,0,0.2) 0%, rgba(239,108,0,0.2) 100%);
        border: 2px solid #E65100;
      }

      .poe-port.port-disabled {
        background: linear-gradient(135deg, #9E9E9E 0%, #616161 100%);
        border: 2px solid #424242;
        color: white !important;
      }

      .poe-port.port-disabled .port-number,
      .poe-port.port-disabled .port-status,
      .poe-port.port-disabled .port-current {
        color: white !important;
        text-shadow: 0 1px 2px rgba(0,0,0,0.3);
      }

      .poe-port.port-empty {
        background: linear-gradient(135deg, #F5F5F5 0%, #E0E0E0 100%);
        border: 2px solid #BDBDBD;
      }

      .poe-port.port-unknown {
        background: linear-gradient(145deg, #F44336 0%, #D32F2F 100%);
        border: 2px solid #B71C1C;
      }

      .port-number {
        font-size: 10px;
        font-weight: bold;
        color: var(--secondary-text-color);
        margin-bottom: 2px;
      }

      .port-device {
        font-size: 8px;
        font-family: monospace;
        color: var(--secondary-text-color);
        opacity: 0.7;
        margin-bottom: 6px;
      }

      /* Realistic Ethernet Connector */
      .ethernet-connector {
        margin-bottom: 8px;
      }

      .connector-body {
        width: 36px;
        height: 28px;
        background: linear-gradient(145deg, #e0e0e0, #c0c0c0);
        border: 1px solid #999;
        border-radius: 4px;
        position: relative;
        box-shadow: inset 0 1px 3px rgba(0,0,0,0.1);
      }

      .connector-opening {
        position: absolute;
        top: 6px;
        left: 4px;
        right: 4px;
        bottom: 8px;
        background: #333;
        border-radius: 2px;
        display: flex;
        align-items: center;
        justify-content: center;
      }

      .pin-contacts {
        display: flex;
        flex-direction: column;
        gap: 2px;
        align-items: center;
      }

      .pin-group {
        display: flex;
        gap: 2px;
      }

      .pin {
        width: 2px;
        height: 4px;
        background: linear-gradient(to bottom, #ffd700, #ffa500);
        border-radius: 1px;
        box-shadow: 0 0 1px rgba(255, 215, 0, 0.5);
      }

      .connector-latch {
        position: absolute;
        bottom: -2px;
        left: 50%;
        transform: translateX(-50%);
        width: 8px;
        height: 4px;
        background: #999;
        border-radius: 0 0 2px 2px;
      }

      /* Status-specific connector styling */
      .port-active .connector-body {
        background: linear-gradient(145deg, #c8e6c9, #a5d6a7);
        border-color: #4CAF50;
      }

      .port-active .pin {
        background: linear-gradient(to bottom, #66BB6A, #4CAF50);
        box-shadow: 0 0 2px rgba(76, 175, 80, 0.6);
      }

      .port-inactive .connector-body {
        background: linear-gradient(145deg, #fff3e0, #ffcc02);
        border-color: #FF9800;
      }

      .port-inactive .pin {
        background: linear-gradient(to bottom, #FFB74D, #FF9800);
        box-shadow: 0 0 2px rgba(255, 152, 0, 0.6);
      }

      .port-empty .connector-body {
        background: linear-gradient(145deg, #f5f5f5, #e0e0e0);
        border-color: #bbb;
      }

      .port-empty .pin {
        background: linear-gradient(to bottom, #ccc, #999);
        box-shadow: none;
      }

      .port-unknown .connector-body {
        background: linear-gradient(145deg, #ffebee, #ffcdd2);
        border-color: #F44336;
      }

      .port-unknown .pin {
        background: linear-gradient(to bottom, #EF5350, #F44336);
        box-shadow: 0 0 2px rgba(244, 67, 54, 0.6);
      }

      .port-info {
        text-align: center;
        font-size: 11px;
        line-height: 1.2;
      }

      .port-current {
        font-weight: bold;
        color: var(--primary-text-color);
      }

      .port-status {
        color: var(--secondary-text-color);
        text-transform: capitalize;
      }

      /* Port Details Panel */
      .port-details {
        background: var(--secondary-background-color);
        border-radius: 12px;
        padding: 16px;
        margin-top: 16px;
        border: 1px solid var(--divider-color);
      }

      .details-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 12px;
        padding-bottom: 8px;
        border-bottom: 1px solid var(--divider-color);
      }

      .details-header h3 {
        margin: 0;
        font-size: 16px;
        color: var(--primary-text-color);
      }

      .close-btn {
        background: none;
        border: none;
        font-size: 24px;
        cursor: pointer;
        color: var(--secondary-text-color);
        padding: 0;
        width: 30px;
        height: 30px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: all 0.2s ease;
      }

      .close-btn:hover {
        background: var(--divider-color);
        color: var(--primary-text-color);
      }

      .details-content {
        display: grid;
        gap: 8px;
        margin-bottom: 16px;
      }

      .detail-row {
        display: flex;
        justify-content: space-between;
        padding: 4px 0;
      }

      .detail-row span:first-child {
        color: var(--secondary-text-color);
        font-weight: 500;
      }

      .detail-row span:last-child {
        color: var(--primary-text-color);
        font-weight: 600;
      }

      .status-active { color: #4CAF50; }
      .status-inactive { color: #FF9800; }
      .status-empty { color: var(--secondary-text-color); }
      .status-disabled { color: var(--disabled-text-color); }
      .status-unknown { color: #F44336; }

      .details-actions {
        display: flex;
        gap: 12px;
        justify-content: center;
      }

      .action-btn {
        padding: 8px 16px;
        border: none;
        border-radius: 6px;
        cursor: pointer;
        font-weight: 500;
        transition: all 0.2s ease;
        min-width: 100px;
      }

      .action-btn.enable {
        background: #4CAF50;
        color: white;
      }

      .action-btn.enable:hover {
        background: #45a049;
      }

      .action-btn.disable {
        background: #F44336;
        color: white;
      }
      
      .action-btn.disable:hover {
        background: #D32F2F;
      }

      .action-btn.reset {
        background: #2196F3;
        color: white;
      }
      
      .action-btn.reset:hover {
        background: #1976D2;
      }

      .action-btn.disabled {
        background: #9E9E9E;
        color: #FFFFFF;
        cursor: not-allowed;
        opacity: 0.6;
      }

      .no-ports {
        text-align: center;
        color: var(--secondary-text-color);
        padding: 40px 20px;
        font-style: italic;
        font-size: 16px;
      }

      /* Responsive Design */
      @media (max-width: 600px) {
        .poe-grid.layout-4-per-row {
          grid-template-columns: repeat(4, 1fr);
        }
        
        .poe-summary {
          grid-template-columns: repeat(2, 1fr);
        }
        
        .details-actions {
          flex-direction: column;
        }
      }
    `;
  }
}

// Register the card
window.customCards = window.customCards || [];
window.customCards.push({
  type: 'exaviz-poe-card',
  name: 'Exaviz PoE Management Card',
  description: 'Comprehensive PoE port management with visual status indicators and detailed controls'
});

console.info(
  '%c  EXAVIZ-POE-CARD  %c  v2.0.0  ',
  'color: orange; font-weight: bold; background: black',
  'color: white; font-weight: bold; background: dimgray',
); 