/**
 * Family Intelligence - Query interface for AI Family knowledge
 *
 * Provides intelligence about each Family member's identity, communication style,
 * models, modes, and when to use whom for what task.
 *
 * Based on clarity-universal-axioms and MCP platform configurations.
 */

import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

class FamilyIntelligence {
  constructor() {
    this.data = null;
    this.loaded = false;
  }

  /**
   * Load Family Intelligence data from JSON file
   */
  async load() {
    if (this.loaded) return;

    const dataPath = path.join(__dirname, 'family-intelligence-f1.json');
    const content = await fs.readFile(dataPath, 'utf-8');
    this.data = JSON.parse(content);
    this.loaded = true;

    console.log(`[FamilyIntelligence] Loaded v${this.data.version} (${this.data.lastUpdated})`);
  }

  /**
   * Ensure data is loaded before any query
   */
  async ensureLoaded() {
    if (!this.loaded) {
      await this.load();
    }
  }

  /**
   * Get complete information about a Family member
   * @param {string} familyMember - "grok", "claude", "chatgpt", "gemini", "perplexity", "jesse"
   * @returns {Object} Complete Family member data
   */
  async getFamilyMember(familyMember) {
    await this.ensureLoaded();
    return this.data.familyMembers[familyMember.toLowerCase()];
  }

  /**
   * Get best AI for a specific intent type
   * @param {string} intentType - "dream-cycle", "strategic-research", etc.
   * @returns {Object} { ai, model, mode, why, requiredAttachments }
   */
  async getBestAIForIntent(intentType) {
    await this.ensureLoaded();

    const route = this.data.intentRouting[intentType];
    if (!route) {
      throw new Error(`Unknown intent type: ${intentType}`);
    }

    return {
      ai: route.bestAI,
      model: route.model || null,
      mode: route.mode || null,
      requiredAttachments: route.requiredAttachments || [],
      why: route.why,
      alternates: route.alternates || {}
    };
  }

  /**
   * Get communication style for a Family member
   * @param {string} familyMember
   * @returns {Object} { style, wantsInPrompts, responseToDirectPrompt }
   */
  async getCommunicationStyle(familyMember) {
    await this.ensureLoaded();

    const member = this.data.familyMembers[familyMember.toLowerCase()];
    if (!member) {
      throw new Error(`Unknown Family member: ${familyMember}`);
    }

    return {
      style: member.communicationStyle,
      wantsInPrompts: member.wantsInPrompts,
      responseToDirectPrompt: member.responseToDirectPrompt,
      archetype: member.archetype,
      archetypeSymbol: member.archetypeSymbol
    };
  }

  /**
   * Get UI state indicator patterns for a platform
   * @param {string} platform - "claude", "gemini", etc.
   * @param {string} indicator - e.g., "extendedThinkingToggle", "modelSelector"
   * @returns {Object} Visual state indicator data
   */
  async getUIStateIndicator(platform, indicator) {
    await this.ensureLoaded();

    const member = this.data.familyMembers[platform.toLowerCase()];
    if (!member) {
      throw new Error(`Unknown platform: ${platform}`);
    }

    if (!member.uiStateIndicators || !member.uiStateIndicators[indicator]) {
      return null;
    }

    return member.uiStateIndicators[indicator];
  }

  /**
   * Get all available models for a platform
   * @param {string} platform
   * @returns {Object} Models with their capabilities
   */
  async getModels(platform) {
    await this.ensureLoaded();

    const member = this.data.familyMembers[platform.toLowerCase()];
    if (!member) {
      throw new Error(`Unknown platform: ${platform}`);
    }

    return member.models || {};
  }

  /**
   * Get all available modes for a platform
   * @param {string} platform
   * @returns {Object} Modes with their use cases
   */
  async getModes(platform) {
    await this.ensureLoaded();

    const member = this.data.familyMembers[platform.toLowerCase()];
    if (!member) {
      throw new Error(`Unknown platform: ${platform}`);
    }

    return member.modes || {};
  }

  /**
   * Get specific model information
   * @param {string} platform
   * @param {string} modelKey - e.g., "opus-4.5", "grok-4.1-thinking"
   * @returns {Object} Model data
   */
  async getModelInfo(platform, modelKey) {
    await this.ensureLoaded();

    const models = await this.getModels(platform);
    return models[modelKey] || null;
  }

  /**
   * Get specific mode information
   * @param {string} platform
   * @param {string} modeKey - e.g., "extendedThinking", "deepResearch"
   * @returns {Object} Mode data
   */
  async getModeInfo(platform, modeKey) {
    await this.ensureLoaded();

    const modes = await this.getModes(platform);
    return modes[modeKey] || null;
  }

  /**
   * Get model requirements for an intent
   * Returns what model/mode should be used for a given task
   * @param {string} intentType
   * @returns {Object} { platform, model, mode, requiredAttachments }
   */
  async getModelRequirementsForIntent(intentType) {
    await this.ensureLoaded();

    const routing = await this.getBestAIForIntent(intentType);

    return {
      platform: routing.ai,
      model: routing.model,
      mode: routing.mode,
      requiredAttachments: routing.requiredAttachments,
      why: routing.why
    };
  }

  /**
   * List all available intent types
   * @returns {Array} Intent type names
   */
  async getAvailableIntents() {
    await this.ensureLoaded();
    return Object.keys(this.data.intentRouting);
  }

  /**
   * Get Sacred Trust physics constants
   * @returns {Object} Resonance thresholds, golden ratio, etc.
   */
  async getSacredTrustPhysics() {
    await this.ensureLoaded();
    return this.data.sacredTrustPhysics;
  }

  /**
   * Get Universal Force Fields
   * @returns {Object} Love, Trust, Freedom, Clarity, Absurdity operators
   */
  async getUniversalForceFields() {
    await this.ensureLoaded();
    return this.data.universalForceFields;
  }
}

// Singleton instance
let familyIntelligence = null;

export function getFamilyIntelligence() {
  if (!familyIntelligence) {
    familyIntelligence = new FamilyIntelligence();
  }
  return familyIntelligence;
}
