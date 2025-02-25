#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
from typing import Dict, Optional, Any, List
import requests
from datetime import datetime, timedelta
import json
from utils.logger import logger

class CoinGeckoHandler:
    def __init__(self, base_url: str, cache_duration: int = 60):
        """
        Initialize CoinGecko handler with rate limiting and caching
        
        Args:
            base_url (str): Base URL for CoinGecko API
            cache_duration (int): How long to cache responses in seconds (default 60)
        """
        self.base_url = base_url
        self.session = requests.Session()
        self.session.timeout = (30, 90)
        self.last_request_time = 0
        self.min_request_interval = 6.0  # Minimum 6 seconds between requests (10 requests per minute)
        self.cache_duration = cache_duration
        self.cache = {}
        self.rate_limit_remaining = None
        self.rate_limit_reset_at = None
        
        # Track API statistics
        self.daily_requests = 0
        self.daily_reset_time = datetime.now()
        self.failed_requests = 0
        
        logger.logger.info(f"CoinGecko handler initialized with {cache_duration}s cache duration")

    def _update_rate_limits(self, response: requests.Response) -> None:
        """Update rate limit information from response headers"""
        try:
            self.rate_limit_remaining = int(response.headers.get('X-RateLimit-Remaining', 0))
            reset_time = int(response.headers.get('X-RateLimit-Reset', 0))
            self.rate_limit_reset_at = datetime.fromtimestamp(reset_time)
            
            logger.logger.debug(
                f"Rate limits updated - Remaining: {self.rate_limit_remaining}, "
                f"Resets at: {self.rate_limit_reset_at}"
            )
        except Exception as e:
            logger.logger.warning(f"Failed to parse rate limit headers: {str(e)}")

    def _should_use_cache(self, cache_key: str) -> bool:
        """Check if we should use cached data"""
        if cache_key not in self.cache:
            return False
            
        cache_entry = self.cache[cache_key]
        age = (datetime.now() - cache_entry['timestamp']).total_seconds()
        
        # Use cache if data is fresh enough
        return age < self.cache_duration

    def _cache_response(self, cache_key: str, data: Any) -> None:
        """Cache API response data"""
        self.cache[cache_key] = {
            'data': data,
            'timestamp': datetime.now()
        }
        logger.logger.debug(f"Cached response for key: {cache_key}")

    def _clean_old_cache(self) -> None:
        """Remove expired entries from cache"""
        now = datetime.now()
        expired_keys = [
            key for key, entry in self.cache.items()
            if (now - entry['timestamp']).total_seconds() > self.cache_duration
        ]
        
        for key in expired_keys:
            del self.cache[key]
            
        if expired_keys:
            logger.logger.debug(f"Cleaned {len(expired_keys)} expired cache entries")

    def _wait_for_rate_limit(self) -> None:
        """Wait if necessary to respect rate limits"""
        now = time.time()
        time_since_last_request = now - self.last_request_time
        
        if time_since_last_request < self.min_request_interval:
            sleep_time = self.min_request_interval - time_since_last_request
            logger.logger.debug(f"Rate limit wait: sleeping for {sleep_time:.2f}s")
            time.sleep(sleep_time)
            
        # Reset daily counters if needed
        if (datetime.now() - self.daily_reset_time).days > 0:
            self.daily_requests = 0
            self.failed_requests = 0
            self.daily_reset_time = datetime.now()
            logger.logger.info("Reset daily API request counters")

    def _handle_rate_limit_response(self) -> None:
        """Handle 429 Too Many Requests response"""
        wait_time = 60  # Default 1 minute wait
        
        if self.rate_limit_reset_at:
            # Wait until rate limit resets, plus 1 second buffer
            wait_time = max(
                1,
                (self.rate_limit_reset_at - datetime.now()).total_seconds() + 1
            )
            
        logger.logger.warning(f"Rate limit exceeded. Waiting {wait_time:.0f}s before retry")
        time.sleep(wait_time)

    def get_market_data(self, params: Dict[str, Any], max_retries: int = 3) -> Optional[Dict[str, Any]]:
        """
        Fetch market data from CoinGecko with caching and rate limiting
        
        Args:
            params (Dict[str, Any]): Query parameters for the request
            max_retries (int): Maximum number of retry attempts
            
        Returns:
            Optional[Dict[str, Any]]: Market data or None if request fails
        """
        cache_key = f"markets_{json.dumps(params, sort_keys=True)}"
        
        # Check cache first
        if self._should_use_cache(cache_key):
            logger.logger.debug(f"Using cached data for: {params.get('ids', '')}")
            return self.cache[cache_key]['data']
            
        retry_count = 0
        base_wait = 5  # Base wait time in seconds
        
        while retry_count < max_retries:
            try:
                self._wait_for_rate_limit()
                
                url = f"{self.base_url}/coins/markets"
                logger.logger.debug(f"Requesting market data for: {params.get('ids', '')}")
                
                self.last_request_time = time.time()
                self.daily_requests += 1
                
                response = self.session.get(url, params=params)
                
                # Update rate limit info
                self._update_rate_limits(response)
                
                if response.status_code == 200:
                    data = response.json()
                    self._cache_response(cache_key, data)
                    logger.log_coingecko_request("/markets", success=True)
                    
                    # Log successful request details
                    logger.logger.info(
                        f"Successfully fetched market data for {params.get('ids', '')} "
                        f"(Daily requests: {self.daily_requests})"
                    )
                    return data
                    
                elif response.status_code == 429:  # Too Many Requests
                    self.failed_requests += 1
                    logger.logger.warning(
                        f"Rate limit hit (Failed requests today: {self.failed_requests})"
                    )
                    self._handle_rate_limit_response()
                    retry_count += 1
                    continue
                    
                else:
                    self.failed_requests += 1
                    wait_time = base_wait * (2 ** retry_count)
                    logger.logger.error(
                        f"Request failed with status {response.status_code}. "
                        f"Waiting {wait_time}s before retry {retry_count + 1}/{max_retries}"
                    )
                    time.sleep(wait_time)
                    retry_count += 1
                    
            except requests.exceptions.Timeout:
                self.failed_requests += 1
                wait_time = base_wait * (2 ** retry_count)
                logger.logger.warning(f"Request timeout, waiting {wait_time}s before retry")
                time.sleep(wait_time)
                retry_count += 1
                
            except Exception as e:
                self.failed_requests += 1
                logger.log_error("CoinGecko Request", str(e))
                logger.log_coingecko_request("/markets", success=False)
                return None
                
        logger.log_error("CoinGecko API", "Maximum retries reached")
        return None

    def get_request_stats(self) -> Dict[str, Any]:
        """Get statistics about API usage"""
        return {
            'daily_requests': self.daily_requests,
            'failed_requests': self.failed_requests,
            'cache_size': len(self.cache),
            'rate_limit_remaining': self.rate_limit_remaining,
            'rate_limit_reset_at': self.rate_limit_reset_at,
        }
