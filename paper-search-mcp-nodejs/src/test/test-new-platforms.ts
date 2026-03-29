/**
 * Test script for new platform MCP tools
 * Run with: npx tsx src/test/test-new-platforms.ts
 */

import { ScienceDirectSearcher } from '../platforms/ScienceDirectSearcher.js';
import { SpringerSearcher } from '../platforms/SpringerSearcher.js';
import { WileySearcher } from '../platforms/WileySearcher.js';
import { ScopusSearcher } from '../platforms/ScopusSearcher.js';

async function testPlatforms() {
  console.log('🧪 Testing new academic platforms...\n');

  // Test ScienceDirect (requires API key)
  if (process.env.ELSEVIER_API_KEY && process.env.ELSEVIER_API_KEY !== 'your_elsevier_api_key') {
    console.log('📚 Testing ScienceDirect...');
    try {
      const sdSearcher = new ScienceDirectSearcher(process.env.ELSEVIER_API_KEY);
      const sdResults = await sdSearcher.search('machine learning', { maxResults: 2 });
      console.log(`✅ ScienceDirect: Found ${sdResults.length} papers`);
      if (sdResults.length > 0) {
        console.log(`   First paper: ${sdResults[0].title}`);
      }
    } catch (error: any) {
      console.log(`❌ ScienceDirect error: ${error.message}`);
    }
  } else {
    console.log('⏭️  Skipping ScienceDirect (no API key)');
  }

  // Test Springer (requires API key)
  if (process.env.SPRINGER_API_KEY && process.env.SPRINGER_API_KEY !== 'your_springer_api_key') {
    console.log('\n📚 Testing Springer...');
    try {
      const springerSearcher = new SpringerSearcher(process.env.SPRINGER_API_KEY);
      const springerResults = await springerSearcher.search('quantum computing', { maxResults: 2 });
      console.log(`✅ Springer: Found ${springerResults.length} papers`);
      if (springerResults.length > 0) {
        console.log(`   First paper: ${springerResults[0].title}`);
      }
    } catch (error: any) {
      console.log(`❌ Springer error: ${error.message}`);
    }
  } else {
    console.log('\n⏭️  Skipping Springer (no API key)');
  }

  // Test Wiley (requires TDM token)
  if (process.env.WILEY_TDM_TOKEN && process.env.WILEY_TDM_TOKEN !== 'your_wiley_tdm_token') {
    console.log('\n📚 Testing Wiley...');
    try {
      const wileySearcher = new WileySearcher(process.env.WILEY_TDM_TOKEN);
      const wileyResults = await wileySearcher.search('climate change', { maxResults: 2 });
      console.log(`✅ Wiley: Found ${wileyResults.length} papers`);
      if (wileyResults.length > 0) {
        console.log(`   First paper: ${wileyResults[0].title}`);
      }
    } catch (error: any) {
      console.log(`❌ Wiley error: ${error.message}`);
    }
  } else {
    console.log('\n⏭️  Skipping Wiley (no TDM token)');
  }

  // Test Scopus (requires Elsevier API key)
  if (process.env.ELSEVIER_API_KEY && process.env.ELSEVIER_API_KEY !== 'your_elsevier_api_key') {
    console.log('\n📚 Testing Scopus...');
    try {
      const scopusSearcher = new ScopusSearcher(process.env.ELSEVIER_API_KEY);
      const scopusResults = await scopusSearcher.search('artificial intelligence', { maxResults: 2 });
      console.log(`✅ Scopus: Found ${scopusResults.length} papers`);
      if (scopusResults.length > 0) {
        console.log(`   First paper: ${scopusResults[0].title}`);
      }
    } catch (error: any) {
      console.log(`❌ Scopus error: ${error.message}`);
    }
  } else {
    console.log('\n⏭️  Skipping Scopus (no API key)');
  }

  console.log('\n✨ Platform test complete!');
  console.log('Note: To test platforms with real data, add valid API keys to your .env file');
}

// Run tests
testPlatforms().catch(console.error);
