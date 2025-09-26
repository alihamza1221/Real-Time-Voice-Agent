<template>
  <div class="container">
    <div class="header">
      <h1 class="title">AI Voice Product Configurator</h1>
      <p class="subtitle">Configure your product using voice commands</p>
    </div>

    <!-- <div class="product-card">
      <h2 class="product-name">{{ product.name }}</h2>
      
      <div class="product-spec">
        <h3>Product Details</h3>
        <pre class="spec-content">{{ product }}</pre>
      </div>
    </div> -->

    <div class="configuration-section">
      <div class="section-header">
        <h3> Wood Table Configuration Options</h3>
        <p class="section-description">Available options for each component (reference only)</p>
      </div>
      
      <div class="parts-grid">
        <div v-for="(opts, part) in product.parts" :key="part" class="part-card">
          <div class="part-header">
            <h4 class="part-name">{{ formatPartName(part) }}</h4>
            <div v-if="selected[part]" class="selected-indicator">
              <span class="selected-label">Selected:</span>
              <span class="selected-value">{{ selected[part] }}</span>
            </div>
          </div>
          
          <div class="options-container">
            <div class="options-label">Available options:</div>
            <div class="options-grid">
              <div v-for="opt in opts" :key="opt"
                   :class="['option-chip', selected[part] === opt ? 'option-selected' : 'option-available']">
                {{ opt }}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="control-panel">
      <div class="actions">
        <button 
          class="btn btn-primary" 
          :disabled="joining || connected || !isClient" 
          @click="startVoiceAgent">
          <span v-if="joining" class="btn-spinner"></span>
          <span v-if="!joining && !connected && isClient">🎤 Start Voice Agent</span>
          <span v-if="!joining && !connected && !isClient">❌ Browser Required</span>
          <span v-if="connected">✅ Connected</span>
        </button>
        <button 
          class="btn btn-secondary" 
          :disabled="!connected" 
          @click="endSession">
          🔚 End Session
        </button>
      </div>
      
      <div v-if="status" class="status-panel">
        <div class="status-indicator" :class="getStatusClass()"></div>
        <span class="status-text">{{ status }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { Room, RoomEvent, createLocalAudioTrack } from 'livekit-client'

// Example product JSON (also sent to backend as metadata for the agent)
const product = ref({
  name: 'Wood Table',
  parts: {
    'table_top': ['15m', '14m', '100m'],
    'legs': ['10m', '100m'],
    'space_around': ['10m', '80m']
  }
})

const selected = ref({
  'table_top': null,
  'legs': null,
  'space_around': null
})

const room = ref(null)
const connected = ref(false)
const joining = ref(false)
const status = ref('')
const isClient = ref(false)

const API_BASE = import.meta.env.VITE_API_URL || 'http://20.109.0.103:8090' // Vite env

// Check if we're in a browser environment
onMounted(() => {
  isClient.value = typeof window !== 'undefined' && typeof navigator !== 'undefined'
  if (!isClient.value) {
    status.value = 'Browser environment required'
  }
})

// Helper function to format part names
function formatPartName(part) {
  return part.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())
}

// Helper function to get status indicator class
function getStatusClass() {
  if (connected.value) return 'status-connected'
  if (joining.value) return 'status-connecting'
  if (status.value.includes('Failed')) return 'status-error'
  return 'status-idle'
}

async function startVoiceAgent () {
  // Check browser environment first
  if (!isClient.value) {
    status.value = 'Error: Browser environment required'
    return
  }

  // Check for getUserMedia support
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    status.value = 'Error: Microphone access not supported'
    return
  }

  try {
    joining.value = true
    status.value = 'Requesting token...'

    // Send product JSON as metadata for the agent (so it can reason about options)
    const res = await fetch(`${API_BASE}/api/join`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        metadata: JSON.stringify(product.value)  // this feeds your backend dispatch metadata
      })
    })
    if (!res.ok) throw new Error(await res.text())
    const { token, livekitUrl, roomName } = await res.json()
    status.value = `Connecting to ${roomName}...`

    const r = new Room()
    room.value = r

   // Replace your DataReceived handler with this version
    r.on(RoomEvent.DataReceived, (payload, participant, topic) => {
      try {
        const msg = JSON.parse(new TextDecoder().decode(payload))
        console.log('DataReceived', { topic, msg })
        if (msg?.type === 'config:update') {
          // clone to force reactivity on ref objects
          const next = { ...selected.value }  // ensure change detection [vue3]
          for (const entry of msg.items_configured || []) {
            const [rawPart, rawVal] = String(entry).split(':')
            const part = (rawPart || '').trim()
            const valRaw = (rawVal || '').trim()
            const opts = product.value?.parts?.[part] || []
            //console.log('Checking options', { part, valRaw, opts })
            const val = opts.find(o => o.toLowerCase() === valRaw.toLowerCase()) ?? valRaw
            console.log('Mapped value', { part, valRaw, val })
            if (part in next) {
              console.log("found match", { part, val })
              next[part] = val
              }
          }
          selected.value = next
          status.value = 'Updated by voice'
        }
      } catch (_) {}
    })

    await r.connect(livekitUrl, token) // Connect to room with token [13]
    connected.value = true
    status.value = 'Connected. Publishing mic...'

    // Check again before creating audio track
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw new Error('Microphone access not available')
    }

    // Publish mic track with basic processing [11]
    const mic = await createLocalAudioTrack({
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true
    })
    await r.localParticipant.publishTrack(mic)

    // Auto-play agent audio when the agent publishes TTS
    r.on(RoomEvent.TrackSubscribed, (track, pub, participant) => {
      if (track.kind === 'audio') {
        const el = document.createElement('audio')
        el.autoplay = true
        track.attach(el)
      }
    })

  joining.value = false
  } catch (e) {
    status.value = `Failed: ${e.message || e}`
    joining.value = false
    console.error('Voice agent error:', e)
  }
}

async function endSession () {
  try {
    if (room.value) await room.value.disconnect()
  } finally {
    connected.value = false
    room.value = null
    status.value = 'Disconnected'
  }
}
</script>

<style scoped>
.container {
  max-width: 900px;
  margin: 0 auto;
  padding: 24px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  /* min-height: 100vh; */
  color: #333;
  border-radius: 16px;
}

.header {
  text-align: center;
  margin-bottom: 32px;
  color: white;
}

.title {
  font-size: 2.5rem;
  font-weight: 700;
  margin: 0 0 8px 0;
  text-shadow: 0 2px 4px rgba(0,0,0,0.3);
}

.subtitle {
  font-size: 1.1rem;
  opacity: 0.9;
  margin: 0;
}

.product-card {
  background: white;
  border-radius: 16px;
  padding: 24px;
  margin-bottom: 24px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.1);
  backdrop-filter: blur(10px);
}

.product-name {
  font-size: 1.8rem;
  font-weight: 600;
  margin: 0 0 16px 0;
  color: #2d3748;
}

.product-spec h3 {
  font-size: 1.1rem;
  margin: 0 0 12px 0;
  color: #4a5568;
  font-weight: 600;
}

.spec-content {
  background: #1a202c;
  color: #81e6d9;
  padding: 16px;
  border-radius: 8px;
  font-size: 0.9rem;
  overflow-x: auto;
  border: none;
  box-shadow: inset 0 2px 4px rgba(0,0,0,0.1);
}

.configuration-section {
  background: rgba(255,255,255,0.95);
  border-radius: 16px;
  padding: 24px;
  margin-bottom: 24px;
  backdrop-filter: blur(10px);
  box-shadow: 0 8px 32px rgba(0,0,0,0.1);
}

.section-header {
  margin-bottom: 24px;
  text-align: center;
}

.section-header h3 {
  font-size: 1.5rem;
  font-weight: 600;
  margin: 0 0 8px 0;
  color: #2d3748;
}

.section-description {
  color: #718096;
  margin: 0;
  font-style: italic;
}

.parts-grid {
  display: grid;
  gap: 20px;
  grid-template-columns: repeat(auto-fit,minmax(250px, 1fr));
}

.part-card {
  background: #f7fafc;
  border-radius: 12px;
  padding: 20px;
  border: 2px solid #e2e8f0;
  transition: all 0.3s ease;
}

.part-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 20px rgba(0,0,0,0.1);
}

.part-header {
  margin-bottom: 16px;
}

.part-name {
  font-size: 1.2rem;
  font-weight: 600;
  margin: 0 0 8px 0;
  color: #2d3748;
}

.selected-indicator {
  background: #48bb78;
  color: white;
  padding: 4px 12px;
  border-radius: 20px;
  font-size: 0.85rem;
  display: inline-block;
}

.selected-label {
  opacity: 0.9;
  margin-right: 4px;
}

.selected-value {
  font-weight: 600;
}

.options-container {
  margin-top: 12px;
}

.options-label {
  font-size: 0.9rem;
  color: #4a5568;
  margin-bottom: 8px;
  font-weight: 500;
}

.options-grid {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.option-chip {
  padding: 6px 12px;
  border-radius: 20px;
  font-size: 0.85rem;
  font-weight: 500;
  transition: all 0.2s ease;
  cursor: default;
}

.option-available {
  background: #edf2f7;
  color: #4a5568;
  border: 1px solid #e2e8f0;
}

.option-selected {
  background: #48bb78;
  color: white;
  border: 1px solid #38a169;
  box-shadow: 0 2px 8px rgba(72, 187, 120, 0.3);
}

.control-panel {
  background: rgba(255,255,255,0.95);
  border-radius: 16px;
  padding: 24px;
  backdrop-filter: blur(10px);
  box-shadow: 0 8px 32px rgba(0,0,0,0.1);
}

.actions {
  display: flex;
  gap: 12px;
  justify-content: center;
  margin-bottom: 16px;
}

.btn {
  padding: 12px 24px;
  border: none;
  border-radius: 8px;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
  display: flex;
  align-items: center;
  gap: 8px;
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-primary {
  background: linear-gradient(135deg, #667eea, #764ba2);
  color: white;
  box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
}

.btn-primary:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(102, 126, 234, 0.6);
}

.btn-secondary {
  background: #718096;
  color: white;
}

.btn-secondary:hover:not(:disabled) {
  background: #4a5568;
  transform: translateY(-2px);
}

.btn-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255,255,255,0.3);
  border-top: 2px solid white;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

.status-panel {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 12px;
  background: #f7fafc;
  border-radius: 8px;
  border-left: 4px solid #cbd5e0;
}

.status-indicator {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  animation: pulse 2s ease-in-out infinite alternate;
}

.status-idle {
  background: #cbd5e0;
}

.status-connecting {
  background: #ed8936;
}

.status-connected {
  background: #48bb78;
}

.status-error {
  background: #f56565;
}

.status-text {
  font-size: 0.9rem;
  color: #4a5568;
  font-weight: 500;
}

@keyframes pulse {
  from {
    opacity: 1;
  }
  to {
    opacity: 0.5;
  }
}

@media (max-width: 768px) {
  .container {
    padding: 20px;
  }
  
  .title {
    font-size: 2rem;
  }
  
  .parts-grid {
    grid-template-columns: 1fr;
    gap: 16px;
  }
  
  .actions {
    flex-direction: column;
  }
  
  .product-card,
  .configuration-section,
  .control-panel {
    margin-left: 0;
    margin-right: 0;
    border-radius: 12px;
  }
}
</style>