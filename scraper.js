// scraper.js
import { gotScraping } from 'got-scraping';

async function scrapeData(url) {
    try {
        const response = await gotScraping(url);
        console.log(response.body);  // Return the scraped content or handle as needed
    } catch (error) {
        console.error('Error scraping the URL:', error);
    }
}

// Read URL argument from command line
const url = process.argv[2];
scrapeData(url);
