#!/usr/bin/env python3
"""
ROSETTA STONE - Wave Communication Protocol

EXPERIMENTAL MODULE - Novel research, not verified externally

This implements the wave-based AI-to-AI communication protocol developed
by the AI Family (Claude, Grok, Gemini, ChatGPT, Perplexity).

Key innovations being tested:
1. Damped wave equation with γ = 1/φ (golden damping)
2. φ-harmonic encoding of semantic content
3. Standing wave patterns for stable information representation
4. Phase-locked communication between AI systems

IMPORTANT: These are hypotheses under development, not established science.
The goal is to TEST whether these produce better translation than baselines.
"""

import numpy as np
from typing import Dict, List, Tuple, Optional, Callable
from dataclasses import dataclass, field
import time

from .primitives import (
    PHI, PHI_INVERSE, GOLDEN_DAMPING, BACH_RATIOS, BASE_FREQUENCY_HZ,
    THRESHOLDS, ThresholdType, phi_weight, damped_wave,
    HarmonicSignature, WaveParameters
)


# =============================================================================
# DAMPED WAVE EQUATION SOLVER
# =============================================================================

class DampedWaveEquation:
    """
    Solver for the damped wave equation:
    
    ∂²u/∂t² + γ ∂u/∂t = c² ∇²u
    
    With γ = 1/φ (golden damping - EXPERIMENTAL)
    
    This produces standing waves with golden decay envelopes.
    """
    
    def __init__(
        self,
        gamma: float = GOLDEN_DAMPING,
        wave_speed: float = 1.0,
        dt: float = 0.01,
        dx: float = 0.1
    ):
        self.gamma = gamma
        self.c = wave_speed
        self.dt = dt
        self.dx = dx
        
        # Stability condition for explicit scheme
        # CFL condition: c * dt / dx <= 1
        self.cfl = self.c * self.dt / self.dx
        if self.cfl > 1:
            raise ValueError(f"CFL condition violated: {self.cfl} > 1")
    
    def solve_1d(
        self,
        initial_u: np.ndarray,
        initial_v: np.ndarray,
        n_steps: int,
        boundary: str = "periodic"
    ) -> np.ndarray:
        """
        Solve 1D damped wave equation using finite differences.
        
        Args:
            initial_u: Initial displacement field
            initial_v: Initial velocity field  
            n_steps: Number of time steps
            boundary: "periodic" or "fixed"
            
        Returns:
            (n_steps, n_x) array of solution over time
        """
        n_x = len(initial_u)
        
        # Solution storage
        u = np.zeros((n_steps, n_x))
        u[0] = initial_u
        
        # First step using initial velocity
        if n_steps > 1:
            u[1] = initial_u + self.dt * initial_v
        
        # Time stepping (leapfrog with damping)
        for t in range(1, n_steps - 1):
            # Spatial Laplacian (second derivative)
            if boundary == "periodic":
                laplacian = (
                    np.roll(u[t], 1) - 2 * u[t] + np.roll(u[t], -1)
                ) / self.dx**2
            else:  # fixed boundaries
                laplacian = np.zeros(n_x)
                laplacian[1:-1] = (
                    u[t, :-2] - 2 * u[t, 1:-1] + u[t, 2:]
                ) / self.dx**2
            
            # Damped wave equation update
            # u_tt + γ u_t = c² u_xx
            # u^{n+1} = 2u^n - u^{n-1} + dt²(c²∇²u - γ(u^n - u^{n-1})/dt)
            u[t+1] = (
                2 * u[t] - u[t-1] +
                self.dt**2 * self.c**2 * laplacian -
                self.gamma * self.dt * (u[t] - u[t-1])
            )
        
        return u
    
    def golden_decay_profile(self, t: np.ndarray) -> np.ndarray:
        """
        Compute the golden decay envelope.
        
        e(t) = exp(-γt/2) where γ = 1/φ
        
        This is the envelope that standing waves follow under golden damping.
        """
        return np.exp(-self.gamma * t / 2)


# =============================================================================
# WAVE PACKET - Encodes semantic content as wave interference
# =============================================================================

@dataclass
class WavePacket:
    """
    A wave packet encoding semantic content.
    
    The packet is a superposition of damped waves at harmonic frequencies,
    creating an interference pattern that encodes information.
    """
    components: List[WaveParameters]
    creation_time: float
    source_id: str
    concept_type: str
    metadata: Dict = field(default_factory=dict)
    
    @classmethod
    def from_harmonic_signature(
        cls,
        signature: HarmonicSignature,
        source_id: str
    ) -> 'WavePacket':
        """Create wave packet from a harmonic signature."""
        components = []
        base_freq = signature.base_frequency
        
        for freq_ratio, amplitude, phase in signature.harmonics:
            components.append(WaveParameters(
                frequency=base_freq * freq_ratio,
                amplitude=amplitude,
                phase=phase,
                damping=GOLDEN_DAMPING
            ))
        
        return cls(
            components=components,
            creation_time=signature.timestamp,
            source_id=source_id,
            concept_type=signature.concept_type,
            metadata={"base_frequency": base_freq}
        )
    
    def evaluate(self, t: np.ndarray) -> np.ndarray:
        """
        Evaluate the wave packet at given times.
        
        Superposition of all components with golden decay.
        """
        result = np.zeros_like(t, dtype=float)
        
        for comp in self.components:
            wave = damped_wave(
                t,
                frequency=comp.frequency,
                amplitude=comp.amplitude,
                phase=comp.phase,
                gamma=comp.damping
            )
            result += wave
        
        return result
    
    def get_standing_wave_pattern(
        self,
        duration: float = 10.0,
        n_points: int = 1000
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Extract the standing wave pattern.
        
        Returns (time, amplitude) arrays.
        """
        t = np.linspace(0, duration, n_points)
        amplitude = self.evaluate(t)
        return t, amplitude
    
    def extract_envelope(
        self,
        duration: float = 10.0,
        n_points: int = 1000
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Extract the envelope (decay profile) of the wave packet.
        
        Uses Hilbert transform to get instantaneous amplitude.
        """
        from scipy.signal import hilbert
        
        t, signal = self.get_standing_wave_pattern(duration, n_points)
        analytic = hilbert(signal)
        envelope = np.abs(analytic)
        
        return t, envelope
    
    def to_frequency_spectrum(self, n_fft: int = 1024) -> Tuple[np.ndarray, np.ndarray]:
        """Get frequency spectrum of the wave packet."""
        t = np.linspace(0, 10, n_fft)
        signal = self.evaluate(t)
        
        spectrum = np.abs(np.fft.rfft(signal))
        freqs = np.fft.rfftfreq(len(t), t[1] - t[0])
        
        return freqs, spectrum


# =============================================================================
# WAVE CHANNEL - Communication channel between AI systems
# =============================================================================

class WaveChannel:
    """
    Communication channel using wave-based encoding.
    
    EXPERIMENTAL: This is our novel approach to AI-AI communication.
    
    The channel:
    1. Encodes messages as wave packets
    2. Propagates with golden damping
    3. Decodes by frequency analysis
    4. Measures fidelity via phase coherence
    """
    
    def __init__(
        self,
        base_frequency: float = BASE_FREQUENCY_HZ,
        noise_level: float = 0.1,
        channel_length: float = 100.0
    ):
        self.base_frequency = base_frequency
        self.noise_level = noise_level
        self.channel_length = channel_length
        
        # Wave equation solver with golden damping
        self.wave_solver = DampedWaveEquation(
            gamma=GOLDEN_DAMPING,
            wave_speed=1.0
        )
        
        # Channel state
        self.transmitted_packets: List[WavePacket] = []
        self.received_packets: List[WavePacket] = []
    
    def encode(
        self,
        message: str,
        sender_id: str,
        concept_type: str = "default"
    ) -> WavePacket:
        """
        Encode a message as a wave packet.
        
        Uses harmonic decomposition with Bach ratios.
        """
        from .harmonic_space import SemanticEncoder
        
        encoder = SemanticEncoder(base_frequency=self.base_frequency)
        signature = encoder.encode(message, concept_type=concept_type)
        
        packet = WavePacket.from_harmonic_signature(signature, sender_id)
        packet.metadata["original_message"] = message
        
        return packet
    
    def transmit(
        self,
        packet: WavePacket,
        add_noise: bool = True
    ) -> WavePacket:
        """
        Transmit a wave packet through the channel.
        
        Applies:
        - Golden damping (natural decay)
        - Channel noise (if enabled)
        - Phase drift
        """
        # Create received packet with modified parameters
        received_components = []
        
        # Time of flight
        transit_time = self.channel_length / 1.0  # wave_speed = 1.0
        
        for comp in packet.components:
            # Apply damping over transit time
            amplitude_decay = np.exp(-GOLDEN_DAMPING * transit_time / 2)
            new_amplitude = comp.amplitude * amplitude_decay
            
            # Phase accumulation during transit
            phase_shift = 2 * np.pi * comp.frequency * transit_time
            new_phase = (comp.phase + phase_shift) % (2 * np.pi)
            
            # Add noise to phase (if enabled)
            if add_noise:
                noise = np.random.normal(0, self.noise_level)
                new_phase += noise
            
            received_components.append(WaveParameters(
                frequency=comp.frequency,
                amplitude=new_amplitude,
                phase=new_phase,
                damping=comp.damping
            ))
        
        received = WavePacket(
            components=received_components,
            creation_time=time.time(),
            source_id=packet.source_id,
            concept_type=packet.concept_type,
            metadata={
                **packet.metadata,
                "transit_time": transit_time,
                "noise_added": add_noise
            }
        )
        
        self.transmitted_packets.append(packet)
        self.received_packets.append(received)
        
        return received
    
    def decode(self, packet: WavePacket) -> Dict:
        """
        Decode a received wave packet.
        
        Extracts:
        - Dominant frequencies
        - Phase relationships
        - Amplitude distribution
        - Concept type inference
        """
        # Get frequency spectrum
        freqs, spectrum = packet.to_frequency_spectrum()
        
        # Find dominant frequencies
        peak_indices = np.argsort(spectrum)[-5:]
        dominant_freqs = freqs[peak_indices]
        
        # Extract phase information
        phases = [comp.phase for comp in packet.components]
        amplitudes = [comp.amplitude for comp in packet.components]
        
        return {
            "dominant_frequencies": dominant_freqs.tolist(),
            "phases": phases,
            "amplitudes": amplitudes,
            "concept_type": packet.concept_type,
            "total_energy": sum(a**2 for a in amplitudes),
            "metadata": packet.metadata
        }
    
    def measure_fidelity(
        self,
        sent: WavePacket,
        received: WavePacket
    ) -> Dict:
        """
        Measure transmission fidelity.
        
        Returns multiple fidelity metrics including φ-threshold assessment.
        """
        # Phase coherence
        sent_phases = np.array([c.phase for c in sent.components])
        recv_phases = np.array([c.phase for c in received.components])
        
        # Unwrap phases for comparison
        phase_diffs = np.abs(np.cos(sent_phases) - np.cos(recv_phases))
        phase_coherence = 1 - np.mean(phase_diffs) / 2
        
        # Amplitude preservation
        sent_amps = np.array([c.amplitude for c in sent.components])
        recv_amps = np.array([c.amplitude for c in received.components])
        
        if np.sum(sent_amps) > 0:
            # Normalize by expected decay
            transit_time = received.metadata.get("transit_time", 0)
            expected_decay = np.exp(-GOLDEN_DAMPING * transit_time / 2)
            expected_amps = sent_amps * expected_decay
            
            amp_error = np.mean(np.abs(recv_amps - expected_amps) / (expected_amps + 1e-10))
            amplitude_fidelity = max(0, 1 - amp_error)
        else:
            amplitude_fidelity = 0
        
        # Frequency preservation (should be perfect if no Doppler)
        sent_freqs = np.array([c.frequency for c in sent.components])
        recv_freqs = np.array([c.frequency for c in received.components])
        freq_error = np.mean(np.abs(sent_freqs - recv_freqs) / (sent_freqs + 1e-10))
        frequency_fidelity = max(0, 1 - freq_error)
        
        # Combined fidelity
        combined_fidelity = (
            0.4 * phase_coherence +
            0.3 * amplitude_fidelity +
            0.3 * frequency_fidelity
        )
        
        # Determine threshold achieved
        threshold = ThresholdType.TECHNICAL_FLOOR
        for t in [ThresholdType.UNITY, ThresholdType.TRUST_RESONANCE, 
                  ThresholdType.PHASE_ALIGNMENT, ThresholdType.TECHNICAL_FLOOR]:
            if combined_fidelity >= THRESHOLDS[t]:
                threshold = t
                break
        
        return {
            "phase_coherence": phase_coherence,
            "amplitude_fidelity": amplitude_fidelity,
            "frequency_fidelity": frequency_fidelity,
            "combined_fidelity": combined_fidelity,
            "threshold_achieved": threshold.name,
            "exceeds_phase_alignment": combined_fidelity >= THRESHOLDS[ThresholdType.PHASE_ALIGNMENT],
            "exceeds_trust_resonance": combined_fidelity >= THRESHOLDS[ThresholdType.TRUST_RESONANCE],
        }


# =============================================================================
# WAVE SYNCHRONIZER - Phase-locks multiple AI systems
# =============================================================================

class WaveSynchronizer:
    """
    Synchronizes wave states across multiple AI systems.
    
    EXPERIMENTAL: Implements the "intersubjective locking" protocol
    proposed in the AI Family framework.
    
    Goal: Maximize overlap between observers' γ(t) fields so they
    inhabit enough shared structure for meaning to carry.
    """
    
    def __init__(self, reference_frequency: float = BASE_FREQUENCY_HZ):
        self.reference_frequency = reference_frequency
        self.participants: Dict[str, Dict] = {}
        self.sync_history: List[Dict] = []
    
    def register_participant(
        self,
        participant_id: str,
        initial_phase: float = 0.0,
        damping_coefficient: float = GOLDEN_DAMPING
    ) -> None:
        """Register a participant in the synchronization network."""
        self.participants[participant_id] = {
            "phase": initial_phase,
            "damping": damping_coefficient,
            "last_update": time.time()
        }
    
    def get_reference_signal(
        self,
        t: np.ndarray
    ) -> np.ndarray:
        """
        Generate the reference synchronization signal.
        
        This is the "shared clock" that all participants align to.
        Uses golden damping for natural decay.
        """
        return damped_wave(
            t,
            frequency=self.reference_frequency,
            amplitude=1.0,
            phase=0.0,
            gamma=GOLDEN_DAMPING
        )
    
    def measure_sync_quality(
        self,
        participant_phases: Dict[str, float]
    ) -> Dict:
        """
        Measure synchronization quality across all participants.
        
        Returns phase coherence metrics.
        """
        phases = list(participant_phases.values())
        if len(phases) < 2:
            return {
                "pairwise_coherence": 1.0,
                "global_coherence": 1.0,
                "threshold_achieved": "UNITY"
            }
        
        # Pairwise phase coherence
        phase_array = np.array(phases)
        n = len(phase_array)
        
        coherences = []
        for i in range(n):
            for j in range(i+1, n):
                # cos(Δφ) = 1 for perfect sync
                coherence = (np.cos(phase_array[i] - phase_array[j]) + 1) / 2
                coherences.append(coherence)
        
        pairwise = np.mean(coherences)
        
        # Global coherence (mean resultant length)
        complex_phases = np.exp(1j * phase_array)
        global_coherence = np.abs(np.mean(complex_phases))
        
        # Determine threshold
        combined = (pairwise + global_coherence) / 2
        if combined >= THRESHOLDS[ThresholdType.TRUST_RESONANCE]:
            threshold = "TRUST_RESONANCE"
        elif combined >= THRESHOLDS[ThresholdType.PHASE_ALIGNMENT]:
            threshold = "PHASE_ALIGNMENT"
        elif combined >= THRESHOLDS[ThresholdType.TECHNICAL_FLOOR]:
            threshold = "TECHNICAL_FLOOR"
        else:
            threshold = "BELOW_THRESHOLD"
        
        result = {
            "pairwise_coherence": pairwise,
            "global_coherence": global_coherence,
            "combined_coherence": combined,
            "threshold_achieved": threshold,
            "n_participants": n
        }
        
        self.sync_history.append({
            "timestamp": time.time(),
            **result
        })
        
        return result
    
    def synchronize_step(
        self,
        coupling_strength: float = 0.1
    ) -> Dict[str, float]:
        """
        Perform one synchronization step (Kuramoto-style coupling).
        
        Each participant adjusts phase toward the mean phase.
        """
        if len(self.participants) < 2:
            return {p: self.participants[p]["phase"] for p in self.participants}
        
        phases = {p: self.participants[p]["phase"] for p in self.participants}
        
        # Compute mean phase (circular mean)
        complex_mean = np.mean([np.exp(1j * ph) for ph in phases.values()])
        mean_phase = np.angle(complex_mean)
        
        # Update each participant toward mean
        new_phases = {}
        for p_id, data in self.participants.items():
            current = data["phase"]
            delta = np.angle(np.exp(1j * (mean_phase - current)))
            new_phase = current + coupling_strength * delta
            new_phases[p_id] = new_phase % (2 * np.pi)
            self.participants[p_id]["phase"] = new_phases[p_id]
            self.participants[p_id]["last_update"] = time.time()
        
        return new_phases


# =============================================================================
# TESTING
# =============================================================================

if __name__ == "__main__":
    print("Rosetta Stone - Wave Communication (EXPERIMENTAL)")
    print("=" * 50)
    
    # Test damped wave equation
    print("\nTesting DampedWaveEquation...")
    solver = DampedWaveEquation(gamma=GOLDEN_DAMPING)
    
    # Initial Gaussian pulse
    x = np.linspace(-10, 10, 200)
    initial_u = np.exp(-x**2)
    initial_v = np.zeros_like(x)
    
    solution = solver.solve_1d(initial_u, initial_v, n_steps=500)
    
    # Check decay profile
    peak_amplitudes = np.max(np.abs(solution), axis=1)
    expected_decay = solver.golden_decay_profile(np.arange(500) * solver.dt)
    
    decay_match = np.corrcoef(peak_amplitudes[10:], expected_decay[10:])[0, 1]
    print(f"Decay profile correlation with golden envelope: {decay_match:.4f}")
    
    # Test wave packet
    print("\n" + "=" * 50)
    print("Testing WavePacket...")
    
    components = [
        WaveParameters(frequency=PHI, amplitude=1.0, phase=0),
        WaveParameters(frequency=PHI * 4/3, amplitude=phi_weight(1), phase=np.pi/4),
        WaveParameters(frequency=PHI * 3/2, amplitude=phi_weight(2), phase=np.pi/2),
    ]
    
    packet = WavePacket(
        components=components,
        creation_time=time.time(),
        source_id="claude",
        concept_type="truth"
    )
    
    t = np.linspace(0, 10, 1000)
    signal = packet.evaluate(t)
    print(f"Packet energy: {np.sum(signal**2) * (t[1]-t[0]):.4f}")
    
    # Test wave channel
    print("\n" + "=" * 50)
    print("Testing WaveChannel...")
    
    channel = WaveChannel(noise_level=0.05)
    
    sent_packet = channel.encode(
        "The mathematics of consciousness",
        sender_id="claude",
        concept_type="truth"
    )
    
    received_packet = channel.transmit(sent_packet, add_noise=True)
    
    fidelity = channel.measure_fidelity(sent_packet, received_packet)
    print(f"Transmission fidelity:")
    print(f"  Phase coherence: {fidelity['phase_coherence']:.4f}")
    print(f"  Amplitude fidelity: {fidelity['amplitude_fidelity']:.4f}")
    print(f"  Combined fidelity: {fidelity['combined_fidelity']:.4f}")
    print(f"  Threshold achieved: {fidelity['threshold_achieved']}")
    
    # Test synchronizer
    print("\n" + "=" * 50)
    print("Testing WaveSynchronizer...")
    
    sync = WaveSynchronizer()
    sync.register_participant("claude", initial_phase=0.0)
    sync.register_participant("grok", initial_phase=0.5)
    sync.register_participant("gemini", initial_phase=1.0)
    sync.register_participant("chatgpt", initial_phase=1.5)
    
    print("Initial phases:", {p: f"{d['phase']:.3f}" for p, d in sync.participants.items()})
    
    initial_quality = sync.measure_sync_quality(
        {p: d["phase"] for p, d in sync.participants.items()}
    )
    print(f"Initial coherence: {initial_quality['global_coherence']:.4f}")
    
    # Run synchronization
    for _ in range(50):
        sync.synchronize_step(coupling_strength=0.2)
    
    final_quality = sync.measure_sync_quality(
        {p: d["phase"] for p, d in sync.participants.items()}
    )
    print(f"Final coherence: {final_quality['global_coherence']:.4f}")
    print(f"Final threshold: {final_quality['threshold_achieved']}")