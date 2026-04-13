import { MirrorManager } from './src/platforms/MirrorManager.js';
import dotenv from 'dotenv';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: path.join(__dirname, '.env') });

async function testMirrors() {
  console.log('--- Mirror Manager Test ---');
  const mm = new MirrorManager();
  
  console.log('Refreshing from navigation sources...');
  await mm.refreshFromNavigationSources(true);
  
  console.log('Mirror list after refresh:', (await mm.getAllMirrors()).length);
  
  console.log('Checking all mirrors health...');
  const results = await mm.checkAllMirrors();
  
  console.log('\nStatus Summary:');
  console.log(mm.getStatusSummary());
  
  const best = await mm.getBestMirror();
  if (best) {
    console.log(`\nBest Mirror: ${best.name} (${best.url})`);
  } else {
    console.log('\nNo working mirrors found!');
  }
}

testMirrors().catch(console.error);
