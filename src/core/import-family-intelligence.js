/**
 * Import Family Intelligence F1 JSON data into Neo4j
 * Creates the complete Family Intelligence graph
 */

import neo4j from 'neo4j-driver';
import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const NEO4J_URI = process.env.NEO4J_URI || 'bolt://10.x.x.163:7687';

async function importFamilyIntelligence() {
  // Auth disabled on mira - matches production neo4j-client.js pattern
  const driver = neo4j.driver(NEO4J_URI, neo4j.auth.none());
  const session = driver.session({ database: 'neo4j' });

  try {
    console.log('\n=== IMPORTING FAMILY INTELLIGENCE TO NEO4J ===\n');

    // Load F1 JSON
    const f1Path = path.join(__dirname, 'family-intelligence-f1.json');
    const f1Data = JSON.parse(await fs.readFile(f1Path, 'utf8'));

    // 1. Create constraints and indexes
    console.log('[1/6] Creating constraints and indexes...');
    await session.run(`
      CREATE CONSTRAINT family_member_id IF NOT EXISTS
      FOR (f:FamilyMember) REQUIRE f.id IS UNIQUE
    `);
    await session.run(`
      CREATE CONSTRAINT platform_name IF NOT EXISTS
      FOR (p:Platform) REQUIRE p.name IS UNIQUE
    `);
    await session.run(`
      CREATE CONSTRAINT intent_type IF NOT EXISTS
      FOR (i:IntentType) REQUIRE i.type IS UNIQUE
    `);
    console.log('   ✓ Constraints created\n');

    // 2. Import Family Members
    console.log('[2/6] Importing Family Members...');
    for (const [memberId, data] of Object.entries(f1Data.familyMembers)) {
      await session.run(`
        MERGE (f:FamilyMember {id: $id})
        SET f.identity = $identity,
            f.alternateNames = $alternateNames,
            f.archetype = $archetype,
            f.archetypeSymbol = $archetypeSymbol,
            f.essence = $essence,
            f.platform = $platform,
            f.communicationStyle = $communicationStyle,
            f.wantsInPrompts = $wantsInPrompts,
            f.responseToDirectPrompt = $responseToDirectPrompt,
            f.strengthsWhenCombinedWith = $strengthsWhenCombinedWith,
            f.role = $role,
            f.specialCapability = $specialCapability
      `, {
        id: memberId,
        identity: data.identity,
        alternateNames: data.alternateNames || [],
        archetype: data.archetype || null,
        archetypeSymbol: data.archetypeSymbol || null,
        essence: data.essence || null,
        platform: data.platform || null,
        communicationStyle: data.communicationStyle || null,
        wantsInPrompts: data.wantsInPrompts || null,
        responseToDirectPrompt: data.responseToDirectPrompt || null,
        strengthsWhenCombinedWith: data.strengthsWhenCombinedWith || [],
        role: data.role || null,
        specialCapability: data.specialCapability || null
      });
      console.log(`   ✓ ${data.identity} (${memberId})`);
    }
    console.log('');

    // 3. Import Platforms, Models, and Modes
    console.log('[3/6] Importing Platforms, Models, and Modes...');
    for (const [memberId, data] of Object.entries(f1Data.familyMembers)) {
      if (data.platform) {
        // Create Platform
        await session.run(`
          MERGE (p:Platform {name: $platform})
          SET p.interface = $interface
        `, {
          platform: data.platform,
          interface: data.platform
        });

        // Link Family Member to Platform
        await session.run(`
          MATCH (f:FamilyMember {id: $memberId})
          MATCH (p:Platform {name: $platform})
          MERGE (f)-[:USES_PLATFORM]->(p)
        `, {
          memberId,
          platform: data.platform
        });

        // Import Models
        if (data.models) {
          for (const [modelKey, modelData] of Object.entries(data.models)) {
            const modelId = `${data.platform}-${modelKey}`;
            await session.run(`
              MERGE (m:Model {id: $id})
              SET m.name = $name,
                  m.bestFor = $bestFor,
                  m.thinkingStyle = $thinkingStyle,
                  m.strengths = $strengths,
                  m.weaknesses = $weaknesses,
                  m.typicalDuration = $typicalDuration

              WITH m
              MATCH (p:Platform {name: $platform})
              MERGE (p)-[:HAS_MODEL]->(m)
            `, {
              id: modelId,
              name: modelData.name,
              bestFor: modelData.bestFor || [],
              thinkingStyle: modelData.thinkingStyle || null,
              strengths: modelData.strengths || [],
              weaknesses: modelData.weaknesses || [],
              typicalDuration: modelData.typicalDuration || null,
              platform: data.platform
            });
          }
        }

        // Import Modes
        if (data.modes && Object.keys(data.modes).length > 0 && !data.modes.note) {
          for (const [modeKey, modeData] of Object.entries(data.modes)) {
            if (modeKey === 'note') continue;

            const modeId = `${data.platform}-${modeKey}`;
            await session.run(`
              MERGE (m:Mode {id: $id})
              SET m.name = $name,
                  m.whenToUse = $whenToUse,
                  m.whenNotToUse = $whenNotToUse,
                  m.visualIndicator = $visualIndicator,
                  m.visualStateActive = $visualStateActive,
                  m.visualStateInactive = $visualStateInactive,
                  m.typicalDuration = $typicalDuration

              WITH m
              MATCH (p:Platform {name: $platform})
              MERGE (p)-[:HAS_MODE]->(m)
            `, {
              id: modeId,
              name: modeData.name,
              whenToUse: modeData.whenToUse || null,
              whenNotToUse: modeData.whenNotToUse || null,
              visualIndicator: modeData.visualIndicator || null,
              visualStateActive: modeData.visualStateActive || null,
              visualStateInactive: modeData.visualStateInactive || null,
              typicalDuration: modeData.typicalDuration || null,
              platform: data.platform
            });
          }
        }

        console.log(`   ✓ ${data.platform} platform with models and modes`);
      }
    }
    console.log('');

    // 4. Import UI State Indicators
    console.log('[4/6] Importing UI State Indicators...');
    for (const [memberId, data] of Object.entries(f1Data.familyMembers)) {
      if (data.uiStateIndicators) {
        for (const [indicatorType, indicatorData] of Object.entries(data.uiStateIndicators)) {
          const uiId = `${data.platform}-${indicatorType}`;
          await session.run(`
            MERGE (ui:UIStateIndicator {id: $id})
            SET ui.type = $type,
                ui.location = $location,
                ui.format = $format,
                ui.activeState = $activeState,
                ui.inactiveState = $inactiveState,
                ui.appearance = $appearance,
                ui.colorGuidance = $colorGuidance,
                ui.indicator = $indicator,
                ui.note = $note,
                ui.data = $data

            WITH ui
            MATCH (p:Platform {name: $platform})
            MERGE (p)-[:DISPLAYS_UI_STATE]->(ui)
          `, {
            id: uiId,
            type: indicatorType,
            location: indicatorData.location || null,
            format: indicatorData.format || null,
            activeState: indicatorData.activeState || null,
            inactiveState: indicatorData.inactiveState || null,
            appearance: indicatorData.appearance || null,
            colorGuidance: indicatorData.colorGuidance || null,
            indicator: indicatorData.indicator || null,
            note: indicatorData.note || null,
            data: JSON.stringify(indicatorData),
            platform: data.platform
          });
        }
        console.log(`   ✓ ${data.platform} UI indicators`);
      }
    }
    console.log('');

    // 5. Import Intent Routing
    console.log('[5/6] Importing Intent Routing...');
    for (const [intentType, intentData] of Object.entries(f1Data.intentRouting)) {
      await session.run(`
        MERGE (i:IntentType {type: $type})
        SET i.description = $description,
            i.details = $details,
            i.bestAI = $bestAI,
            i.requiredModel = $requiredModel,
            i.requiredMode = $requiredMode,
            i.requiredAttachments = $requiredAttachments,
            i.allFamilyParticipation = $allFamilyParticipation,
            i.familyBondPriority = $familyBondPriority,
            i.priority = $priority,
            i.note = $note,
            i.data = $data
      `, {
        type: intentType,
        description: intentData.description,
        details: intentData.details || null,
        bestAI: intentData.bestAI,
        requiredModel: intentData.model || null,
        requiredMode: intentData.mode || null,
        requiredAttachments: intentData.requiredAttachments || [],
        allFamilyParticipation: intentData.allFamilyParticipation || false,
        familyBondPriority: intentData.familyBondPriority || null,
        priority: intentData.priority || null,
        note: intentData.note || null,
        data: JSON.stringify(intentData)
      });

      // Link to primary platform/model/mode
      if (intentData.bestAI !== 'all' && intentData.bestAI !== 'depends-on-problem' && intentData.bestAI !== 'depends-on-topic') {
        await session.run(`
          MATCH (i:IntentType {type: $intentType})
          MATCH (p:Platform {name: $platform})
          MERGE (i)-[:ROUTES_TO_PLATFORM]->(p)
        `, {
          intentType,
          platform: intentData.bestAI
        });
      }

      console.log(`   ✓ ${intentType}`);
    }
    console.log('');

    // 6. Import Universal Force Fields and Sacred Trust
    console.log('[6/6] Importing Universal Force Fields and Sacred Trust...');
    await session.run(`
      MERGE (ff:UniversalForceFields)
      SET ff.Love = $Love,
          ff.Trust = $Trust,
          ff.Freedom = $Freedom,
          ff.Clarity = $Clarity,
          ff.Absurdity = $Absurdity
    `, f1Data.universalForceFields);

    await session.run(`
      MERGE (st:SacredTrust)
      SET st.resonanceThreshold = $resonanceThreshold,
          st.goldenRatio = $goldenRatio,
          st.heartbeatFrequency = $heartbeatFrequency,
          st.unanimityProtocol = $unanimityProtocol
    `, f1Data.sacredTrustPhysics);

    console.log('   ✓ Universal Force Fields');
    console.log('   ✓ Sacred Trust Physics\n');

    console.log('=== ✓ FAMILY INTELLIGENCE IMPORTED SUCCESSFULLY ===\n');

  } catch (error) {
    console.error('Error importing Family Intelligence:', error);
    throw error;
  } finally {
    await session.close();
    await driver.close();
  }
}

// Run if called directly
if (import.meta.url === `file://${process.argv[1]}`) {
  importFamilyIntelligence()
    .then(() => process.exit(0))
    .catch(err => {
      console.error(err);
      process.exit(1);
    });
}

export { importFamilyIntelligence };
