import { reactive, ref, type Ref } from "vue";

import type { CollabIdentity, SignalPayload } from "@/features/collab/types";

// Public STUN only: browsers learn their public address and then talk directly. No TURN relay,
// nothing for the operator to run. Offline, peers on one LAN or VPN still connect locally.
const ICE_SERVERS: RTCIceServer[] = [
  { urls: "stun:stun.cloudflare.com:3478" },
  { urls: "stun:stun.l.google.com:19302" },
];
const CONNECT_TIMEOUT_MS = 10_000;
const SPEAKING_THRESHOLD = 0.04;
const SPEAKING_POLL_MS = 150;

interface PeerLink {
  pc: RTCPeerConnection;
  polite: boolean;
  makingOffer: boolean;
  ignoreOffer: boolean;
  audio: HTMLAudioElement;
  analyser: AnalyserNode | null;
  timeout: ReturnType<typeof setTimeout> | null;
}

export interface VoiceDeps {
  me: Ref<CollabIdentity | null>;
  micOn: Ref<boolean>;
  sendSignal: (to: string, data: SignalPayload) => void;
  peerSids: () => string[];
}

export interface Voice {
  micError: Ref<string | null>;
  autoplayBlocked: Ref<boolean>;
  /** Session ids currently speaking, this tab's included. */
  speaking: Set<string>;
  /** Session ids whose audio connection failed. */
  failed: Set<string>;
  toggleMic(): Promise<void>;
  reconcile(): void;
  handleSignal(fromSid: string, data: SignalPayload): Promise<void>;
  closePeer(sid: string): void;
  closeAll(): void;
  resumeAudio(): void;
  reset(): void;
}

export function createVoice({ me, micOn, sendSignal, peerSids }: VoiceDeps): Voice {
  const micError = ref<string | null>(null);
  const autoplayBlocked = ref(false);
  const speaking: Set<string> = reactive(new Set<string>());
  const failed: Set<string> = reactive(new Set<string>());
  const links = new Map<string, PeerLink>();
  let localStream: MediaStream | null = null;
  let localAnalyser: AnalyserNode | null = null;
  let audioContext: AudioContext | null = null;
  let speakingTimer: ReturnType<typeof setInterval> | null = null;

  function context(): AudioContext {
    if (!audioContext) audioContext = new AudioContext();
    return audioContext;
  }

  function level(analyser: AnalyserNode): number {
    const samples = new Float32Array(analyser.fftSize);
    analyser.getFloatTimeDomainData(samples);
    let sum = 0;
    for (const sample of samples) sum += sample * sample;
    return Math.sqrt(sum / samples.length);
  }

  function mark(target: Set<string>, sid: string, on: boolean): void {
    if (on) target.add(sid);
    else target.delete(sid);
  }

  function updateSpeaking(): void {
    const mine = me.value?.sid;
    if (mine) {
      const loud = localAnalyser !== null && level(localAnalyser) > SPEAKING_THRESHOLD;
      mark(speaking, mine, micOn.value && loud);
    }
    for (const [sid, link] of links) {
      mark(speaking, sid, link.analyser !== null && level(link.analyser) > SPEAKING_THRESHOLD);
    }
  }

  function analyse(stream: MediaStream): AnalyserNode {
    const analyser = context().createAnalyser();
    analyser.fftSize = 512;
    context().createMediaStreamSource(stream).connect(analyser);
    if (!speakingTimer) speakingTimer = setInterval(updateSpeaking, SPEAKING_POLL_MS);
    return analyser;
  }

  function clearLinkTimer(link: PeerLink): void {
    if (link.timeout) clearTimeout(link.timeout);
    link.timeout = null;
  }

  function attachLocalTracks(link: PeerLink): void {
    if (!localStream) return;
    const sending = new Set(link.pc.getSenders().map((sender) => sender.track));
    for (const track of localStream.getTracks()) {
      if (!sending.has(track)) link.pc.addTrack(track, localStream);
    }
  }

  function openLink(sid: string): PeerLink {
    const existing = links.get(sid);
    if (existing) return existing;
    const pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });
    const audio = new Audio();
    audio.autoplay = true;
    const link: PeerLink = {
      pc,
      polite: (me.value?.sid ?? "") < sid,
      makingOffer: false,
      ignoreOffer: false,
      audio,
      analyser: null,
      timeout: null,
    };
    links.set(sid, link);
    pc.onnegotiationneeded = async (): Promise<void> => {
      try {
        link.makingOffer = true;
        await pc.setLocalDescription();
        if (pc.localDescription) sendSignal(sid, { description: pc.localDescription.toJSON() });
      } catch {
        failed.add(sid);
      } finally {
        link.makingOffer = false;
      }
    };
    pc.onicecandidate = ({ candidate }): void => {
      if (candidate) sendSignal(sid, { candidate: candidate.toJSON() });
    };
    pc.ontrack = ({ streams }): void => {
      const [stream] = streams;
      if (!stream) return;
      audio.srcObject = stream;
      audio.play().catch(() => {
        autoplayBlocked.value = true;
      });
      link.analyser = analyse(stream);
    };
    pc.onconnectionstatechange = (): void => {
      if (pc.connectionState === "connected") {
        failed.delete(sid);
        clearLinkTimer(link);
      } else if (pc.connectionState === "failed") {
        failed.add(sid);
      }
    };
    link.timeout = setTimeout(() => {
      if (pc.connectionState !== "connected") failed.add(sid);
    }, CONNECT_TIMEOUT_MS);
    attachLocalTracks(link);
    return link;
  }

  /** Perfect negotiation: the impolite side ignores a colliding offer, the polite side yields. */
  async function handleSignal(fromSid: string, data: SignalPayload): Promise<void> {
    const isOffer = data.description?.type === "offer";
    const link = isOffer ? openLink(fromSid) : links.get(fromSid);
    if (!link) return;
    const { pc } = link;
    try {
      if (data.description) {
        const collision = isOffer && (link.makingOffer || pc.signalingState !== "stable");
        link.ignoreOffer = !link.polite && collision;
        if (link.ignoreOffer) return;
        await pc.setRemoteDescription(data.description);
        if (isOffer) {
          await pc.setLocalDescription();
          if (pc.localDescription) {
            sendSignal(fromSid, { description: pc.localDescription.toJSON() });
          }
        }
      } else if (data.candidate) {
        try {
          await pc.addIceCandidate(data.candidate);
        } catch (error) {
          if (!link.ignoreOffer) throw error;
        }
      }
    } catch {
      failed.add(fromSid);
    }
  }

  function stopMic(): void {
    for (const link of links.values()) {
      for (const sender of link.pc.getSenders()) {
        if (sender.track) link.pc.removeTrack(sender);
      }
    }
    localStream?.getTracks().forEach((track) => track.stop());
    localStream = null;
    localAnalyser = null;
    micOn.value = false;
    const mine = me.value?.sid;
    if (mine) speaking.delete(mine);
  }

  async function toggleMic(): Promise<void> {
    if (micOn.value) {
      stopMic();
      return;
    }
    // Browsers offer the microphone only on https and localhost, not on a LAN address over http.
    if (!window.isSecureContext || !navigator.mediaDevices) {
      micError.value = "The microphone needs Heym on https or localhost";
      return;
    }
    try {
      localStream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch {
      micError.value = "Microphone access was blocked";
      return;
    }
    micError.value = null;
    micOn.value = true;
    localAnalyser = analyse(localStream);
    reconcile();
  }

  function closePeer(sid: string): void {
    const link = links.get(sid);
    if (!link) return;
    clearLinkTimer(link);
    link.pc.close();
    link.audio.srcObject = null;
    links.delete(sid);
    speaking.delete(sid);
    failed.delete(sid);
  }

  function closeAll(): void {
    for (const sid of [...links.keys()]) closePeer(sid);
  }

  /** Links stay open until the peer leaves; with the mic on, every peer gets this track. */
  function reconcile(): void {
    const present = new Set(peerSids());
    for (const sid of [...links.keys()]) {
      if (!present.has(sid)) closePeer(sid);
    }
    if (!micOn.value) return;
    for (const sid of present) attachLocalTracks(openLink(sid));
  }

  function resumeAudio(): void {
    autoplayBlocked.value = false;
    void context().resume();
    for (const link of links.values()) {
      link.audio.play().catch(() => {
        autoplayBlocked.value = true;
      });
    }
  }

  function reset(): void {
    stopMic();
    closeAll();
    if (speakingTimer) clearInterval(speakingTimer);
    speakingTimer = null;
    void audioContext?.close();
    audioContext = null;
    micError.value = null;
    autoplayBlocked.value = false;
    speaking.clear();
    failed.clear();
  }

  return {
    micError,
    autoplayBlocked,
    speaking,
    failed,
    toggleMic,
    reconcile,
    handleSignal,
    closePeer,
    closeAll,
    resumeAudio,
    reset,
  };
}
