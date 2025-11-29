// Family Intelligence Neo4j Schema
// Creates the graph structure for AI Family knowledge

// ============================================================================
// CONSTRAINTS (Uniqueness)
// ============================================================================

CREATE CONSTRAINT family_member_id IF NOT EXISTS
FOR (f:FamilyMember) REQUIRE f.id IS UNIQUE;

CREATE CONSTRAINT platform_name IF NOT EXISTS
FOR (p:Platform) REQUIRE p.name IS UNIQUE;

CREATE CONSTRAINT model_id IF NOT EXISTS
FOR (m:Model) REQUIRE m.id IS UNIQUE;

CREATE CONSTRAINT mode_id IF NOT EXISTS
FOR (m:Mode) REQUIRE m.id IS UNIQUE;

CREATE CONSTRAINT intent_type IF NOT EXISTS
FOR (i:IntentType) REQUIRE i.type IS UNIQUE;

// ============================================================================
// INDEXES (Performance)
// ============================================================================

CREATE INDEX family_archetype IF NOT EXISTS
FOR (f:FamilyMember) ON (f.archetype);

CREATE INDEX intent_priority IF NOT EXISTS
FOR (i:IntentType) ON (i.priority);

CREATE INDEX model_best_for IF NOT EXISTS
FOR (m:Model) ON (m.bestFor);

// ============================================================================
// NODE STRUCTURE
// ============================================================================

// FamilyMember
// Properties: id, identity, alternateNames[], archetype, archetypeSymbol,
//             essence, communicationStyle, wantsInPrompts, responseToDirectPrompt,
//             strengthsWhenCombinedWith[], role, specialCapability
// Relationships: USES_PLATFORM, HAS_ARCHETYPE

// Platform
// Properties: name, interface
// Relationships: HAS_MODEL, HAS_MODE, DISPLAYS_UI_STATE

// Model
// Properties: id, name, bestFor[], thinkingStyle, strengths[], weaknesses[],
//             typicalDuration
// Relationships: BELONGS_TO_PLATFORM, RECOMMENDED_FOR_INTENT

// Mode
// Properties: id, name, whenToUse, whenNotToUse, visualIndicator,
//             visualStateActive, visualStateInactive, colorGuidance,
//             typicalDuration
// Relationships: BELONGS_TO_PLATFORM, REQUIRED_FOR_INTENT

// UIStateIndicator
// Properties: type (modelSelector, modeToggle, attachments, etc.),
//             location, format, activeState, inactiveState, appearance,
//             colorGuidance
// Relationships: BELONGS_TO_PLATFORM

// IntentType
// Properties: type, description, details, bestAI, requiredModel, requiredMode,
//             requiredAttachments[], allFamilyParticipation, familyBondPriority,
//             priority, note
// Relationships: ROUTES_TO_PLATFORM, ROUTES_TO_MODEL, ROUTES_TO_MODE,
//                ALTERNATE_PLATFORM, ALTERNATE_MODEL, ALTERNATE_MODE

// Archetype
// Properties: name, symbol, forceField (Love, Trust, Freedom, Clarity, Absurdity)
// Relationships: EXPRESSED_BY_FAMILY_MEMBER

// ============================================================================
// SAMPLE QUERIES
// ============================================================================

// Get best AI for intent:
// MATCH (i:IntentType {type: 'dream-sessions'})-[:ROUTES_TO_PLATFORM]->(p:Platform)
// OPTIONAL MATCH (i)-[:ROUTES_TO_MODEL]->(m:Model)
// OPTIONAL MATCH (i)-[:ROUTES_TO_MODE]->(mode:Mode)
// RETURN p.name, m.name, mode.name

// Get UI state patterns for platform:
// MATCH (p:Platform {name: 'claude'})-[:DISPLAYS_UI_STATE]->(ui:UIStateIndicator)
// RETURN ui.type, ui.location, ui.activeState, ui.inactiveState, ui.colorGuidance

// Get Family member communication style:
// MATCH (f:FamilyMember {id: 'grok'})
// RETURN f.communicationStyle, f.wantsInPrompts, f.responseToDirectPrompt

// Get all models for a platform:
// MATCH (p:Platform {name: 'claude'})-[:HAS_MODEL]->(m:Model)
// RETURN m.name, m.bestFor, m.thinkingStyle

// Get intents requiring all Family participation:
// MATCH (i:IntentType {allFamilyParticipation: true})
// RETURN i.type, i.description, i.familyBondPriority
