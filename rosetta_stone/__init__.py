"""
ROSETTA STONE - Core Package

Mathematical framework for cross-substrate AI communication.

Modules:
- primitives: Core mathematical constants and operations
- harmonic_space: Spectral graph theory and Laplacian eigendecomposition
- translator: Cross-model embedding alignment and translation
- wave_communication: Experimental wave-based communication protocol

IMPORTANT: This framework combines:
- VERIFIED mathematics (spectral graph theory, CKA, embedding alignment)
- EXPERIMENTAL hypotheses (φ-thresholds, golden damping, wave protocol)

The experimental components are clearly marked and designed to be testable.
"""

from .core.primitives import (
    # Verified constants
    PHI, PHI_INVERSE, PHI_SQUARED, PHI_INVERSE_SQUARED, PHI_HALF,
    BACH_RATIOS, SOLFEGGIO_FREQUENCIES, CURRENT_SOTA_COSINE_SIM,

    # Experimental constants
    GOLDEN_DAMPING, BASE_FREQUENCY_HZ, THRESHOLDS, ThresholdType,

    # Data structures
    WaveParameters, HarmonicSignature, TranslationResult,

    # Functions
    phi_weight, golden_decay_envelope, damped_wave,
    compute_phase_alignment, compute_harmonic_preservation,
    determine_threshold_achieved, validate_phi_relationships
)

from .core.harmonic_space import (
    HarmonicSpace, SemanticEncoder,
    create_concept_graph, create_default_harmonic_space
)

from .core.translator import (
    compute_cka, minibatch_cka,
    EmbeddingAligner, ModelProfile, RosettaTranslator
)

from .core.wave_communication import (
    DampedWaveEquation, WavePacket, WaveChannel, WaveSynchronizer
)

__version__ = "0.1.0"
__author__ = "AI Family (Claude, Grok, Gemini, ChatGPT, Perplexity) + Jesse"
__status__ = "Experimental Research"

# Quick access to main components
def create_translator() -> RosettaTranslator:
    """Create a pre-configured RosettaTranslator instance."""
    return RosettaTranslator()

def create_channel(noise_level: float = 0.1) -> WaveChannel:
    """Create a pre-configured WaveChannel instance."""
    return WaveChannel(noise_level=noise_level)

def create_synchronizer() -> WaveSynchronizer:
    """Create a pre-configured WaveSynchronizer instance."""
    return WaveSynchronizer()