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
        <div v-for="part in product.parts" :key="part.name" class="part-card">
          <div class="part-header">
            <h4 class="part-name">{{ part.titel || part.name }}</h4>
            <div v-if="selected[part.name]" class="selected-indicator">
              <span class="selected-label">Selected:</span>
              <span class="selected-value">{{ selected[part.name] }}</span>
            </div>
          </div>
          
          <div class="options-container">
            <div class="options-label">Available options:</div>
            <div class="options-grid">
              <div v-for="opt in part.value" :key="opt"
                   :class="['option-chip', selected[part.name] === opt ? 'option-selected' : 'option-available']"
                   @click="selectOption(part.name, opt)">
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
const product = ref(
  
{
name: 'Wood Table',
parts: [
  {"id":0,"uniqueId":"1588942193773","name":"platte_thickness","titel":"Stärke","value":["16 mm","19 mm","25 mm","8 mm"]},{"id":1,"uniqueId":"1614246937544","name":"texture_direction","titel":"Maserungsrichtung ","value":["Vertikal","Horizontal"]},{"id":2,"uniqueId":"1709586217030","name":"sideschoice_of_edges1","titel":"Seitenauswahl der Kanten :","value":["oben","rechts","unten","links"]},{"id":3,"uniqueId":"1709635825282","name":"edge_processing1","titel":"Kantenbearbeitung:","value":["Ohne","Weiß Hochglanz","Schwarz Hochglanz","Ahorn Natur","Alu Geschliffen","Anthrazit","Atollblau","Beige","Beton dunkel","Beton hell","Eiche Salzburg","Eierschale","Esche Taormina Vogue","Grau","Hellgrau","Kernapfel","Kirsche Acco","Limone","Lipstick","Murnau Ahorn","Niagara Eiche hell","Nussbaum","Onyx","Rose","Samerbergbuche","Schiefer","Schwarz","Seablue","Silber","Sonoma Eiche","Taubenblau","Türkis","Walnuss Venedig","Weiss","Wenge Classic","Marmor Weiss","Marmor Dunkel Grau","Marmor Hell Grau","Swiss Elm Kalt","Aloe Green","Dive Blue","Efeu","Eternal Oak","Jaffa Orange","Lamella Cream","Lamella Terra","Marineblau","Olive","Pistazien Grün","Astfichte","Cappuccino","Cashmere","Coco Tweed Creme","Fichte Weiß","Frontweiss","MellowPine White","Stonetex Black"]},{"id":4,"uniqueId":"1709232334992","name":"st_amount_socket","titel":"Steckdosenbohrungen","value":["Keine","Eine","Zwei","Drei","Vier","Fünf"]},{"id":5,"uniqueId":"1709232556743","name":"rows_of_holes_for_shelves","titel":"Lochreihen für Regalbretter","value":["Keine","lange Seite - 2 Reihen für Regalbretter - pro Platte","kurze Seite - 2 Reihen für Regalbretter - pro Platte"]},{"id":6,"uniqueId":"1709232830865","name":"hinges_drill_hole","titel":"Scharniere inkl. Bohrung","value":["Keine","Eckanschlag 2 Bohrungen und 2 Scharniere","Mittelwand 2 Bohrungen und 2 Scharniere","Einliegend 2 Bohrungen und 2 Scharniere","Eckanschlag 3 Bohrungen und 3 Scharniere","Mittelwand 3 Bohrungen und 3 Scharniere","Einliegend 3 Bohrungen und 3 Scharniere","Eckanschlag 4 Bohrungen und 4 Scharniere","Mittelwand 4 Bohrungen und 4 Scharniere","Einliegend 4 Bohrungen und 4 Scharniere","Eckanschlag 5 Bohrungen und 5 Scharniere","Mittelwand 5 Bohrungen und 5 Scharniere","Einliegend 5 Bohrungen und 5 Scharniere"]}],
LANGUAGE: 'Egnlish'
}
)



const selected = ref({})

const room = ref(null)
const connected = ref(false)
const joining = ref(false)
const status = ref('')
const isClient = ref(false)

// const API_BASE = import.meta.env.VITE_API_URL || 'http://20.109.0.103:8090' // Vite env

//http://config.verkaufs-plattformen.de:8090
const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8090' 
onMounted(() => {
  // Check if we're in a browser environment
  isClient.value = typeof window !== 'undefined' && typeof navigator !== 'undefined'
  if (!isClient.value) {
    status.value = 'Browser environment required'
  }

  // Initialize selected for each part
  product.value.parts.forEach(part => {
    if (!(part.name in selected.value)) {
      selected.value[part.name] = null
    }
  })
})

// Check if we're in a browser environment
onMounted(() => {
  isClient.value = typeof window !== 'undefined' && typeof navigator !== 'undefined'
  if (!isClient.value) {
    status.value = 'Browser environment required'
  }
})


// Helper function to get status indicator class
function getStatusClass() {
  if (connected.value) return 'status-connected'
  if (joining.value) return 'status-connecting'
  if (status.value.includes('Failed')) return 'status-error'
  return 'status-idle'
}

// Add method to select option
function selectOption(partName, opt) {
  selected.value = { ...selected.value, [partName]: opt }
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

r.on(RoomEvent.DataReceived, (payload, participant, topic) => {
  console.log('____DataReceived event triggered____');
  try {
    console.log('DataReceived raw', { topic, payload, participant })  
    const msg = JSON.parse(new TextDecoder().decode(payload))
    console.log('DataReceived parsed', { topic, msg })
    
    if (msg?.type === 'config:update') {
      const next = { ...selected.value }
      
      // Handle both single object and array formats
      const items = Array.isArray(msg.items_configured) 
        ? msg.items_configured 
        : [msg.items_configured]
      
      console.log('Processing items:', items)
      
      for (const item of items) {
        if (item?.name && item?.value) {
          console.log(`Setting ${item.name} = ${item.value}`)
          next[item.name] = item.value
        }
      }
      
      selected.value = next
      status.value = `Updated by voice: ${items.map(i => i.name).join(', ')}`
      console.log('Updated selected:', selected.value)
    }
  } catch (e) {
    console.error('DataReceived parse error:', e)
  }
})

    r.on(RoomEvent.ParticipantConnected, (p) => {
  console.log('remote joined', p.identity)
})
r.on(RoomEvent.ParticipantDisconnected, (p) => {
  console.log('remote left', p.identity)
})
room.value.remoteParticipants.forEach((p, id) => {             // Map iteration
  console.log('remote', id, p.identity)
})

console.log("remote participants : ", room.value.remoteParticipants);
    console.log('Connecting to LiveKit', { livekitUrl, roomName , token})
  

    connected.value = true
    status.value = 'Connected. Publishing mic...'

    // Check again before creating audio track
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw new Error('Microphone access not available')
    }

    // Publish mic track with basic processing [11]

    // Auto-play agent audio when the agent publishes TTS
    r.on(RoomEvent.TrackSubscribed, (track, pub, participant) => {
      console.log('TrackSubscribed', { track, pub, participant })
      if (track.kind === 'audio') {
        const el = document.createElement('audio')
        el.autoplay = true,

        track.attach(el)
      }
    })

    if (!r.canPlayAudio) {
  console.log("started audio")
}
r.on(RoomEvent.AudioPlaybackStatusChanged, () => {
  if (!r.canPlayAudio) {
    console.log("Audio playback requires user interaction");
    // show a button and call r.startAudio() on click
  }
});



    r.on(RoomEvent.TrackUnsubscribed, (track, pub, participant) => {
      console.log('**(*(*(*((*(*TrackUnsubscribed', { track, pub, participant })
      
    })

    console.log('local', room.value.localParticipant)              // OK after connect
    console.log("remote participants : ", room.value.remoteParticipants);



    // console.log("remote participants : ", room.remoteParticipants);
    // console.log("local participants : ", room.localParticipant);

    // room.remoteParticipants?.forEach((participant) => {
    //   participant.trackPublications.forEach((publication) => {
    //     publication.setSubscribed(true);
    //   });
    // });


    await r.connect(livekitUrl, token) // Connect to room with token [13]
    await r.startAudio(); // must be within a user gesture
    const mic = await createLocalAudioTrack({
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true
    })
    await r.localParticipant.publishTrack(mic)

    r.remoteParticipants.forEach((p) => {
  p.audioTrackPublications.forEach((pub) => {
    if (!pub.isSubscribed) pub.setSubscribed(true);
    const tr = pub.audioTrack;
    if (tr) {
      const el = new Audio();
      el.autoplay = true;
      tr.attach(el);
    }
  });
});
  joining.value = false
  status.value = "Connected. You can start speaking now."
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