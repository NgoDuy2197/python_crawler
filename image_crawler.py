import os
import time
import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ImageCrawler:
    def __init__(self):
        load_dotenv()
        self.base_url = os.getenv('START_URL')
        self.pager_selector = os.getenv('PAGER_SELECTOR', '.next-page')
        self.max_pages = int(os.getenv('MAX_PAGES', 10))
        self.timeout = int(os.getenv('PAGE_LOAD_TIMEOUT', 30))
        self.user_agent = os.getenv('USER_AGENT')
        
        # Create RESULT directory if it doesn't exist
        self.result_dir = Path('RESULT')
        self.result_dir.mkdir(exist_ok=True)
        
        # Create a timestamp for this crawl session
        self.timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.session_dir = self.result_dir / self.timestamp
        self.session_dir.mkdir(exist_ok=True)
        
        # Initialize webdriver and other attributes
        self.driver = None
        self.visited_urls = set()
        self.image_urls = set()
        
        # Set up logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler(self.session_dir / 'crawler.log')
            ]
        )
        
        # Initialize WebDriver
        if not self.setup_driver():
            raise Exception("Failed to initialize WebDriver. Please check if Chrome is installed and up to date.")
    
    def setup_driver(self):
        """Initialize and configure the Selenium WebDriver."""
        from selenium.webdriver.chrome.service import Service as ChromeService
        
        options = Options()
        options.add_argument('--headless=new')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-software-rasterizer')
        options.add_argument('--log-level=3')
        options.add_argument('--silent')
        
        if self.user_agent:
            options.add_argument(f'user-agent={self.user_agent}')
        
        try:
            # Try to use ChromeDriverManager to get the appropriate driver
            try:
                from webdriver_manager.chrome import ChromeDriverManager
                from webdriver_manager.core.utils import ChromeType
                
                driver_path = ChromeDriverManager(
                    chrome_type=ChromeType.CHROMIUM,
                    print_first_line=False
                ).install()
                service = ChromeService(executable_path=driver_path)
            except Exception as e:
                logger.warning(f"Using system ChromeDriver: {e}")
                service = ChromeService()
            
            self.driver = webdriver.Chrome(service=service, options=options)
            self.driver.set_page_load_timeout(self.timeout)
            logger.info("WebDriver initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize WebDriver: {e}")
            # Try one more time with default Chrome
            try:
                logger.info("Trying with default Chrome...")
                self.driver = webdriver.Chrome(options=options)
                self.driver.set_page_load_timeout(self.timeout)
                logger.info("WebDriver initialized with default Chrome")
                return True
            except Exception as e2:
                logger.error(f"Failed to initialize default Chrome: {e2}")
                raise Exception(f"Failed to initialize WebDriver: {e}. Also failed to use default Chrome: {e2}")
    
    def is_valid_url(self, url):
        """Check if URL is valid and belongs to the same domain."""
        if not url or url.startswith('javascript:') or url.startswith('mailto:'):
            return False
            
        # Handle relative URLs
        if not url.startswith(('http://', 'https://')):
            url = urljoin(self.base_url, url)
        
        # Check if URL belongs to the same domain
        base_domain = urlparse(self.base_url).netloc
        url_domain = urlparse(url).netloc
        
        return url_domain == base_domain
    
    def get_absolute_url(self, url):
        """Convert relative URL to absolute."""
        if url.startswith(('http://', 'https://')):
            return url
        return urljoin(self.base_url, url)
    
    def extract_links(self, url):
        """Extract all links from a page."""
        try:
            self.driver.get(url)
            WebDriverWait(self.driver, self.timeout).until(
                lambda d: d.execute_script('return document.readyState') == 'complete'
            )
            
            # Extract all links
            links = set()
            elements = self.driver.find_elements(By.TAG_NAME, 'a')
            for element in elements:
                try:
                    href = element.get_attribute('href')
                    if href and self.is_valid_url(href):
                        links.add(self.get_absolute_url(href))
                except Exception as e:
                    logger.debug(f"Error extracting link: {e}")
            
            return links
            
        except TimeoutException:
            logger.warning(f"Timeout while loading page: {url}")
            return set()
        except Exception as e:
            logger.error(f"Error extracting links from {url}: {e}")
            return set()
    
    def extract_images(self, url):
        """Extract all image URLs from a page."""
        try:
            self.driver.get(url)
            WebDriverWait(self.driver, self.timeout).until(
                lambda d: d.execute_script('return document.readyState') == 'complete'
            )
            
            # Extract image URLs
            image_urls = set()
            img_elements = self.driver.find_elements(By.TAG_NAME, 'img')
            
            for img in img_elements:
                try:
                    src = img.get_attribute('src') or img.get_attribute('data-src')
                    if src and self.is_valid_url(src):
                        image_urls.add(self.get_absolute_url(src))
                except Exception as e:
                    logger.debug(f"Error extracting image URL: {e}")
            
            return image_urls
            
        except TimeoutException:
            logger.warning(f"Timeout while loading page for images: {url}")
            return set()
        except Exception as e:
            logger.error(f"Error extracting images from {url}: {e}")
            return set()
    
    def has_next_page(self):
        """Check if there's a next page using the pager selector."""
        try:
            # Try to find elements that might indicate the next page
            next_buttons = self.driver.find_elements(By.CSS_SELECTOR, f"{self.pager_selector}, a[rel='next'], .pagination-next, .next, .page-next")
            
            # Log all found buttons for debugging
            logger.debug(f"Found {len(next_buttons)} potential next page buttons")
            
            # Check each button to see if it's visible and clickable
            for button in next_buttons:
                try:
                    if button.is_displayed() and button.is_enabled():
                        logger.debug(f"Found visible and enabled next page button: {button.get_attribute('outerHTML')[:100]}...")
                        return True
                except Exception as e:
                    logger.debug(f"Error checking button: {e}")
                    continue
                    
            return False
            
        except Exception as e:
            logger.error(f"Error checking for next page: {e}")
            return False
    
    def go_to_next_page(self):
        """Navigate to the next page using the pager selector."""
        current_url = self.driver.current_url
        
        try:
            # Try to find and click the next page button
            next_buttons = self.driver.find_elements(By.CSS_SELECTOR, f"{self.pager_selector}, a[rel='next'], .pagination-next, .next, .page-next")
            
            for button in next_buttons:
                try:
                    if button.is_displayed() and button.is_enabled():
                        # Get the URL before clicking
                        next_url = button.get_attribute('href')
                        if next_url and next_url != current_url:
                            # Scroll to the button and click
                            self.driver.execute_script("arguments[0].scrollIntoView(true);", button)
                            time.sleep(1)  # Small delay for any animations
                            button.click()
                            
                            # Wait for the page to load
                            WebDriverWait(self.driver, self.timeout).until(
                                lambda d: d.execute_script('return document.readyState') == 'complete'
                            )
                            
                            # Wait for URL to change
                            WebDriverWait(self.driver, self.timeout).until(
                                lambda d: d.current_url != current_url
                            )
                            
                            # Additional wait for dynamic content
                            time.sleep(2)
                            return self.driver.current_url
                except Exception as e:
                    logger.debug(f"Tried to click button but got error: {e}")
                    continue
                    
            # If no button was clickable, try to find the next page URL directly
            next_links = self.driver.find_elements(By.CSS_SELECTOR, f"a[href*='page'], a[href*='p='], a[href*='/2']")
            for link in next_links:
                try:
                    href = link.get_attribute('href')
                    if href and href != current_url and 'page' in href.lower() or 'p=' in href.lower():
                        self.driver.get(href)
                        WebDriverWait(self.driver, self.timeout).until(
                            lambda d: d.execute_script('return document.readyState') == 'complete'
                        )
                        return self.driver.current_url
                except Exception as e:
                    logger.debug(f"Tried to follow link but got error: {e}")
                    continue
                    
            return None
            
        except Exception as e:
            logger.error(f"Error navigating to next page: {e}")
            return None
    
    def generate_html_report(self):
        """Generate an HTML report with all found images."""
        if not self.image_urls:
            logger.warning("No images found to generate report")
            return
        
        # Create a template with placeholders for dynamic content
        template = """<!DOCTYPE html>
        <html>
        <head>
            <title>Image Crawler Results - {{timestamp}}</title>
            <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600&display=swap" rel="stylesheet">
            <style>
                :root {
                    --primary-color: #ff6b6b;
                    --secondary-color: #4ecdc4;
                    --bg-color: #f8f9fa;
                    --card-bg: #ffffff;
                    --text-color: #333;
                    --text-light: #6c757d;
                    --shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
                    --transition: all 0.3s ease;
                }
                
                * {
                    margin: 0;
                    padding: 0;
                    box-sizing: border-box;
                }
                
                body {
                    font-family: 'Poppins', sans-serif;
                    background-color: var(--bg-color);
                    color: var(--text-color);
                    line-height: 1.6;
                    padding: 20px;
                }
                
                .container {
                    max-width: 1400px;
                    margin: 0 auto;
                    padding: 20px;
                }
                
                header {
                    text-align: center;
                    margin-bottom: 30px;
                    padding: 20px;
                    background: linear-gradient(135deg, var(--primary-color), #ff8e8e);
                    color: white;
                    border-radius: 10px;
                    box-shadow: var(--shadow);
                    cursor: pointer;
                }
                
                h1 {
                    font-size: 2.5rem;
                    margin-bottom: 10px;
                    font-weight: 600;
                }
                
                .stats {
                    display: flex;
                    justify-content: center;
                    gap: 20px;
                    margin-top: 15px;
                    font-size: 0.9rem;
                    opacity: 0.9;
                }
                
                .image-container {
                    display: grid;
                    grid-template-columns: repeat(4, 1fr);
                    gap: 20px;
                    margin-top: 20px;
                }
                
                .image-item {
                    background: var(--card-bg);
                    border-radius: 12px;
                    overflow: hidden;
                    box-shadow: var(--shadow);
                    transition: var(--transition);
                    display: flex;
                    flex-direction: column;
                }
                
                .image-item:hover {
                    transform: translateY(-5px);
                    box-shadow: 0 10px 25px rgba(0, 0, 0, 0.15);
                }
                
                .image-wrapper {
                    width: 100%;
                    padding-bottom: 100%;
                    position: relative;
                    overflow: hidden;
                }
                
                .image-item img {
                    position: absolute;
                    top: 0;
                    left: 0;
                    width: 100%;
                    height: 100%;
                    object-fit: contain;
                    transition: var(--transition);
                    background: #f5f5f5;
                }
                
                .image-item:hover img {
                    transform: scale(1.05);
                }
                
                .image-details {
                    padding: 15px;
                    flex-grow: 1;
                    display: flex;
                    flex-direction: column;
                }
                
                .image-url {
                    font-size: 0.75rem;
                    color: var(--primary-color);
                    word-break: break-all;
                    text-decoration: none;
                    padding: 8px 12px;
                    background: rgba(255, 107, 107, 0.1);
                    border-radius: 6px;
                    margin-top: 10px;
                    transition: var(--transition);
                    display: inline-block;
                }
                
                .image-url:hover {
                    background: rgba(255, 107, 107, 0.2);
                    color: #e64a4a;
                }
                
                .image-meta {
                    display: flex;
                    justify-content: space-between;
                    font-size: 0.8rem;
                    color: var(--text-light);
                    margin-top: 10px;
                }
                
                .image-index {
                    background: var(--secondary-color);
                    color: white;
                    width: 30px;
                    height: 30px;
                    border-radius: 50%;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    font-weight: 600;
                    position: absolute;
                    top: 10px;
                    right: 10px;
                    z-index: 2;
                }
                
                .no-image {
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    background: #f0f0f0;
                    color: #999;
                    font-size: 0.9rem;
                    height: 200px;
                }
                
                /* Remove mobile-specific styles */
            </style>
        </head>
        <body>
            <div class="container">
                <header>
                    <h1>Image Gallery</h1>
                    <div class="stats">
                        <span>📅 {{timestamp}}</span>
                        <span>🖼️ {{count}} images found</span>
                    </div>
                </header>
                <div class="image-container">
                    {{image_items}}
                </div>
            </div>
            <script>
                // Add smooth scrolling to top when clicking on the header
                try {
                    document.querySelector('header').addEventListener('click', function() {
                        try {
                            window.scrollTo({ top: 0, behavior: 'smooth' });
                        } catch (e) {
                            console.error('Scroll error:', e);
                            window.scrollTo(0, 0);
                        }
                    });
                    
                    // Remove lazy loading and animations
                } catch (e) {
                    console.error('Initialization error:', e);
                }
            </script>
        </body>
        </html>
        """
        
        # Generate image items HTML
        image_items = []
        for idx, img_url in enumerate(sorted(self.image_urls), 1):
            image_items.append(f"""
                <div class="image-item">
                    <div class="image-wrapper">
                        <span class="image-index">{idx}</span>
                        <img src="{img_url}" alt="Image {idx}" loading="eager" onerror="this.parentElement.innerHTML='<div>Image not available</div>'">
                    </div>
                    <div class="image-details">
                        <div class="image-meta">
                            <span>#{idx}</span>
                            <span>🔗 Source</span>
                        </div>
                        <a href="{img_url}" class="image-url" target="_blank" rel="noopener noreferrer">
                            {img_url}
                        </a>
                    </div>
                </div>
            """)
        
        # Format the template with the actual values
        html_content = template.replace('{{timestamp}}', datetime.now().strftime('%Y-%m-%d %H:%M:%S')) \
                             .replace('{{count}}', str(len(self.image_urls))) \
                             .replace('{{image_items}}', '\n'.join(image_items))
        
        report_path = self.session_dir / 'index.html'
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        logger.info(f"HTML report generated: {report_path}")
    
    def crawl(self):
        """Start the crawling process."""
        if not self.base_url:
            logger.error("No START_URL specified in .env file")
            return
        
        logger.info(f"Starting crawl from: {self.base_url}")
        
        current_url = self.base_url
        page_count = 0
        
        try:
            while current_url and (self.max_pages == 0 or page_count < self.max_pages):
                if current_url in self.visited_urls:
                    break
                    
                logger.info(f"Crawling page {page_count + 1}: {current_url}")
                
                # Add to visited URLs
                self.visited_urls.add(current_url)
                
                # Extract images from current page
                images = self.extract_images(current_url)
                if images:
                    self.image_urls.update(images)
                    logger.info(f"Found {len(images)} images on {current_url}")
                
                # Check for next page
                if self.has_next_page():
                    next_url = self.go_to_next_page()
                    if next_url and next_url != current_url:
                        current_url = next_url
                        page_count += 1
                        continue
                
                # If no next page via pager, get all links and find unvisited ones
                links = self.extract_links(current_url)
                unvisited_links = [link for link in links if link not in self.visited_urls]
                
                if unvisited_links:
                    current_url = unvisited_links[0]
                    page_count += 1
                else:
                    break
            
            # Generate HTML report after crawling is complete
            self.generate_html_report()
            
            logger.info(f"Crawling completed. Found {len(self.image_urls)} images in {len(self.visited_urls)} pages.")
            
        except KeyboardInterrupt:
            logger.info("Crawling interrupted by user")
        except Exception as e:
            logger.error(f"Error during crawling: {e}")
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Clean up resources."""
        try:
            if hasattr(self, 'driver'):
                self.driver.quit()
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

def main():
    crawler = ImageCrawler()
    crawler.crawl()

if __name__ == "__main__":
    main()
