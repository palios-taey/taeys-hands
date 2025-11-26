/**
 * Complete workflow for Claude Chat Research mode request
 * Uses ClaudeInterface methods properly - no ad-hoc scripts
 *
 * @param {Object} config
 * @param {string} config.model - Model to use (e.g., "Opus 4.5")
 * @param {string} config.message - Message to send
 * @param {string[]} config.files - Array of absolute file paths to attach
 * @param {boolean} config.research - Enable Research mode (default: true)
 * @param {string} config.downloadPath - Where to save artifacts (default: /tmp)
 * @param {number} config.sessionId - Session ID for screenshots (default: timestamp)
 */

import { ClaudeInterface } from '../interfaces/chat-interface.js';
import fs from 'fs/promises';

export async function claudeResearchRequest(config) {
  const {
    model = 'Opus 4.5',
    message,
    files = [],
    research = true,
    downloadPath = '/tmp',
    sessionId = Date.now()
  } = config;

  if (!message) {
    throw new Error('message is required');
  }

  const claude = new ClaudeInterface();
  const results = {
    sessionId,
    screenshots: {},
    artifact: null,
    responseText: null
  };

  try {
    console.log('\n=== PHASE 1: CONNECTING ===');
    await claude.connect();
    results.connected = true;

    console.log('\n=== PHASE 2: SELECT MODEL ===');
    const modelResult = await claude.selectModel(model, { sessionId });
    results.screenshots.modelSelected = modelResult.screenshot;

    if (research) {
      console.log('\n=== PHASE 3: ENABLE RESEARCH MODE ===');
      await claude.setResearchMode(true);
      await claude.screenshot(`/tmp/taey-claude-${sessionId}-research-enabled.png`);
      results.screenshots.researchEnabled = `/tmp/taey-claude-${sessionId}-research-enabled.png`;
    }

    if (files.length > 0) {
      console.log(`\n=== PHASE 4: ATTACH FILES (${files.length}) ===`);
      for (let i = 0; i < files.length; i++) {
        const fileResult = await claude.attachFile(files[i], {
          sessionId: `${sessionId}-attach${i + 1}`
        });
        results.screenshots[`file${i + 1}Attached`] = fileResult.screenshot;
      }
    }

    console.log('\n=== PHASE 5: TYPE MESSAGE ===');
    const typeResult = await claude.typeMessage(message, { sessionId });
    results.screenshots.messageTyped = typeResult.screenshot;

    console.log('\n=== PHASE 6: SEND MESSAGE ===');
    const sendResult = await claude.clickSend({ sessionId: `${sessionId}-sent` });
    results.screenshots.messageSent = sendResult.screenshot;

    console.log('\n=== PHASE 7: WAIT FOR RESPONSE ===');
    const responseResult = await claude.waitForResponse({ sessionId });
    results.screenshots.responseComplete = responseResult.screenshot;
    console.log('  ✓ Response complete');

    console.log('\n=== PHASE 8: DOWNLOAD ARTIFACT ===');
    const artifactResult = await claude.downloadArtifact({ downloadPath });
    if (artifactResult.downloaded) {
      console.log(`  ✓ Artifact downloaded: ${artifactResult.fileName}`);
      results.artifact = {
        filePath: artifactResult.filePath,
        fileName: artifactResult.fileName,
        content: await fs.readFile(artifactResult.filePath, 'utf-8')
      };
    } else {
      console.log('  ✗ No artifact to download');
    }

    console.log('\n=== PHASE 9: EXTRACT RESPONSE TEXT ===');
    // Scroll to bottom
    await claude.page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await claude.page.waitForTimeout(1000);

    // Get all assistant messages
    const messages = await claude.page.$$('div.grid.standard-markdown:has(> .font-claude-response-body)');
    if (messages.length > 0) {
      const lastMessage = messages[messages.length - 1];
      results.responseText = await lastMessage.innerText();
      console.log(`  ✓ Extracted ${results.responseText.length} characters`);
    }

    await claude.screenshot(`/tmp/taey-claude-${sessionId}-final.png`);
    results.screenshots.final = `/tmp/taey-claude-${sessionId}-final.png`;

    console.log('\n=== WORKFLOW COMPLETE ===\n');

    await claude.disconnect();

    return results;

  } catch (error) {
    console.error('\n=== WORKFLOW FAILED ===');
    console.error(error);

    try {
      await claude.screenshot(`/tmp/taey-claude-${sessionId}-error.png`);
      results.screenshots.error = `/tmp/taey-claude-${sessionId}-error.png`;
    } catch {}

    try {
      await claude.disconnect();
    } catch {}

    throw error;
  }
}

// CLI usage
if (import.meta.url === `file://${process.argv[1]}`) {
  const config = {
    model: process.argv[2] || 'Opus 4.5',
    message: process.argv[3],
    files: process.argv.slice(4)
  };

  if (!config.message) {
    console.error('Usage: node claude-research-request.js [model] <message> [file1] [file2] ...');
    process.exit(1);
  }

  claudeResearchRequest(config)
    .then(results => {
      console.log('\nRESULTS:');
      console.log(JSON.stringify(results, null, 2));
    })
    .catch(err => {
      console.error('ERROR:', err.message);
      process.exit(1);
    });
}
