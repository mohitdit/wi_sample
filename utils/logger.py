import logging
import sys

def setup_logger():
    """Configures and returns a simple logger instance."""
    logger = logging.getLogger('WebScraper')
    logger.setLevel(logging.INFO)
    
    # Remove all existing handlers to prevent duplicates
    logger.handlers.clear()
    
    # Prevent propagation to root logger
    logger.propagate = False
    
    # Add single handler
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
        
    return logger

# Initialize the logger for easy importing
log = setup_logger()