function t(t,e,s,o){var i,r=arguments.length,a=r<3?e:null===o?o=Object.getOwnPropertyDescriptor(e,s):o;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)a=Reflect.decorate(t,e,s,o);else for(var n=t.length-1;n>=0;n--)(i=t[n])&&(a=(r<3?i(a):r>3?i(e,s,a):i(e,s))||a);return r>3&&a&&Object.defineProperty(e,s,a),a}function e(t,e){if("object"==typeof Reflect&&"function"==typeof Reflect.metadata)return Reflect.metadata(t,e)}"function"==typeof SuppressedError&&SuppressedError;
/**
 * @license
 * Copyright 2019 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
const s=globalThis,o=s.ShadowRoot&&(void 0===s.ShadyCSS||s.ShadyCSS.nativeShadow)&&"adoptedStyleSheets"in Document.prototype&&"replace"in CSSStyleSheet.prototype,i=Symbol(),r=new WeakMap;let a=class{constructor(t,e,s){if(this._$cssResult$=!0,s!==i)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=t,this.t=e}get styleSheet(){let t=this.o;const e=this.t;if(o&&void 0===t){const s=void 0!==e&&1===e.length;s&&(t=r.get(e)),void 0===t&&((this.o=t=new CSSStyleSheet).replaceSync(this.cssText),s&&r.set(e,t))}return t}toString(){return this.cssText}};const n=(t,...e)=>{const s=1===t.length?t[0]:e.reduce(((e,s,o)=>e+(t=>{if(!0===t._$cssResult$)return t.cssText;if("number"==typeof t)return t;throw Error("Value passed to 'css' function must be a 'css' function result: "+t+". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.")})(s)+t[o+1]),t[0]);return new a(s,t,i)},l=o?t=>t:t=>t instanceof CSSStyleSheet?(t=>{let e="";for(const s of t.cssRules)e+=s.cssText;return(t=>new a("string"==typeof t?t:t+"",void 0,i))(e)})(t):t,{is:c,defineProperty:d,getOwnPropertyDescriptor:p,getOwnPropertyNames:h,getOwnPropertySymbols:u,getPrototypeOf:g}=Object,v=globalThis,f=v.trustedTypes,m=f?f.emptyScript:"",_=v.reactiveElementPolyfillSupport,b=(t,e)=>t,y={toAttribute(t,e){switch(e){case Boolean:t=t?m:null;break;case Object:case Array:t=null==t?t:JSON.stringify(t)}return t},fromAttribute(t,e){let s=t;switch(e){case Boolean:s=null!==t;break;case Number:s=null===t?null:Number(t);break;case Object:case Array:try{s=JSON.parse(t)}catch(t){s=null}}return s}},$=(t,e)=>!c(t,e),x={attribute:!0,type:String,converter:y,reflect:!1,useDefault:!1,hasChanged:$};
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */Symbol.metadata??=Symbol("metadata"),v.litPropertyMetadata??=new WeakMap;let w=class extends HTMLElement{static addInitializer(t){this._$Ei(),(this.l??=[]).push(t)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(t,e=x){if(e.state&&(e.attribute=!1),this._$Ei(),this.prototype.hasOwnProperty(t)&&((e=Object.create(e)).wrapped=!0),this.elementProperties.set(t,e),!e.noAccessor){const s=Symbol(),o=this.getPropertyDescriptor(t,s,e);void 0!==o&&d(this.prototype,t,o)}}static getPropertyDescriptor(t,e,s){const{get:o,set:i}=p(this.prototype,t)??{get(){return this[e]},set(t){this[e]=t}};return{get:o,set(e){const r=o?.call(this);i?.call(this,e),this.requestUpdate(t,r,s)},configurable:!0,enumerable:!0}}static getPropertyOptions(t){return this.elementProperties.get(t)??x}static _$Ei(){if(this.hasOwnProperty(b("elementProperties")))return;const t=g(this);t.finalize(),void 0!==t.l&&(this.l=[...t.l]),this.elementProperties=new Map(t.elementProperties)}static finalize(){if(this.hasOwnProperty(b("finalized")))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(b("properties"))){const t=this.properties,e=[...h(t),...u(t)];for(const s of e)this.createProperty(s,t[s])}const t=this[Symbol.metadata];if(null!==t){const e=litPropertyMetadata.get(t);if(void 0!==e)for(const[t,s]of e)this.elementProperties.set(t,s)}this._$Eh=new Map;for(const[t,e]of this.elementProperties){const s=this._$Eu(t,e);void 0!==s&&this._$Eh.set(s,t)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(t){const e=[];if(Array.isArray(t)){const s=new Set(t.flat(1/0).reverse());for(const t of s)e.unshift(l(t))}else void 0!==t&&e.push(l(t));return e}static _$Eu(t,e){const s=e.attribute;return!1===s?void 0:"string"==typeof s?s:"string"==typeof t?t.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise((t=>this.enableUpdating=t)),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach((t=>t(this)))}addController(t){(this._$EO??=new Set).add(t),void 0!==this.renderRoot&&this.isConnected&&t.hostConnected?.()}removeController(t){this._$EO?.delete(t)}_$E_(){const t=new Map,e=this.constructor.elementProperties;for(const s of e.keys())this.hasOwnProperty(s)&&(t.set(s,this[s]),delete this[s]);t.size>0&&(this._$Ep=t)}createRenderRoot(){const t=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return((t,e)=>{if(o)t.adoptedStyleSheets=e.map((t=>t instanceof CSSStyleSheet?t:t.styleSheet));else for(const o of e){const e=document.createElement("style"),i=s.litNonce;void 0!==i&&e.setAttribute("nonce",i),e.textContent=o.cssText,t.appendChild(e)}})(t,this.constructor.elementStyles),t}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(!0),this._$EO?.forEach((t=>t.hostConnected?.()))}enableUpdating(t){}disconnectedCallback(){this._$EO?.forEach((t=>t.hostDisconnected?.()))}attributeChangedCallback(t,e,s){this._$AK(t,s)}_$ET(t,e){const s=this.constructor.elementProperties.get(t),o=this.constructor._$Eu(t,s);if(void 0!==o&&!0===s.reflect){const i=(void 0!==s.converter?.toAttribute?s.converter:y).toAttribute(e,s.type);this._$Em=t,null==i?this.removeAttribute(o):this.setAttribute(o,i),this._$Em=null}}_$AK(t,e){const s=this.constructor,o=s._$Eh.get(t);if(void 0!==o&&this._$Em!==o){const t=s.getPropertyOptions(o),i="function"==typeof t.converter?{fromAttribute:t.converter}:void 0!==t.converter?.fromAttribute?t.converter:y;this._$Em=o,this[o]=i.fromAttribute(e,t.type)??this._$Ej?.get(o)??null,this._$Em=null}}requestUpdate(t,e,s){if(void 0!==t){const o=this.constructor,i=this[t];if(s??=o.getPropertyOptions(t),!((s.hasChanged??$)(i,e)||s.useDefault&&s.reflect&&i===this._$Ej?.get(t)&&!this.hasAttribute(o._$Eu(t,s))))return;this.C(t,e,s)}!1===this.isUpdatePending&&(this._$ES=this._$EP())}C(t,e,{useDefault:s,reflect:o,wrapped:i},r){s&&!(this._$Ej??=new Map).has(t)&&(this._$Ej.set(t,r??e??this[t]),!0!==i||void 0!==r)||(this._$AL.has(t)||(this.hasUpdated||s||(e=void 0),this._$AL.set(t,e)),!0===o&&this._$Em!==t&&(this._$Eq??=new Set).add(t))}async _$EP(){this.isUpdatePending=!0;try{await this._$ES}catch(t){Promise.reject(t)}const t=this.scheduleUpdate();return null!=t&&await t,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(const[t,e]of this._$Ep)this[t]=e;this._$Ep=void 0}const t=this.constructor.elementProperties;if(t.size>0)for(const[e,s]of t){const{wrapped:t}=s,o=this[e];!0!==t||this._$AL.has(e)||void 0===o||this.C(e,void 0,s,o)}}let t=!1;const e=this._$AL;try{t=this.shouldUpdate(e),t?(this.willUpdate(e),this._$EO?.forEach((t=>t.hostUpdate?.())),this.update(e)):this._$EM()}catch(e){throw t=!1,this._$EM(),e}t&&this._$AE(e)}willUpdate(t){}_$AE(t){this._$EO?.forEach((t=>t.hostUpdated?.())),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(t)),this.updated(t)}_$EM(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(t){return!0}update(t){this._$Eq&&=this._$Eq.forEach((t=>this._$ET(t,this[t]))),this._$EM()}updated(t){}firstUpdated(t){}};w.elementStyles=[],w.shadowRootOptions={mode:"open"},w[b("elementProperties")]=new Map,w[b("finalized")]=new Map,_?.({ReactiveElement:w}),(v.reactiveElementVersions??=[]).push("2.1.0");
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
const E=globalThis,P=E.trustedTypes,A=P?P.createPolicy("lit-html",{createHTML:t=>t}):void 0,k="$lit$",S=`lit$${Math.random().toFixed(9).slice(2)}$`,C="?"+S,F=`<${C}>`,T=document,D=()=>T.createComment(""),U=t=>null===t||"object"!=typeof t&&"function"!=typeof t,z=Array.isArray,O="[ \t\n\f\r]",M=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,R=/-->/g,H=/>/g,I=RegExp(`>|${O}(?:([^\\s"'>=/]+)(${O}*=${O}*(?:[^ \t\n\f\r"'\`<>=]|("|')|))|$)`,"g"),N=/'/g,j=/"/g,W=/^(?:script|style|textarea|title)$/i,B=(t=>(e,...s)=>({_$litType$:t,strings:e,values:s}))(1),L=Symbol.for("lit-noChange"),V=Symbol.for("lit-nothing"),Y=new WeakMap,q=T.createTreeWalker(T,129);function X(t,e){if(!z(t)||!t.hasOwnProperty("raw"))throw Error("invalid template strings array");return void 0!==A?A.createHTML(e):e}const Z=(t,e)=>{const s=t.length-1,o=[];let i,r=2===e?"<svg>":3===e?"<math>":"",a=M;for(let e=0;e<s;e++){const s=t[e];let n,l,c=-1,d=0;for(;d<s.length&&(a.lastIndex=d,l=a.exec(s),null!==l);)d=a.lastIndex,a===M?"!--"===l[1]?a=R:void 0!==l[1]?a=H:void 0!==l[2]?(W.test(l[2])&&(i=RegExp("</"+l[2],"g")),a=I):void 0!==l[3]&&(a=I):a===I?">"===l[0]?(a=i??M,c=-1):void 0===l[1]?c=-2:(c=a.lastIndex-l[2].length,n=l[1],a=void 0===l[3]?I:'"'===l[3]?j:N):a===j||a===N?a=I:a===R||a===H?a=M:(a=I,i=void 0);const p=a===I&&t[e+1].startsWith("/>")?" ":"";r+=a===M?s+F:c>=0?(o.push(n),s.slice(0,c)+k+s.slice(c)+S+p):s+S+(-2===c?e:p)}return[X(t,r+(t[s]||"<?>")+(2===e?"</svg>":3===e?"</math>":"")),o]};class G{constructor({strings:t,_$litType$:e},s){let o;this.parts=[];let i=0,r=0;const a=t.length-1,n=this.parts,[l,c]=Z(t,e);if(this.el=G.createElement(l,s),q.currentNode=this.el.content,2===e||3===e){const t=this.el.content.firstChild;t.replaceWith(...t.childNodes)}for(;null!==(o=q.nextNode())&&n.length<a;){if(1===o.nodeType){if(o.hasAttributes())for(const t of o.getAttributeNames())if(t.endsWith(k)){const e=c[r++],s=o.getAttribute(t).split(S),a=/([.?@])?(.*)/.exec(e);n.push({type:1,index:i,name:a[2],strings:s,ctor:"."===a[1]?et:"?"===a[1]?st:"@"===a[1]?ot:tt}),o.removeAttribute(t)}else t.startsWith(S)&&(n.push({type:6,index:i}),o.removeAttribute(t));if(W.test(o.tagName)){const t=o.textContent.split(S),e=t.length-1;if(e>0){o.textContent=P?P.emptyScript:"";for(let s=0;s<e;s++)o.append(t[s],D()),q.nextNode(),n.push({type:2,index:++i});o.append(t[e],D())}}}else if(8===o.nodeType)if(o.data===C)n.push({type:2,index:i});else{let t=-1;for(;-1!==(t=o.data.indexOf(S,t+1));)n.push({type:7,index:i}),t+=S.length-1}i++}}static createElement(t,e){const s=T.createElement("template");return s.innerHTML=t,s}}function J(t,e,s=t,o){if(e===L)return e;let i=void 0!==o?s._$Co?.[o]:s._$Cl;const r=U(e)?void 0:e._$litDirective$;return i?.constructor!==r&&(i?._$AO?.(!1),void 0===r?i=void 0:(i=new r(t),i._$AT(t,s,o)),void 0!==o?(s._$Co??=[])[o]=i:s._$Cl=i),void 0!==i&&(e=J(t,i._$AS(t,e.values),i,o)),e}class K{constructor(t,e){this._$AV=[],this._$AN=void 0,this._$AD=t,this._$AM=e}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(t){const{el:{content:e},parts:s}=this._$AD,o=(t?.creationScope??T).importNode(e,!0);q.currentNode=o;let i=q.nextNode(),r=0,a=0,n=s[0];for(;void 0!==n;){if(r===n.index){let e;2===n.type?e=new Q(i,i.nextSibling,this,t):1===n.type?e=new n.ctor(i,n.name,n.strings,this,t):6===n.type&&(e=new it(i,this,t)),this._$AV.push(e),n=s[++a]}r!==n?.index&&(i=q.nextNode(),r++)}return q.currentNode=T,o}p(t){let e=0;for(const s of this._$AV)void 0!==s&&(void 0!==s.strings?(s._$AI(t,s,e),e+=s.strings.length-2):s._$AI(t[e])),e++}}class Q{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(t,e,s,o){this.type=2,this._$AH=V,this._$AN=void 0,this._$AA=t,this._$AB=e,this._$AM=s,this.options=o,this._$Cv=o?.isConnected??!0}get parentNode(){let t=this._$AA.parentNode;const e=this._$AM;return void 0!==e&&11===t?.nodeType&&(t=e.parentNode),t}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(t,e=this){t=J(this,t,e),U(t)?t===V||null==t||""===t?(this._$AH!==V&&this._$AR(),this._$AH=V):t!==this._$AH&&t!==L&&this._(t):void 0!==t._$litType$?this.$(t):void 0!==t.nodeType?this.T(t):(t=>z(t)||"function"==typeof t?.[Symbol.iterator])(t)?this.k(t):this._(t)}O(t){return this._$AA.parentNode.insertBefore(t,this._$AB)}T(t){this._$AH!==t&&(this._$AR(),this._$AH=this.O(t))}_(t){this._$AH!==V&&U(this._$AH)?this._$AA.nextSibling.data=t:this.T(T.createTextNode(t)),this._$AH=t}$(t){const{values:e,_$litType$:s}=t,o="number"==typeof s?this._$AC(t):(void 0===s.el&&(s.el=G.createElement(X(s.h,s.h[0]),this.options)),s);if(this._$AH?._$AD===o)this._$AH.p(e);else{const t=new K(o,this),s=t.u(this.options);t.p(e),this.T(s),this._$AH=t}}_$AC(t){let e=Y.get(t.strings);return void 0===e&&Y.set(t.strings,e=new G(t)),e}k(t){z(this._$AH)||(this._$AH=[],this._$AR());const e=this._$AH;let s,o=0;for(const i of t)o===e.length?e.push(s=new Q(this.O(D()),this.O(D()),this,this.options)):s=e[o],s._$AI(i),o++;o<e.length&&(this._$AR(s&&s._$AB.nextSibling,o),e.length=o)}_$AR(t=this._$AA.nextSibling,e){for(this._$AP?.(!1,!0,e);t&&t!==this._$AB;){const e=t.nextSibling;t.remove(),t=e}}setConnected(t){void 0===this._$AM&&(this._$Cv=t,this._$AP?.(t))}}class tt{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(t,e,s,o,i){this.type=1,this._$AH=V,this._$AN=void 0,this.element=t,this.name=e,this._$AM=o,this.options=i,s.length>2||""!==s[0]||""!==s[1]?(this._$AH=Array(s.length-1).fill(new String),this.strings=s):this._$AH=V}_$AI(t,e=this,s,o){const i=this.strings;let r=!1;if(void 0===i)t=J(this,t,e,0),r=!U(t)||t!==this._$AH&&t!==L,r&&(this._$AH=t);else{const o=t;let a,n;for(t=i[0],a=0;a<i.length-1;a++)n=J(this,o[s+a],e,a),n===L&&(n=this._$AH[a]),r||=!U(n)||n!==this._$AH[a],n===V?t=V:t!==V&&(t+=(n??"")+i[a+1]),this._$AH[a]=n}r&&!o&&this.j(t)}j(t){t===V?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,t??"")}}class et extends tt{constructor(){super(...arguments),this.type=3}j(t){this.element[this.name]=t===V?void 0:t}}class st extends tt{constructor(){super(...arguments),this.type=4}j(t){this.element.toggleAttribute(this.name,!!t&&t!==V)}}class ot extends tt{constructor(t,e,s,o,i){super(t,e,s,o,i),this.type=5}_$AI(t,e=this){if((t=J(this,t,e,0)??V)===L)return;const s=this._$AH,o=t===V&&s!==V||t.capture!==s.capture||t.once!==s.once||t.passive!==s.passive,i=t!==V&&(s===V||o);o&&this.element.removeEventListener(this.name,this,s),i&&this.element.addEventListener(this.name,this,t),this._$AH=t}handleEvent(t){"function"==typeof this._$AH?this._$AH.call(this.options?.host??this.element,t):this._$AH.handleEvent(t)}}class it{constructor(t,e,s){this.element=t,this.type=6,this._$AN=void 0,this._$AM=e,this.options=s}get _$AU(){return this._$AM._$AU}_$AI(t){J(this,t)}}const rt=E.litHtmlPolyfillSupport;rt?.(G,Q),(E.litHtmlVersions??=[]).push("3.3.0");const at=globalThis;
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */class nt extends w{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){const t=super.createRenderRoot();return this.renderOptions.renderBefore??=t.firstChild,t}update(t){const e=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(t),this._$Do=((t,e,s)=>{const o=s?.renderBefore??e;let i=o._$litPart$;if(void 0===i){const t=s?.renderBefore??null;o._$litPart$=i=new Q(e.insertBefore(D(),t),t,void 0,s??{})}return i._$AI(t),i})(e,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return L}}nt._$litElement$=!0,nt.finalized=!0,at.litElementHydrateSupport?.({LitElement:nt});const lt=at.litElementPolyfillSupport;lt?.({LitElement:nt}),(at.litElementVersions??=[]).push("4.2.0");
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
const ct={attribute:!0,type:String,converter:y,reflect:!1,hasChanged:$},dt=(t=ct,e,s)=>{const{kind:o,metadata:i}=s;let r=globalThis.litPropertyMetadata.get(i);if(void 0===r&&globalThis.litPropertyMetadata.set(i,r=new Map),"setter"===o&&((t=Object.create(t)).wrapped=!0),r.set(s.name,t),"accessor"===o){const{name:o}=s;return{set(s){const i=e.get.call(this);e.set.call(this,s),this.requestUpdate(o,i,t)},init(e){return void 0!==e&&this.C(o,void 0,t,e),e}}}if("setter"===o){const{name:o}=s;return function(s){const i=this[o];e.call(this,s),this.requestUpdate(o,i,t)}}throw Error("Unsupported decorator location: "+o)};
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */function pt(t){return(e,s)=>"object"==typeof s?dt(t,e,s):((t,e,s)=>{const o=e.hasOwnProperty(s);return e.constructor.createProperty(s,t),o?Object.getOwnPropertyDescriptor(e,s):void 0})(t,e,s)}
/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */function ht(t){return pt({...t,state:!0,attribute:!1})}let ut=class extends nt{constructor(){super(...arguments),this._ports=[],this._selectedPort=null,this._tooltipVisible=!1,this._tooltipContent="",this._tooltipX=0,this._tooltipY=0,this._loadingPorts=new Set}static getStubConfig(t){const e=new Set;Object.keys(t.states).forEach((t=>{const s=t.match(/^switch\.(.+?)_port\d+$/);s&&e.add(s[1])}));const s=Array.from(e).sort();return{type:"custom:exaviz-poe-card",poe_set:s.length>0?s[0]:"addon_0"}}setConfig(t){if(!t)throw new Error("Invalid configuration");this.config={show_header:!0,layout:"auto",show_details:!0,show_summary:!0,...t}}getCardSize(){return(this.config.show_header?1:0)+Math.ceil(this._ports.length/("8-per-row"===this._getPortLayout()?8:4))+(this.config.show_details&&null!==this._selectedPort?2:0)+(this.config.show_summary?1:0)+1}firstUpdated(){this._discoverPorts()}_detectAvailablePoeSets(){const t=new Set;return Object.keys(this.hass.states).forEach((e=>{const s=e.match(/^switch\.(.+?)_port\d+$/);s&&t.add(s[1])})),Array.from(t).sort()}_discoverPorts(){if(!this.hass)return;let t=this.config.poe_set;if(!t){const e=this._detectAvailablePoeSets();if(!(e.length>0))return void(this._ports=[]);t=e[0]}const e=[];Object.keys(this.hass.states).forEach((s=>{if(s.startsWith(`switch.${t}_port`)){const o=s.match(/^switch\.(.+?)_port(\d+)$/);if(o){const s=parseInt(o[2],10),i=this._getPortConfig(s,t);i&&e.push(i)}}})),e.sort(((t,e)=>{const s=t.port%2==0,o=e.port%2==0;return s&&!o?-1:!s&&o?1:t.port-e.port})),this._ports=e}_getPortConfig(t,e){const s=e||this.config.poe_set,o=`switch.${s}_port${t}`,i=`sensor.${s}_port${t}_current`,r=`binary_sensor.${s}_port${t}_powered`,a=`binary_sensor.${s}_port${t}_plug`,n=`button.${s}_port${t}_reset`;if(!this.hass.states[o])return null;const l=this.hass.states[o];return{port:t,linux_device:l?.attributes?.linux_device||`${s}-${t}`,switchEntity:o,currentEntity:i,poweredEntity:r,pluggedEntity:a,resetEntity:n}}async _togglePort(t){const e=t.port;this._loadingPorts.add(e),this.requestUpdate();try{const e=this.hass.states[t.currentEntity],s=e?.attributes?.enabled??!1,o=s?"turn_off":"turn_on",i=s?"off":"on";await this.hass.callService("switch",o,{entity_id:t.switchEntity});const r=50;let a=0;for(;a<r;){await new Promise((t=>setTimeout(t,200)));const e=this.hass.states[t.switchEntity];if(e?.state===i)break;a++}}catch(t){console.error("Error toggling port:",t)}finally{this._loadingPorts.delete(e),this.requestUpdate()}}async _resetPort(t){try{await this.hass.callService("button","press",{entity_id:t.resetEntity})}catch(t){console.error("Error resetting port:",t)}}_getPortStatus(t){const e=this.hass.states[t.pluggedEntity],s=this.hass.states[t.poweredEntity],o=this.hass.states[t.currentEntity],i="on"===e?.state,r="on"===s?.state,a=o?.attributes?.status||"";return(o?.attributes?.enabled??!0)&&"disabled"!==a?"power on"===a?"active":a.includes("backoff")||a.includes("detection")||a.includes("searching")?"empty":i?i&&r?"active":i&&!r?"inactive":"unknown":"empty":"disabled"}_getPortCurrent(t){const e=this.hass.states[t.currentEntity];return e&&parseFloat(e.state)||0}_getPortLayout(){return this.config.layout&&"auto"!==this.config.layout?this.config.layout:this._ports.length<=15?"4-per-row":"8-per-row"}_handlePortClick(t,e){t.preventDefault(),t.stopPropagation(),"contextmenu"===t.type?this._resetPort(e):this._selectedPort===e.port?this._togglePort(e):this._selectedPort=e.port}_getDefaultCardTitle(){const t=this.hass?.states?.["sensor.board_status"],e=t?.attributes?.board_type;if(e&&"unknown"!==e){return`${e.charAt(0).toUpperCase()+e.slice(1)} PoE Management`}const s=this.config.poe_set||"onboard";return{onboard:"Onboard PoE Management",addon_0:"Add-on Board 0 PoE",addon_1:"Add-on Board 1 PoE"}[s]||`${s.replace(/_/g," ").toUpperCase()} PoE Management`}_getPoeSetSummary(){let t=0,e=0,s=0;return this._ports.forEach((o=>{const i=this._getPortCurrent(o),r=this._getPortStatus(o),a=this.hass.states[o.currentEntity];t+=i,"active"===r&&e++,(a?.attributes?.enabled??!1)&&s++})),{totalPorts:this._ports.length,enabledPorts:s,activePorts:e,totalPower:t.toFixed(1)}}_getSelectedPortDetails(){if(null===this._selectedPort)return null;const t=this._ports.find((t=>t.port===this._selectedPort));if(!t)return null;const e=this.hass.states[t.switchEntity],s=this.hass.states[t.currentEntity],o=this.hass.states[t.poweredEntity],i=this.hass.states[t.pluggedEntity],r=e&&"unavailable"!==e.state;return{port:this._selectedPort,entityId:t.currentEntity,enabled:s?.attributes?.enabled??!1,switchAvailable:r,current:parseFloat(s?.state)||0,powered:"on"===o?.state,plugged:"on"===i?.state,status:this._getPortStatus(t),deviceInfo:{device_name:s?.attributes?.device_name,device_type:s?.attributes?.device_type,ip_address:s?.attributes?.device_ip,mac_address:s?.attributes?.device_mac,manufacturer:s?.attributes?.device_manufacturer,hostname:s?.attributes?.device_hostname}}}render(){if(!this.config||!this.hass)return B`<ha-card><div class="card-content">Configuration required</div></ha-card>`;if(0===this._ports.length){const t=this._detectAvailablePoeSets();return B`
        <ha-card>
          <div class="card-content">
            <div class="no-ports">
              <h3>No PoE ports found for "${this.config.poe_set}"</h3>
              ${t.length>0?B`
                <p>Available PoE systems detected:</p>
                <ul style="text-align: left; padding-left: 20px;">
                  ${t.map((t=>B`<li><code>${t}</code></li>`))}
                </ul>
                <p>Update your card configuration to use one of the above values for <code>poe_set</code>.</p>
              `:B`
                <p>No PoE switch entities found. Make sure the Exaviz integration is configured.</p>
              `}
            </div>
          </div>
        </ha-card>
      `}const t=this._getPortLayout(),e=this.config.name||this._getDefaultCardTitle(),s=this._getPoeSetSummary(),o=this._getSelectedPortDetails();return B`
      <ha-card>
        ${this.config.show_header?B`
          <div class="card-header">
            <img 
              class="exaviz-logo-header" 
              src="/exaviz_static/assets/exaviz_logo_plain.svg?v=20260211" 
              alt="Exaviz"
            />
            <div class="name">${e}</div>
          </div>
        `:""}
        
        <div class="card-content">
          ${this.config.show_summary?B`
            <div class="poe-summary">
              <div class="summary-item">
                <span class="label">Total Ports:</span>
                <span class="value">${s.totalPorts}</span>
              </div>
              <div class="summary-item">
                <span class="label">Enabled:</span>
                <span class="value">${s.enabledPorts}</span>
              </div>
              <div class="summary-item">
                <span class="label">Active:</span>
                <span class="value">${s.activePorts}</span>
              </div>
              <div class="summary-item">
                <span class="label">Total Power:</span>
                <span class="value">${s.totalPower}W</span>
              </div>
            </div>
          `:""}
          
          ${this._renderServerStatus()}
          
          <div class="poe-grid layout-${t}">
            ${this._ports.map((t=>this._renderPort(t)))}
          </div>
          
          ${this.config.show_details&&o?B`
            <div class="port-details">
              <div class="details-header">
                <h3>Port ${o.port+1} Details</h3>
                <button @click=${()=>this._selectedPort=null} class="close-btn">×</button>
              </div>
              <div class="details-content">
                <div class="detail-row">
                  <span>Status:</span>
                  <span class="status-${o.status}">${o.status}</span>
                </div>
                <div class="detail-row">
                  <span>Power Draw:</span>
                  <span>${this._formatDetailedPowerDisplay(o)}</span>
                </div>
                <div class="detail-row">
                  <span>Enabled:</span>
                  <span>${o.enabled?"Yes":"No"}</span>
                </div>
                <div class="detail-row">
                  <span>Device Plugged:</span>
                  <span>${o.plugged?"Yes":"No"}</span>
                </div>
                <div class="detail-row">
                  <span>Device Powered:</span>
                  <span>${o.powered?"Yes":"No"}</span>
                </div>
                ${o.deviceInfo.manufacturer||o.deviceInfo.mac_address||o.deviceInfo.ip_address?B`
                  ${o.deviceInfo.manufacturer?B`
                    <div class="detail-row">
                      <span>Manufacturer:</span>
                      <span><strong>${o.deviceInfo.manufacturer}</strong></span>
                    </div>
                  `:""}
                  ${o.deviceInfo.ip_address?B`
                    <div class="detail-row">
                      <span>IP Address:</span>
                      <span style="font-family: monospace;">${o.deviceInfo.ip_address}</span>
                    </div>
                  `:o.deviceInfo.manufacturer?B`
                    <div class="detail-row">
                      <span 
                        class="tooltip-trigger"
                        @mouseenter=${t=>this._showTooltip(t,"Device detected but has no IP address. Possible causes: DHCP server not running, static IP configuration, or network issue.")}
                        @mouseleave=${()=>this._hideTooltip()}
                      >IP Address:</span>
                      <span style="color: var(--warning-color, #FF9800);">Not assigned</span>
                    </div>
                  `:""}
                  ${o.deviceInfo.mac_address?B`
                    <div class="detail-row">
                      <span>MAC Address:</span>
                      <span style="font-family: monospace;">${o.deviceInfo.mac_address}</span>
                    </div>
                  `:""}
                  ${o.deviceInfo.hostname?B`
                    <div class="detail-row">
                      <span>Hostname:</span>
                      <span>${o.deviceInfo.hostname}</span>
                    </div>
                  `:""}
                `:""}
              </div>
              <div class="details-actions">
                ${o.switchAvailable?B`
                  <button @click=${()=>this._togglePort(this._ports.find((t=>t.port===this._selectedPort)))} 
                          class="action-btn ${o.enabled?"disable":"enable"}">
                    ${o.enabled?"Disable Port":"Enable Port"}
                  </button>
                `:B`
                  <button disabled 
                          class="action-btn disabled" 
                          title="Enable/Disable not supported for add-on boards (kernel driver limitation)">
                    Enable/Disable Unavailable
                  </button>
                `}
                <button @click=${()=>this._resetPort(this._ports.find((t=>t.port===this._selectedPort)))} 
                        class="action-btn reset">
                  Reset Port
                </button>
              </div>
            </div>
          `:""}
        </div>
        
        <!-- Custom Tooltip -->
        ${this._tooltipVisible?B`
          <div 
            class="custom-tooltip" 
            style="left: ${this._tooltipX}px; top: ${this._tooltipY}px;"
          >
            <div class="tooltip-content">
              ${this._tooltipContent.split("\n").map((t=>B`
                ${t}<br/>
              `))}
            </div>
          </div>
        `:""}
      </ha-card>
    `}_renderPort(t){const e=this._getPortStatus(t);this._getPortCurrent(t);const s=this.hass.states[t.currentEntity],o=s?.attributes?.enabled??!1,i=this._selectedPort===t.port,r=this._loadingPorts.has(t.port);return B`
      <div 
        class="poe-port port-${e} ${o?"enabled":"disabled"} ${i?"selected":""} ${r?"loading":""}"
        @click=${e=>this._handlePortClick(e,t)}
        @contextmenu=${e=>this._handlePortClick(e,t)}
        title="Port ${t.port+1}: ${e} (${this._formatPowerDisplay(t)})
Click to select, click again to toggle on/off
Right-click to reset"
      >
        ${r?B`
          <div class="loading-overlay">
            <div class="spinner"></div>
          </div>
        `:""}
        <div class="port-number">P${t.port+1}</div>
        <div class="port-device">${t.linux_device||`${this.config.poe_set}-${t.port}`}</div>
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
          <div class="port-current">${this._formatPowerDisplay(t)}</div>
          <div class="port-status">${e}</div>
        </div>
      </div>
    `}_formatPowerDisplay(t){const e=this.hass.states[t.currentEntity];if(!e)return"0W";const s=parseFloat(e.state)||0,o=e.attributes?.allocated_power_watts;return o&&o>0?`${s.toFixed(1)}W / ${o.toFixed(1)}W`:`${s.toFixed(1)}W`}_getPoeClassDescription(t){return{0:"Class 0: Unclassified (legacy device, may draw up to port maximum)",1:"Class 1: 0.44-3.84W (low power devices)",2:"Class 2: 3.84-6.49W (medium power devices)",3:"Class 3: 6.49-12.95W (high power devices)",4:"Class 4: 12.95-25.5W (PoE+ devices, requires 802.3at)",5:"Class 5: 40-45W (PoE++ Type 3)",6:"Class 6: 51-60W (PoE++ Type 4)",7:"Class 7: 62-71.3W (PoE++ Type 4)",8:"Class 8: 71.3-90W (PoE++ Type 4, maximum)","?":"Class Unknown: Device not classified"}[t]||`Class ${t}: Unknown power class`}_formatDetailedPowerDisplay(t){const e=t.current||0,s=this.hass.states[t.entityId],o=s?.attributes?.allocated_power_watts,i=s?.attributes?.poe_class;if(o&&o>0){const t=o>0?(e/o*100).toFixed(0):"0";if("?"!==i){const s=this._getPoeClassDescription(i);return B`
          ${e.toFixed(1)}W / ${o.toFixed(1)}W
          <span 
            class="poe-class-label tooltip-trigger"
            @mouseenter=${t=>this._showTooltip(t,s)}
            @mouseleave=${()=>this._hideTooltip()}
            title="${s}"
          >
            Class ${i}
          </span>
          - ${t}% utilized
        `}return B`${e.toFixed(1)}W / ${o.toFixed(1)}W - ${t}% utilized`}return B`${e.toFixed(1)}W`}_renderServerStatus(){const t=this.hass.states["sensor.exaviz_vms_vms_server_status"];if(!t)return B``;const e=t?.state||"unknown",s=t?.last_updated,o=t?.attributes||{},i=o.server_host||"unknown",r=o.server_port||"unknown",a=o.connection_details||{},n=o.update_interval||30,l=o.last_update_success;let c="unknown",d="Unknown",p="🔸",h="";"connected"===e?(c="connected",d="Exaviz Server Connected",p="🟢",h=`Real server at ${i}:${r}`):"mock_poe_data"===e?(c="mock-poe",d="Exaviz Server Connected (PoE mocked)",p="🔵",h=`Real server at ${i}:${r} (mock PoE data)`):"disconnected"===e?(c="disconnected",d="Exaviz Server Disconnected",p="🔴",h=`Connection to ${i}:${r} failed`):"mock"===e&&(c="mock",d="Mock Server",p="🟡",h="Full mock mode - demo data only");const u=this._buildServerTooltip(o,a,e),g=l&&("connected"===e||"mock_poe_data"===e||"mock"===e),v=s?Math.floor((Date.now()-new Date(s).getTime())/1e3):null,f=v&&v>2*n;return B`
      <div class="server-status">
        <div class="status-item">
          <span class="label">Server Status:</span>
          <span 
            class="value status-${c} ${f?"stale":""} tooltip-trigger" 
            @mouseenter=${t=>this._showTooltip(t,u)}
            @mouseleave=${()=>this._hideTooltip()}
          >
            ${p} ${d}
            ${g?"":B`<span class="health-indicator">⚠️</span>`}
          </span>
        </div>
        <div class="status-item">
          <span class="label">Connection:</span>
          <span 
            class="value connection-info tooltip-trigger" 
            @mouseenter=${t=>this._showTooltip(t,h)}
            @mouseleave=${()=>this._hideTooltip()}
          >
            ${i}:${r}
            ${"mock_poe_data"===e?B`<span class="mock-indicator">(PoE mocked)</span>`:""}
          </span>
        </div>
        ${s?B`
          <div class="status-item">
            <span class="label">Last Check:</span>
            <span class="value ${f?"stale":""}">
              ${new Date(s).toLocaleTimeString()}
              ${f?B`<span class="stale-indicator">⏰</span>`:""}
            </span>
          </div>
        `:""}
        ${this._renderServerHealthIndicator(o,v,n)}
      </div>
    `}_buildServerTooltip(t,e,s){const o=[];return o.push(`🌐 Server: ${t.server_host||"unknown"}:${t.server_port||"unknown"}`),"mock"===s?(o.push("🎭 Mode: Full mock server (demo data)"),o.push("📊 PoE Data: Simulated (8 ports, realistic power consumption)"),o.push("⚡ Hardware: Mock PoE+ capable hardware"),o.push("🔄 Updates: Every 30 seconds with dynamic data")):"mock_poe_data"===s?(o.push("🎭 Mode: Real server + mock PoE data"),o.push("✅ VMS Connected: Real Exaviz server"),o.push("📊 PoE Data: Simulated (real server lacks PoE implementation)"),o.push("⚡ Hardware: Mock 2x8 PoE+ ports configuration")):"connected"===s?(o.push("✅ Mode: Fully connected to real server"),o.push("📊 PoE Data: Real hardware data"),o.push("⚡ Hardware: Physical PoE+ switches")):o.push("❌ Status: Connection failed or unavailable"),void 0!==e.connected&&o.push("🔗 Connected: "+(e.connected?"Yes":"No")),void 0!==e.authenticated&&o.push("🔐 Authenticated: "+(e.authenticated?"Yes":"No")),e.update_count&&o.push(`📈 Updates: ${e.update_count}`),e.error_count&&o.push(`❌ Errors: ${e.error_count}`),t.update_interval&&o.push(`⏱️ Update Interval: ${t.update_interval}s`),void 0!==t.last_update_success&&o.push("✅ Last Update: "+(t.last_update_success?"Success":"Failed")),o.join("\n")}_renderServerHealthIndicator(t,e,s){const o=t.connection_details?.error_count||0,i=t.connection_details?.update_count||0,r=i>0?((i-o)/i*100).toFixed(1):"100.0";return o>0||e&&e>2*s?B`
        <div class="status-item health-warning">
          <span class="label">Health:</span>
          <span 
            class="value tooltip-trigger" 
            @mouseenter=${t=>this._showTooltip(t,"Connection health information\nErrors may indicate network issues or server problems")}
            @mouseleave=${()=>this._hideTooltip()}
          >
            ${o>0?B`${o} errors`:""}
            ${e&&e>2*s?B`(${e}s since update)`:""}
            Success: ${r}%
          </span>
        </div>
      `:B``}_showTooltip(t,e){const s=t.target.getBoundingClientRect();this._tooltipContent=e,this._tooltipX=s.left+s.width/2,this._tooltipY=s.top-10,this._tooltipVisible=!0}_hideTooltip(){this._tooltipVisible=!1}static get styles(){return n`
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
    `}};t([pt({attribute:!1}),e("design:type",Object)],ut.prototype,"hass",void 0),t([pt(),e("design:type",Object)],ut.prototype,"config",void 0),t([ht(),e("design:type",Array)],ut.prototype,"_ports",void 0),t([ht(),e("design:type",Object)],ut.prototype,"_selectedPort",void 0),t([ht(),e("design:type",Boolean)],ut.prototype,"_tooltipVisible",void 0),t([ht(),e("design:type",String)],ut.prototype,"_tooltipContent",void 0),t([ht(),e("design:type",Number)],ut.prototype,"_tooltipX",void 0),t([ht(),e("design:type",Number)],ut.prototype,"_tooltipY",void 0),t([ht(),e("design:type",Set)],ut.prototype,"_loadingPorts",void 0),ut=t([(t=>(e,s)=>{void 0!==s?s.addInitializer((()=>{customElements.define(t,e)})):customElements.define(t,e)})("exaviz-poe-card")],ut),window.customCards=window.customCards||[],window.customCards.push({type:"exaviz-poe-card",name:"Exaviz PoE Management Card",description:"Comprehensive PoE port management with visual status indicators and detailed controls"}),console.info("%c  EXAVIZ-POE-CARD  %c  v2.0.0  ","color: orange; font-weight: bold; background: black","color: white; font-weight: bold; background: dimgray"),console.info("%c🔌 EXAVIZ POE CARD %c2.0.0 ","color: white; background: #90FF80; font-weight: bold;","color: #90FF80; background: white; font-weight: bold;"),console.info("Exaviz PoE Card loaded");
