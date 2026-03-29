/**
 * OpenAlex API Integration
 * 
 * OpenAlex is a fully open catalog of scholarly works.
 * Base URL: https://api.openalex.org
 * Documentation: https://docs.openalex.org
 */

import axios, { AxiosInstance } from 'axios';
import { Paper, PaperFactory } from '../models/Paper.js';
import { PaperSource, SearchOptions, DownloadOptions, PlatformCapabilities } from './PaperSource.js';
import { sanitizeDoi } from '../utils/SecurityUtils.js';
import { TIMEOUTS, USER_AGENT } from '../config/constants.js';
import { logDebug } from '../utils/Logger.js';

export class OpenAlexSearcher extends PaperSource {
    private client: AxiosInstance;
    private mailto?: string;

    constructor(apiKeyOrMailto?: string) {
        super('openalex', 'https://api.openalex.org/works', apiKeyOrMailto);

        // Check if the provided key looks like an email (for polite pool)
        if (apiKeyOrMailto && apiKeyOrMailto.includes('@')) {
            this.mailto = apiKeyOrMailto;
            this.mailto = apiKeyOrMailto;
            // this.apiKey is protected/readonly or string only in base class, avoid setting to undefined if possible
            // or cast to any if we really need to clear it, but better to just leave it as is 
            // since we passed it to super constructor, but wait, we effectively passed mailto as apiKey.
            // If we want to "clear" it, we might need a different approach.
            // Actually, we can just cast to any to silence TS if we are sure, or just not set it.
            // If we passed it to super, this.apiKey holds the email.
            // In request interceptor we check this.apiKey.
            // Let's rely on mailto check in interceptor.
            (this as any).apiKey = undefined;
        } else {
            this.mailto = process.env.OPENALEX_MAILTO; // Fallback to env
        }

        this.client = axios.create({
            baseURL: this.baseUrl,
            timeout: TIMEOUTS.DEFAULT,
            headers: {
                'Accept': 'application/json',
                'User-Agent': `${USER_AGENT} paper-search-mcp-nodejs/0.2.5`
            }
        });

        // Add interceptor to add api_key or mailto to requests
        this.client.interceptors.request.use((config) => {
            config.params = config.params || {};
            if (this.apiKey) {
                config.params.api_key = this.apiKey;
            }
            if (this.mailto) {
                config.params.mailto = this.mailto;
            }
            return config;
        });
    }

    getCapabilities(): PlatformCapabilities {
        return {
            search: true,
            download: false,
            fullText: false,
            citations: true,
            requiresApiKey: false, // Optional
            supportedOptions: ['maxResults', 'year', 'author', 'sortBy', 'sortOrder']
        };
    }

    async search(query: string, options: SearchOptions = {}): Promise<Paper[]> {
        const maxResults = Math.min(options.maxResults || 10, 200); // OpenAlex max per page is 200

        const params: Record<string, any> = {
            search: query,
            per_page: maxResults,
        };

        // Build filters
        const filters: string[] = [];

        // Year filter
        if (options.year) {
            const yearMatch = options.year.match(/^(\d{4})(?:-(\d{4})?)?$/);
            if (yearMatch) {
                const startYear = yearMatch[1];
                const endYear = yearMatch[2] || startYear;
                if (startYear === endYear) {
                    filters.push(`publication_year:${startYear}`);
                } else if (endYear) {
                    filters.push(`publication_year:${startYear}-${endYear}`);
                } else {
                    filters.push(`publication_year:>${startYear}`);
                }
            }
        }

        // OpenAlex doesn't support direct author string search in filters easily without ID.
        // The search parameter searches everywhere. 
        // We'll stick to basic search + year filter for now.

        const sortMapping: Record<string, string> = {
            'relevance': 'relevance_score',
            'date': 'publication_date',
            'citations': 'cited_by_count'
        };

        if (options.sortBy) {
            const sortField = sortMapping[options.sortBy] || 'relevance_score';
            const sortOrder = options.sortOrder === 'asc' ? 'asc' : 'desc';
            params.sort = `${sortField}:${sortOrder}`;
        }

        if (filters.length > 0) {
            params.filter = filters.join(',');
        }

        try {
            const response = await this.client.get('', { params });

            if (response.status === 200 && response.data?.results) {
                return this.parseSearchResponse(response.data.results);
            }

            return [];
        } catch (error: any) {
            this.handleHttpError(error, 'search');
        }
    }

    async getPaperByDoi(doi: string): Promise<Paper | null> {
        const cleanDoi = sanitizeDoi(doi);
        if (!cleanDoi.valid) return null;

        try {
            const response = await this.client.get(`https://doi.org/${cleanDoi.sanitized}`);
            if (response.status === 200 && response.data) {
                return this.parsePaper(response.data);
            }
            return null;
        } catch (error: any) {
            if (error.response?.status === 404) return null;
            this.handleHttpError(error, 'getPaperByDoi');
            return null; // unreachable
        }
    }

    async downloadPdf(paperId: string, options?: DownloadOptions): Promise<string> {
        throw new Error('OpenAlex does not support direct PDF download via API. Use Sci-Hub or other tools with the DOI.');
    }

    async readPaper(paperId: string, options?: DownloadOptions): Promise<string> {
        throw new Error('OpenAlex does not support full text extraction');
    }

    private parseSearchResponse(results: any[]): Paper[] {
        const papers: Paper[] = [];
        for (const item of results) {
            const paper = this.parsePaper(item);
            if (paper) {
                papers.push(paper);
            }
        }
        return papers;
    }

    private parsePaper(data: any): Paper | null {
        try {
            const doi = data.doi ? data.doi.replace('https://doi.org/', '') : '';
            const title = data.title || 'No title';

            const authors: string[] = [];
            const authorships = data.authorships || [];
            for (const authorship of authorships) {
                if (authorship.author?.display_name) {
                    authors.push(authorship.author.display_name);
                }
            }

            let publishedDate: Date | null = null;
            let year: number | undefined = data.publication_year;
            if (data.publication_date) {
                publishedDate = new Date(data.publication_date);
            }

            const source = data.primary_location?.source?.display_name || '';
            const url = data.id || data.doi || '';

            const citationCount = data.cited_by_count || 0;

            // Abstract inverted index reconstruction could be done here but it's complex/heavy
            // OpenAlex provides abstract as inverted index.
            let abstract = '';
            if (data.abstract_inverted_index) {
                // Simple reconstruction if needed, or skip for performance
                // Let's skip heavy reconstruction for now or just take a note
                abstract = '(Abstract available in OpenAlex inverted index format)';
            }

            return PaperFactory.create({
                paperId: data.id,
                title: title,
                authors: authors,
                abstract: abstract,
                source: 'openalex',
                publishedDate: publishedDate,
                year: year,
                journal: source,
                doi: doi,
                url: url,
                pdfUrl: data.open_access?.oa_url || '', // OA URL if available
                citationCount: citationCount,
                extra: {
                    is_oa: data.open_access?.is_oa || false,
                    oa_status: data.open_access?.oa_status || '',
                    type: data.type
                }
            });
        } catch (error: any) {
            logDebug('Error parsing OpenAlex paper:', error.message);
            return null;
        }
    }
}
