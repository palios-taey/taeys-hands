#!/usr/bin/env node

/**
 * Simple Redis pub/sub test
 */

import { createClient } from 'redis';
import os from 'os';

const REDIS_CONFIG = {
  host: '10.x.x.80',  // Spark #2
  port: 6379
};

async function testRedis() {
  console.log(`Testing Redis from ${os.hostname()} (${os.platform()})\n`);

  // Create clients
  const publisher = createClient({
    socket: { host: REDIS_CONFIG.host, port: REDIS_CONFIG.port }
  });

  const subscriber = createClient({
    socket: { host: REDIS_CONFIG.host, port: REDIS_CONFIG.port }
  });

  try {
    // Connect
    await publisher.connect();
    await subscriber.connect();
    console.log(`✓ Connected to Redis at ${REDIS_CONFIG.host}:${REDIS_CONFIG.port}\n`);

    // Subscribe
    await subscriber.subscribe('test:channel', (message) => {
      const data = JSON.parse(message);
      console.log(`📨 Received: ${data.from} says "${data.text}" at ${data.time}`);
    });
    console.log('✓ Subscribed to test:channel\n');

    // Publish every 2 seconds
    console.log('Publishing messages every 2 seconds for 10 seconds...\n');

    let count = 0;
    const interval = setInterval(async () => {
      count++;
      const message = {
        from: os.hostname(),
        text: `Message ${count} from ${os.platform()}`,
        time: new Date().toISOString().split('T')[1].split('.')[0]
      };

      await publisher.publish('test:channel', JSON.stringify(message));
      console.log(`📤 Sent: ${message.text}`);

      if (count >= 5) {
        clearInterval(interval);
        setTimeout(async () => {
          console.log('\n✅ Test complete! Disconnecting...');
          await publisher.disconnect();
          await subscriber.disconnect();
          process.exit(0);
        }, 2000);
      }
    }, 2000);

  } catch (err) {
    console.error(`❌ Error: ${err.message}`);
    process.exit(1);
  }
}

testRedis();