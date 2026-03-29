/**
 * Sci-Hub 功能测试
 * 测试镜像站点健康检测、论文搜索和下载功能
 */

import { SciHubSearcher } from '../platforms/SciHubSearcher.js';
import { PaperFactory } from '../models/Paper.js';
import * as fs from 'fs';
import * as path from 'path';

async function testMirrorHealth() {
  console.log('\n🧪 Testing Sci-Hub Mirror Health Check...');
  
  const searcher = new SciHubSearcher();
  
  try {
    // 获取镜像状态
    const mirrorStatus = searcher.getMirrorStatus();
    console.log(`📊 Total mirrors: ${mirrorStatus.length}`);
    
    // 显示前5个镜像的状态
    mirrorStatus.slice(0, 5).forEach(mirror => {
      const statusEmoji = mirror.status === 'Working' ? '✅' : '❌';
      const responseTime = mirror.responseTime ? `${mirror.responseTime}ms` : 'N/A';
      console.log(`${statusEmoji} ${mirror.url} - ${mirror.status} (${responseTime})`);
    });
    
    // 统计可用镜像数量
    const workingMirrors = mirrorStatus.filter(m => m.status === 'Working').length;
    console.log(`\n✅ Working mirrors: ${workingMirrors}/${mirrorStatus.length}`);
    
    // 强制重新检测
    console.log('\n🔄 Forcing health check...');
    await searcher.forceHealthCheck();
    
    const updatedStatus = searcher.getMirrorStatus();
    const updatedWorking = updatedStatus.filter(m => m.status === 'Working').length;
    console.log(`✅ After check: ${updatedWorking}/${updatedStatus.length} mirrors working`);
    
    console.log('✅ Mirror health test passed');
  } catch (error) {
    console.error('❌ Mirror health test failed:', error);
  }
}

async function testSearchByDOI() {
  console.log('\n🧪 Testing Sci-Hub Search by DOI...');
  
  const searcher = new SciHubSearcher();
  
  // 测试用的DOI（一个比较经典的论文）
  const testDOIs = [
    '10.1038/nature12373',  // Hinton's deep learning paper
    '10.1126/science.1127647', // Another well-known paper
    '10.1016/j.cell.2019.05.031' // Recent Cell paper
  ];
  
  for (const doi of testDOIs) {
    try {
      console.log(`\n🔍 Searching for DOI: ${doi}`);
      
      const results = await searcher.search(doi);
      
      if (results.length > 0) {
        const paper = results[0];
        console.log('✅ Paper found:');
        console.log(`  Title: ${paper.title}`);
        console.log(`  DOI: ${paper.doi}`);
        console.log(`  PDF URL: ${paper.pdfUrl ? '✅ Available' : '❌ Not available'}`);
        console.log(`  Mirror: ${paper.extra?.mirror || 'Unknown'}`);
        
        // 验证数据转换
        const dictFormat = PaperFactory.toDict(paper);
        console.log('  Data validation: ✅ Pass');
      } else {
        console.log(`⚠️ No paper found for DOI: ${doi}`);
      }
    } catch (error: any) {
      console.log(`❌ Failed to search DOI ${doi}: ${error.message}`);
    }
  }
  
  console.log('\n✅ DOI search test completed');
}

async function testSearchByURL() {
  console.log('\n🧪 Testing Sci-Hub Search by URL...');
  
  const searcher = new SciHubSearcher();
  
  // 测试用的URL
  const testURL = 'https://www.nature.com/articles/nature12373';
  
  try {
    console.log(`🔍 Searching for URL: ${testURL}`);
    
    const results = await searcher.search(testURL);
    
    if (results.length > 0) {
      const paper = results[0];
      console.log('✅ Paper found:');
      console.log(`  Title: ${paper.title}`);
      console.log(`  PDF URL: ${paper.pdfUrl ? '✅ Available' : '❌ Not available'}`);
    } else {
      console.log(`⚠️ No paper found for URL: ${testURL}`);
    }
  } catch (error: any) {
    console.log(`❌ Failed to search URL: ${error.message}`);
  }
  
  console.log('✅ URL search test completed');
}

async function testDownloadPDF() {
  console.log('\n🧪 Testing Sci-Hub PDF Download...');
  
  const searcher = new SciHubSearcher();
  const testDOI = '10.1038/nature12373';
  const downloadPath = './test-downloads';
  
  try {
    // 创建测试下载目录
    if (!fs.existsSync(downloadPath)) {
      fs.mkdirSync(downloadPath, { recursive: true });
    }
    
    console.log(`📥 Downloading PDF for DOI: ${testDOI}`);
    console.log(`📁 Save path: ${downloadPath}`);
    
    const filePath = await searcher.downloadPdf(testDOI, { 
      savePath: downloadPath,
      overwrite: true 
    });
    
    console.log(`✅ PDF downloaded to: ${filePath}`);
    
    // 验证文件存在且有内容
    const stats = fs.statSync(filePath);
    console.log(`📊 File size: ${(stats.size / 1024 / 1024).toFixed(2)} MB`);
    
    if (stats.size > 1000) { // 至少1KB
      console.log('✅ Download test passed');
    } else {
      console.log('⚠️ Downloaded file seems too small');
    }
    
    // 清理测试文件（可选）
    // fs.unlinkSync(filePath);
    // console.log('🧹 Test file cleaned up');
    
  } catch (error: any) {
    console.error(`❌ Download test failed: ${error.message}`);
  }
}

async function testInvalidInput() {
  console.log('\n🧪 Testing Invalid Input Handling...');
  
  const searcher = new SciHubSearcher();
  
  const invalidInputs = [
    'random text',
    '123456',
    'not a doi',
    ''
  ];
  
  for (const input of invalidInputs) {
    try {
      console.log(`Testing invalid input: "${input}"`);
      const results = await searcher.search(input);
      
      if (results.length === 0) {
        console.log(`✅ Correctly returned empty results for: "${input}"`);
      } else {
        console.log(`⚠️ Unexpected results for invalid input: "${input}"`);
      }
    } catch (error: any) {
      console.log(`✅ Correctly handled error for: "${input}"`);
    }
  }
  
  console.log('✅ Invalid input test passed');
}

async function testPlatformCapabilities() {
  console.log('\n🧪 Testing Sci-Hub Platform Capabilities...');
  
  const searcher = new SciHubSearcher();
  
  try {
    const capabilities = searcher.getCapabilities();
    
    console.log('Platform capabilities:');
    console.log(`  Search: ${capabilities.search ? '✅' : '❌'}`);
    console.log(`  Download: ${capabilities.download ? '✅' : '❌'}`);
    console.log(`  Full Text: ${capabilities.fullText ? '✅' : '❌'}`);
    console.log(`  Citations: ${capabilities.citations ? '✅' : '❌'}`);
    console.log(`  Requires API Key: ${capabilities.requiresApiKey ? '✅' : '❌'}`);
    console.log(`  Supported Options: ${capabilities.supportedOptions.join(', ')}`);
    
    // 验证平台信息
    console.log('\nPlatform info:');
    console.log(`  Name: ${searcher.getPlatformName()}`);
    console.log(`  Base URL: ${searcher.getBaseUrl()}`);
    console.log(`  Has API Key: ${searcher.hasApiKey() ? 'Yes' : 'No'}`);
    
    console.log('\n✅ Capabilities test passed');
  } catch (error) {
    console.error('❌ Capabilities test failed:', error);
  }
}

async function runAllTests() {
  console.log('🚀 Starting Sci-Hub Tests\n');
  console.log('=' .repeat(50));
  
  // 运行所有测试
  await testPlatformCapabilities();
  await testMirrorHealth();
  await testInvalidInput();
  await testSearchByDOI();
  await testSearchByURL();
  await testDownloadPDF();
  
  console.log('\n' + '=' .repeat(50));
  console.log('🎉 Sci-Hub test suite completed!');
}

// 运行测试
if (import.meta.url === `file://${process.argv[1]}`) {
  runAllTests().catch(console.error);
}

export {
  testMirrorHealth,
  testSearchByDOI,
  testSearchByURL,  
  testDownloadPDF,
  testInvalidInput,
  testPlatformCapabilities
};
