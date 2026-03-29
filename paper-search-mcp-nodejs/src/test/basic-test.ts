/**
 * 基础功能测试
 * 用于验证核心组件是否正常工作
 */

import { ArxivSearcher } from '../platforms/ArxivSearcher.js';
import { WebOfScienceSearcher } from '../platforms/WebOfScienceSearcher.js';
import { PubMedSearcher } from '../platforms/PubMedSearcher.js';
import { PaperFactory } from '../models/Paper.js';

async function testArxivSearch() {
  console.log('🧪 Testing arXiv Search...');
  
  const searcher = new ArxivSearcher();
  
  try {
    console.log('Platform capabilities:', searcher.getCapabilities());
    
    const results = await searcher.search('machine learning', { maxResults: 3 });
    console.log(`Found ${results.length} papers from arXiv`);
    
    if (results.length > 0) {
      const firstPaper = results[0];
      console.log('First paper:', {
        id: firstPaper.paperId,
        title: firstPaper.title.substring(0, 100) + '...',
        authors: firstPaper.authors.slice(0, 3),
        source: firstPaper.source
      });
      
      // 测试数据转换
      const dictFormat = PaperFactory.toDict(firstPaper);
      console.log('✅ Data conversion successful');
    }
    
    console.log('✅ arXiv test passed');
  } catch (error) {
    console.error('❌ arXiv test failed:', error);
  }
}

async function testWebOfScienceSearch() {
  console.log('\n🧪 Testing Web of Science Search...');
  
  const apiKey = process.env.WOS_API_KEY;
  if (!apiKey) {
    console.log('⚠️  Skipping Web of Science test - no API key provided');
    return;
  }
  
  const searcher = new WebOfScienceSearcher(apiKey);
  
  try {
    console.log('Platform capabilities:', searcher.getCapabilities());
    console.log('API key status:', searcher.hasApiKey() ? 'configured' : 'missing');
    
    // 测试简单搜索
    const results = await searcher.search('machine learning', { maxResults: 2 });
    console.log(`Found ${results.length} papers from Web of Science`);
    
    if (results.length > 0) {
      const firstPaper = results[0];
      console.log('First paper:', {
        id: firstPaper.paperId,
        title: firstPaper.title.substring(0, 100) + '...',
        citationCount: firstPaper.citationCount,
        source: firstPaper.source
      });
    }
    
    console.log('✅ Web of Science test passed');
  } catch (error: any) {
    if (error.message.includes('401') || error.message.includes('403')) {
      console.log('⚠️  Web of Science test failed - Invalid API key');
    } else {
      console.error('❌ Web of Science test failed:', error.message);
    }
  }
}

async function testPaperModel() {
  console.log('\n🧪 Testing Paper Model...');
  
  try {
    // 测试Paper工厂
    const testPaper = PaperFactory.create({
      paperId: 'test-123',
      title: 'Test Paper Title',
      source: 'test',
      authors: ['Author One', 'Author Two'],
      abstract: 'This is a test abstract',
      doi: '10.1000/test.123',
      publishedDate: new Date('2023-01-01'),
      pdfUrl: 'https://example.com/test.pdf',
      url: 'https://example.com/paper/test-123'
    });
    
    // 验证创建的对象
    console.log('Created paper:', {
      id: testPaper.paperId,
      title: testPaper.title,
      authorCount: testPaper.authors.length,
      hasAbstract: !!testPaper.abstract
    });
    
    // 测试验证功能
    const isValid = PaperFactory.validate(testPaper);
    console.log('Paper validation:', isValid ? '✅ valid' : '❌ invalid');
    
    // 测试字典转换
    const dictFormat = PaperFactory.toDict(testPaper);
    console.log('Dictionary conversion keys:', Object.keys(dictFormat).length);
    
    console.log('✅ Paper model test passed');
  } catch (error) {
    console.error('❌ Paper model test failed:', error);
  }
}

async function testPubMedSearch() {
  console.log('\n🧪 Testing PubMed Search...');
  
  const pubmedSearcher = new PubMedSearcher(process.env.PUBMED_API_KEY);
  
  try {
    console.log('Platform capabilities:', pubmedSearcher.getCapabilities());
    console.log('API key status:', pubmedSearcher.hasApiKey() ? 'configured' : 'not configured');
    console.log('Rate limiter status:', pubmedSearcher.getRateLimiterStatus());
    
    // 测试简单搜索
    const results = await pubmedSearcher.search('COVID-19', { maxResults: 3 });
    console.log(`Found ${results.length} papers from PubMed`);
    
    if (results.length > 0) {
      const firstPaper = results[0];
      console.log('First paper:', {
        id: firstPaper.paperId,
        title: firstPaper.title.substring(0, 100) + '...',
        authors: firstPaper.authors.slice(0, 2),
        journal: firstPaper.journal,
        source: firstPaper.source
      });
    }
    
    console.log('✅ PubMed test passed');
  } catch (error: any) {
    if (error.message.includes('rate limit') || error.message.includes('429')) {
      console.log('⚠️  PubMed test failed - Rate limit exceeded (this is expected for testing)');
    } else {
      console.error('❌ PubMed test failed:', error.message);
    }
  }
}

async function runAllTests() {
  console.log('🚀 Starting Paper Search MCP Tests\n');
  
  await testPaperModel();
  await testArxivSearch();
  await testWebOfScienceSearch();
  await testPubMedSearch();
  
  console.log('\n🎉 Test suite completed!');
}

// 运行测试
if (import.meta.url === `file://${process.argv[1]}`) {
  runAllTests().catch(console.error);
}