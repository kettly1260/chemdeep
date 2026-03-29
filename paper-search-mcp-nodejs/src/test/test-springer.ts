/**
 * Final test for SpringerSearcher with both Meta and OpenAccess APIs
 */

import { SpringerSearcher } from '../platforms/SpringerSearcher.js';
import dotenv from 'dotenv';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

// Load environment variables
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
dotenv.config({ path: join(__dirname, '../../.env') });

console.log('=== Testing SpringerSearcher ===\n');

async function testSpringerSearcher() {
  const searcher = new SpringerSearcher(process.env.SPRINGER_API_KEY);
  
  // Test 1: Basic search using Meta API
  console.log('1. Basic search (Meta API)');
  try {
    const papers = await searcher.search('machine learning', { maxResults: 3 });
    console.log(`   ✅ Found ${papers.length} papers`);
    if (papers.length > 0) {
      const first = papers[0];
      console.log(`   First paper:`);
      console.log(`     - Title: ${first.title}`);
      console.log(`     - DOI: ${first.doi}`);
      console.log(`     - Authors: ${first.authors.join(', ')}`);
      console.log(`     - Has PDF: ${!!first.pdfUrl}`);
      console.log(`     - Open Access: ${first.extra?.openAccess || false}`);
    }
  } catch (error: any) {
    console.error(`   ❌ Error: ${error.message}`);
  }
  
  console.log('\n2. Search with filters');
  try {
    const papers = await searcher.search('COVID-19', { 
      maxResults: 2,
      year: '2020-2021',
      journal: 'Nature'
    });
    console.log(`   ✅ Found ${papers.length} papers with filters`);
  } catch (error: any) {
    console.error(`   ❌ Error: ${error.message}`);
  }
  
  console.log('\n3. Search for open access papers');
  try {
    const papers = await searcher.search('artificial intelligence', { 
      maxResults: 5,
      openAccess: true
    } as any);
    console.log(`   ✅ Found ${papers.length} papers`);
    
    // Count how many are actually open access
    let openCount = 0;
    for (const paper of papers) {
      if (paper.extra?.openAccess === true || paper.extra?.openAccess === 'true') {
        openCount++;
      }
    }
    console.log(`   Open access papers: ${openCount}/${papers.length}`);
  } catch (error: any) {
    console.error(`   ❌ Error: ${error.message}`);
  }
  
  console.log('\n4. Search by DOI');
  try {
    const papers = await searcher.search('10.1007/s00453-020-00785-5', { maxResults: 1 });
    if (papers.length > 0) {
      console.log(`   ✅ Found paper by DOI`);
      console.log(`     - Title: ${papers[0].title}`);
      console.log(`     - DOI: ${papers[0].doi}`);
    } else {
      console.log(`   ❌ Paper not found by DOI`);
    }
  } catch (error: any) {
    console.error(`   ❌ Error: ${error.message}`);
  }
  
  console.log('\n5. Test download PDF');
  try {
    // Search for an open access paper
    const papers = await searcher.search('COVID-19', { 
      maxResults: 10,
      openAccess: true
    } as any);
    
    // Find one with a PDF URL
    const paperWithPdf = papers.find(p => p.pdfUrl);
    if (paperWithPdf) {
      console.log(`   Found paper with PDF: ${paperWithPdf.title?.substring(0, 50)}...`);
      console.log(`   PDF URL: ${paperWithPdf.pdfUrl}`);
      // Don't actually download to avoid creating files
      console.log(`   ✅ PDF URL available (download skipped in test)`);
    } else {
      console.log(`   ⚠️ No papers with PDF URLs found`);
    }
  } catch (error: any) {
    console.error(`   ❌ Error: ${error.message}`);
  }
  
  console.log('\n6. Check capabilities');
  const capabilities = searcher.getCapabilities();
  console.log('   Capabilities:', capabilities);
  
  console.log('\n7. Check platform status');
  try {
    // Test if API is working by doing a minimal search
    const testSearch = await searcher.search('test', { maxResults: 1 });
    console.log(`   ✅ Platform status: operational`);
    console.log(`   Message: Successfully connected to Springer API`);
  } catch (error: any) {
    console.error(`   ❌ Platform status: error - ${error.message}`);
  }
}

// Run tests
testSpringerSearcher().then(() => {
  console.log('\n=== Tests Complete ===');
}).catch(error => {
  console.error('Unexpected error:', error);
});
