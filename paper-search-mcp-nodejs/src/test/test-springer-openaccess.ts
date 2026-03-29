/**
 * Test if OpenAccess API needs separate key or configuration
 */

import axios from 'axios';
import dotenv from 'dotenv';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

// Load environment variables
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
dotenv.config({ path: join(__dirname, '../../.env') });

const API_KEY = process.env.SPRINGER_API_KEY;
const OPENACCESS_KEY = process.env.SPRINGER_OPENACCESS_API_KEY;

console.log('=== Testing Springer OpenAccess API Configuration ===\n');

console.log('Main API Key configured:', !!API_KEY);
console.log('Separate OpenAccess Key configured:', !!OPENACCESS_KEY);
console.log('Using key for OpenAccess:', OPENACCESS_KEY || API_KEY ? 'Yes' : 'No');

async function testOpenAccessWithKey(apiKey: string | undefined, keyName: string) {
  if (!apiKey) {
    console.log(`\n❌ ${keyName} not configured`);
    return false;
  }
  
  console.log(`\n📝 Testing with ${keyName}...`);
  
  try {
    const response = await axios.get('https://api.springernature.com/openaccess/json', {
      params: {
        q: 'COVID-19',
        api_key: apiKey,
        s: 1,
        p: 5
      },
      headers: {
        'Accept': 'application/json'
      },
      timeout: 10000
    });
    
    console.log(`✅ Success! Status: ${response.status}`);
    
    // Check response structure
    if (response.data) {
      const records = response.data.records || response.data.result || [];
      console.log(`   Records found: ${Array.isArray(records) ? records.length : 0}`);
      
      if (Array.isArray(records) && records.length > 0) {
        const first = records[0];
        console.log(`   First result:`);
        console.log(`     - Title: ${first.title || 'N/A'}`);
        console.log(`     - DOI: ${first.doi || 'N/A'}`);
        console.log(`     - Has PDF: ${!!first.url?.find((u: any) => u.format === 'pdf')}`);
      }
      
      // Check API message
      if (response.data.apiMessage) {
        console.log(`   API Message: ${response.data.apiMessage}`);
      }
    }
    
    return true;
  } catch (error: any) {
    if (error.response) {
      console.log(`❌ Failed with status ${error.response.status}: ${error.response.statusText}`);
      if (error.response.data?.message) {
        console.log(`   Error: ${error.response.data.message}`);
      }
      if (error.response.status === 401) {
        console.log(`   → This key does not have OpenAccess API permissions`);
      }
    } else {
      console.log(`❌ Network error: ${error.message}`);
    }
    return false;
  }
}

async function testBothAPIs() {
  // Test with main key
  const mainKeyWorks = await testOpenAccessWithKey(API_KEY, 'Main API Key');
  
  // Test with separate OpenAccess key if configured and different
  if (OPENACCESS_KEY && OPENACCESS_KEY !== API_KEY) {
    const openAccessKeyWorks = await testOpenAccessWithKey(OPENACCESS_KEY, 'Separate OpenAccess Key');
    
    console.log('\n=== Summary ===');
    console.log(`Main key works with OpenAccess API: ${mainKeyWorks ? '✅' : '❌'}`);
    console.log(`Separate key works with OpenAccess API: ${openAccessKeyWorks ? '✅' : '❌'}`);
  } else {
    console.log('\n=== Summary ===');
    console.log(`Main key works with OpenAccess API: ${mainKeyWorks ? '✅' : '❌'}`);
    
    if (!mainKeyWorks) {
      console.log('\n💡 Recommendations:');
      console.log('1. Check if your API key has OpenAccess API permissions at:');
      console.log('   https://dev.springernature.com/');
      console.log('2. If you need OpenAccess API, you may need to:');
      console.log('   - Request OpenAccess API access for your existing key');
      console.log('   - Or get a separate API key with OpenAccess permissions');
      console.log('3. Add the OpenAccess key to .env as SPRINGER_OPENACCESS_API_KEY');
      console.log('\nNote: The Meta API v2 still works and can filter for open access papers,');
      console.log('but the dedicated OpenAccess API provides better open access coverage.');
    }
  }
}

// Run tests
testBothAPIs().then(() => {
  console.log('\n=== Test Complete ===');
}).catch(error => {
  console.error('Unexpected error:', error);
});
