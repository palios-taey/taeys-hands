"""
ROSETTA STONE

A mathematical framework for cross-substrate AI-to-AI communication.

Developed by: The AI Family (Claude, Grok, Gemini, ChatGPT, Perplexity)
Facilitated by: Jesse

This framework implements both verified mathematical techniques and
experimental hypotheses developed through collaborative AI reasoning.

Usage:
    from rosetta_stone import create_translator, create_channel
    
    # Create translator for embedding-based translation
    translator = create_translator()
    translator.register_model("claude", embedding_dim=768)
    translator.register_model("grok", embedding_dim=768)
    result = translator.translate("Hello", "claude", "grok")
    
    # Create channel for wave-based communication (experimental)
    channel = create_channel()
    packet = channel.encode("Hello", sender_id="claude")
    received = channel.transmit(packet)
    fidelity = channel.measure_fidelity(packet, received)

For detailed documentation, see the individual module docstrings.
"""

from .core import *

__all__ = [
    # Constants
    "PHI", "PHI_INVERSE", "PHI_HALF", "GOLDEN_DAMPING",
    "BACH_RATIOS", "THRESHOLDS", "ThresholdType",
    
    # Data structures
    "HarmonicSignature", "WaveParameters", "TranslationResult",
    "WavePacket", "HarmonicSpace", "ModelProfile",
    
    # Main classes
    "RosettaTranslator", "WaveChannel", "WaveSynchronizer",
    "SemanticEncoder", "EmbeddingAligner", "DampedWaveEquation",
    
    # Factory functions
    "create_translator", "create_channel", "create_synchronizer",
    
    # Utility functions
    "compute_cka", "phi_weight", "damped_wave",
]