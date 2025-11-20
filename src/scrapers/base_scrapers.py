from playwright.sync_api import sync_playwright, Page, Browser
from bs4 import BeautifulSoup
import time
import logging
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BaseScraper:
    """Base class for all scrapers with Playwright"""
    
    def __init__(self, headless: bool = True):
        """
        Initialize the scraper
        
        Args:
            headless: Run browser in headless mode (invisible)
        """
        self.headless = headless
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
    
    def start(self):
        """
        Start Playwright and launch browser
        
        Steps:
        1. Start playwright
        2. Launch chromium browser
        3. Create browser context with user agent
        4. Create new page
        """
        logger.info('Starting Playwright browser....')
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            headless = self.headless,
            args=['--no-sandbox']
        )
        self.context = self.browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        self.page = self.context.new_page()
        logger.info('Browser Started')
    
    def stop(self):
        """
        Stop browser and cleanup

        Steps:
        1. Close browser if it exists
        2. Stop playwright if it exists
        3. Log message
        """
        try:
            if self.browser:
                self.browser.close()
        except Exception as e:
            logger.warning(f"Error closing browser: {e}")

        try:
            if self.playwright:
                self.playwright.stop()
        except Exception as e:
            logger.warning(f"Error stopping playwright: {e}")

        logger.info('Browser closed')
    
    def goto(self, url: str) -> bool:
        """
        Navigate to a URL
        
        Args:
            url: The URL to navigate to
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            logger.info(f'Navigating to {url}')
            self.page.goto(url)
            time.sleep(2)
            return True
        except Exception as e:
            logger.info(f'Navigation failed: {e}')
            return False
    
    def get_html(self) -> BeautifulSoup:
        """
        Get current page HTML as BeautifulSoup object
        
        Returns:
            BeautifulSoup: Parsed HTML
        """
        content = self.page.content()

        soup = BeautifulSoup(content, 'html.parser')

        return soup