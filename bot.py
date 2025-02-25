#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from typing import Dict, Optional, Any, Union, List, Tuple
import sys
import os
import time
import requests
import re
import numpy as np
from datetime import datetime, timedelta
import anthropic
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.keys import Keys
import random
import statistics

from utils.logger import logger
from utils.browser import browser
from config import config
from coingecko_handler import CoinGeckoHandler
from mood_config import MoodIndicators, determine_advanced_mood, Mood, MemePhraseGenerator
from meme_phrases import MEME_PHRASES

class Layer1AnalysisBot:
    def __init__(self) -> None:
        self.browser = browser
        self.config = config
        self.claude_client = anthropic.Client(api_key=self.config.CLAUDE_API_KEY)
        self.past_predictions = []
        self.meme_phrases = MEME_PHRASES
        self.last_check_time = datetime.now()
        self.last_market_data = {}
        
        # Initialize CoinGecko handler with 60s cache duration
        self.coingecko = CoinGeckoHandler(
            base_url=self.config.COINGECKO_BASE_URL,
            cache_duration=60
        )
        
        self.target_chains = {
            'SOL': 'solana',
            'DOT': 'polkadot'
        }

        self.chain_name_mapping = {
            'SOL': 'solana',
            'DOT': 'polkadot'
        }
        
        self.CORRELATION_THRESHOLD = 0.75  
        self.VOLUME_THRESHOLD = 0.60  
        self.TIME_WINDOW = 24 
        logger.log_startup()

    def _get_historical_volume_data(self, chain: str) -> List[Dict[str, Any]]:
        """
        Get historical volume data for the specified window period
        """
        try:
            window_start = datetime.now() - timedelta(minutes=self.config.VOLUME_WINDOW_MINUTES)
            query = """
                SELECT timestamp, volume
                FROM market_data
                WHERE chain = ? AND timestamp >= ?
                ORDER BY timestamp DESC
            """
            
            conn = self.config.db.conn
            cursor = conn.cursor()
            cursor.execute(query, (chain, window_start))
            results = cursor.fetchall()
            
            volume_data = [
                {
                    'timestamp': datetime.fromisoformat(row[0]),
                    'volume': float(row[1])
                }
                for row in results
            ]
            
            logger.logger.debug(
                f"Retrieved {len(volume_data)} volume data points for {chain} "
                f"over last {self.config.VOLUME_WINDOW_MINUTES} minutes"
            )
            
            return volume_data
            
        except Exception as e:
            logger.log_error(f"Historical Volume Data - {chain}", str(e))
            return []

    def _analyze_volume_trend(self, current_volume: float, historical_data: List[Dict[str, Any]]) -> Tuple[float, str]:
        """
        Analyze volume trend over the window period
        Returns (percentage_change, trend_description)
        """
        if not historical_data:
            return 0.0, "insufficient_data"
            
        try:
            # Calculate average volume excluding the current volume
            historical_volumes = [entry['volume'] for entry in historical_data]
            avg_volume = statistics.mean(historical_volumes) if historical_volumes else current_volume
            
            # Calculate percentage change
            volume_change = ((current_volume - avg_volume) / avg_volume) * 100
            
            # Determine trend
            if volume_change >= self.config.VOLUME_TREND_THRESHOLD:
                trend = "significant_increase"
            elif volume_change <= -self.config.VOLUME_TREND_THRESHOLD:
                trend = "significant_decrease"
            elif volume_change >= 5:  # Smaller but notable increase
                trend = "moderate_increase"
            elif volume_change <= -5:  # Smaller but notable decrease
                trend = "moderate_decrease"
            else:
                trend = "stable"
                
            logger.logger.debug(
                f"Volume trend analysis: {volume_change:.2f}% change from average. "
                f"Current: {current_volume:,.0f}, Avg: {avg_volume:,.0f}, "
                f"Trend: {trend}"
            )
            
            return volume_change, trend
            
        except Exception as e:
            logger.log_error("Volume Trend Analysis", str(e))
            return 0.0, "error"

    def start(self) -> None:
        """Main bot execution loop"""
        try:
            retry_count = 0
            max_setup_retries = 3
            
            while retry_count < max_setup_retries:
                if not self.browser.initialize_driver():
                    retry_count += 1
                    logger.logger.warning(f"Browser initialization attempt {retry_count} failed, retrying...")
                    time.sleep(10)
                    continue
                    
                if not self._login_to_twitter():
                    retry_count += 1
                    logger.logger.warning(f"Twitter login attempt {retry_count} failed, retrying...")
                    time.sleep(15)
                    continue
                    
                break
            
            if retry_count >= max_setup_retries:
                raise Exception("Failed to initialize bot after maximum retries")

            logger.logger.info("Bot initialized successfully")

            while True:
                try:
                    self._run_analysis_cycle()
                    
                    # Calculate sleep time until next regular check
                    time_since_last = (datetime.now() - self.last_check_time).total_seconds()
                    sleep_time = max(0, self.config.BASE_INTERVAL - time_since_last)
                    
                    logger.logger.debug(f"Sleeping for {sleep_time:.1f}s until next check")
                    time.sleep(sleep_time)
                    
                    self.last_check_time = datetime.now()
                    
                except Exception as e:
                    logger.log_error("Analysis Cycle", str(e), exc_info=True)
                    time.sleep(60)  # Shorter sleep on error
                    continue

        except KeyboardInterrupt:
            logger.logger.info("Bot stopped by user")
        except Exception as e:
            logger.log_error("Bot Execution", str(e))
        finally:
            self._cleanup()

    def _should_post_update(self, new_data: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Determine if we should post an update based on market changes
        Returns (should_post, trigger_reason)
        """
        if not self.last_market_data:
            self.last_market_data = new_data
            return True, "initial_post"

        trigger_reason = None

        # Check for significant price changes
        for chain in self.target_chains.keys():
            if chain not in new_data or chain not in self.last_market_data:
                continue

            # Calculate immediate price change since last check
            price_change = abs(
                (new_data[chain]['current_price'] - self.last_market_data[chain]['current_price']) /
                self.last_market_data[chain]['current_price'] * 100
            )
            
            # Calculate immediate volume change since last check
            immediate_volume_change = abs(
                (new_data[chain]['volume'] - self.last_market_data[chain]['volume']) /
                self.last_market_data[chain]['volume'] * 100
            )

            logger.logger.debug(
                f"{chain} immediate changes - Price: {price_change:.2f}%, Volume: {immediate_volume_change:.2f}%"
            )

            # Check immediate price change
            if price_change >= self.config.PRICE_CHANGE_THRESHOLD:
                trigger_reason = f"price_change_{chain.lower()}"
                logger.logger.info(f"Significant price change detected for {chain}: {price_change:.2f}%")
                break
                
            # Check immediate volume change
            if immediate_volume_change >= self.config.VOLUME_CHANGE_THRESHOLD:
                trigger_reason = f"volume_change_{chain.lower()}"
                logger.logger.info(f"Significant immediate volume change detected for {chain}: {immediate_volume_change:.2f}%")
                break
                
            # Check rolling window volume trend
            historical_volume = self._get_historical_volume_data(chain)
            if historical_volume:
                volume_change_pct, trend = self._analyze_volume_trend(
                    new_data[chain]['volume'],
                    historical_volume
                )
                
                # Log the volume trend
                logger.logger.debug(
                    f"{chain} rolling window volume trend: {volume_change_pct:.2f}% ({trend})"
                )
                
                # Check if trend is significant enough to trigger
                if trend in ["significant_increase", "significant_decrease"]:
                    trigger_reason = f"volume_trend_{chain.lower()}_{trend}"
                    logger.logger.info(
                        f"Significant volume trend detected for {chain}: "
                        f"{volume_change_pct:.2f}% over {self.config.VOLUME_WINDOW_MINUTES} minutes"
                    )
                    break

        # Check if regular interval has passed
        time_since_last = (datetime.now() - self.last_check_time).total_seconds()
        if time_since_last >= self.config.BASE_INTERVAL:
            trigger_reason = trigger_reason or "regular_interval"
            if trigger_reason == "regular_interval":
                logger.logger.debug("Regular interval check triggered")

        should_post = trigger_reason is not None
        if should_post:
            self.last_market_data = new_data
            logger.logger.info(f"Update triggered by: {trigger_reason}")
        else:
            logger.logger.debug("No triggers activated, skipping update")

        return should_post, trigger_reason

    def _get_crypto_data(self) -> Optional[Dict[str, Any]]:
        """Fetch SOL and DOT data from CoinGecko with retries"""
        try:
            params = {
                **self.config.get_coingecko_params(),
                'ids': ','.join(self.target_chains.values()), 
                'sparkline': True 
            }
            
            data = self.coingecko.get_market_data(params)
            if not data:
                logger.logger.error("Failed to fetch market data from CoinGecko")
                return None
                
            formatted_data = {
                coin['symbol'].upper(): {
                    'current_price': coin['current_price'],
                    'volume': coin['total_volume'],
                    'price_change_percentage_24h': coin['price_change_percentage_24h'],
                    'sparkline': coin.get('sparkline_in_7d', {}).get('price', []),
                    'market_cap': coin['market_cap'],
                    'market_cap_rank': coin['market_cap_rank'],
                    'total_supply': coin.get('total_supply'),
                    'max_supply': coin.get('max_supply'),
                    'circulating_supply': coin.get('circulating_supply'),
                    'ath': coin.get('ath'),
                    'ath_change_percentage': coin.get('ath_change_percentage')
                } for coin in data
            }
            
            # Log API usage statistics
            stats = self.coingecko.get_request_stats()
            logger.logger.debug(
                f"CoinGecko API stats - Daily requests: {stats['daily_requests']}, "
                f"Failed: {stats['failed_requests']}, Cache size: {stats['cache_size']}"
            )
            
            # Store market data in database
            for chain, chain_data in formatted_data.items():
                self.config.db.store_market_data(chain, chain_data)
            
            missing_chains = set(self.target_chains.keys()) - set(formatted_data.keys())
            if missing_chains:
                logger.log_error("Crypto Data", f"Missing data for: {', '.join(missing_chains)}")
                return None
                
            logger.logger.info(f"Successfully fetched crypto data for {', '.join(formatted_data.keys())}")
            return formatted_data
                
        except Exception as e:
            logger.log_error("CoinGecko API", str(e))
            return None

    def _calculate_correlations(self, market_data: Dict[str, Any]) -> Dict[str, float]:
        """Calculate L1 correlations and patterns"""
        try:
            sol_data = market_data['SOL']
            dot_data = market_data['DOT']
            
            price_correlation = abs(
                sol_data['price_change_percentage_24h'] - 
                dot_data['price_change_percentage_24h']
            ) / max(abs(sol_data['price_change_percentage_24h']), 
                   abs(dot_data['price_change_percentage_24h']))
            
            volume_correlation = abs(
                (sol_data['volume'] - dot_data['volume']) / 
                max(sol_data['volume'], dot_data['volume'])
            )
            
            market_cap_ratio = sol_data['market_cap'] / dot_data['market_cap']
            
            correlations = {
                'price_correlation': 1 - price_correlation,
                'volume_correlation': 1 - volume_correlation,
                'market_cap_ratio': market_cap_ratio
            }
            
            # Store correlation data
            self.config.db.store_correlation_analysis(correlations)
            
            logger.logger.debug(
                f"Correlations calculated - Price: {correlations['price_correlation']:.2f}, "
                f"Volume: {correlations['volume_correlation']:.2f}, "
                f"MCap Ratio: {correlations['market_cap_ratio']:.2f}"
            )
            
            return correlations
            
        except Exception as e:
            logger.log_error("Correlation Calculation", str(e))
            return {
                'price_correlation': 0.0,
                'volume_correlation': 0.0,
                'market_cap_ratio': 1.0
            }

    def _analyze_market_sentiment(self, crypto_data: Dict[str, Any], trigger_type: str) -> Optional[str]:
        """Generate L1-specific market analysis with enhanced pattern detection"""
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                logger.logger.debug(f"Starting market sentiment analysis (attempt {retry_count + 1})")
                
                correlations = self._calculate_correlations(crypto_data)
                
                callback = self._get_spicy_callback({sym: data['current_price'] 
                                                   for sym, data in crypto_data.items()})
                
                chain_moods = {}
                meme_context = {}
                
                # Volume trend context to include in prompt
                volume_trends = {}
                
                for chain, data in crypto_data.items():
                    indicators = MoodIndicators(
                        price_change=data['price_change_percentage_24h'],
                        trading_volume=data['volume'],
                        volatility=abs(data['price_change_percentage_24h']) / 100,
                        social_sentiment=None,
                        funding_rates=None,
                        liquidation_volume=None
                    )
                    
                    mood = determine_advanced_mood(indicators)
                    chain_moods[chain] = {
                        'mood': mood.value,
                        'change': data['price_change_percentage_24h'],
                        'ath_distance': data['ath_change_percentage']
                    }
                    
                    # Store mood data
                    self.config.db.store_mood(chain, mood.value, indicators)
                    
                    meme_context[chain] = MemePhraseGenerator.generate_meme_phrase(
                        chain=chain.upper(),
                        mood=Mood(mood.value)
                    )
                    
                    # Get volume trend for additional context
                    historical_volume = self._get_historical_volume_data(chain)
                    if historical_volume:
                        volume_change_pct, trend = self._analyze_volume_trend(
                            data['volume'],
                            historical_volume
                        )
                        volume_trends[chain] = {
                            'change_pct': volume_change_pct,
                            'trend': trend
                        }

                # Get historical context from database
                historical_context = {}
                for chain in self.target_chains.keys():
                    stats = self.config.db.get_chain_stats(chain, hours=24)
                    if stats:
                        historical_context[chain] = f"24h Avg: ${stats['avg_price']:,.2f}, "
                        historical_context[chain] += f"High: ${stats['max_price']:,.2f}, "
                        historical_context[chain] += f"Low: ${stats['min_price']:,.2f}"
                
                # Check if this is a volume trend trigger
                volume_context = ""
                if "volume_trend" in trigger_type:
                    triggered_chain = trigger_type.split('_')[2].upper()
                    trend_type = trigger_type.split('_')[3]
                    if triggered_chain in volume_trends:
                        change = volume_trends[triggered_chain]['change_pct']
                        direction = "increase" if change > 0 else "decrease"
                        volume_context = f"\nVolume Analysis:\n{triggered_chain} showing {abs(change):.1f}% {direction} in volume over last hour. This is a significant {trend_type}."

                prompt = f"""Write a witty Layer 1 blockchain market analysis as a single paragraph. Market data:
                
                Chain Performance:
                - SOL: {chain_moods['SOL']['change']:.1f}% ({chain_moods['SOL']['mood']})
                - DOT: {chain_moods['DOT']['change']:.1f}% ({chain_moods['DOT']['mood']})
                
                Historical Context:
                - SOL: {historical_context.get('SOL', 'No historical data')}
                - DOT: {historical_context.get('DOT', 'No historical data')}
                
                Key Metrics:
                - Price correlation: {correlations['price_correlation']:.2f}
                - Volume correlation: {correlations['volume_correlation']:.2f}
                - Market cap ratio: {correlations['market_cap_ratio']:.2f}
                
                Chain-specific context:
                - SOL meme: {meme_context['SOL']}
                - DOT meme: {meme_context['DOT']}
                
                ATH Distance:
                - SOL: {chain_moods['SOL']['ath_distance']:.1f}%
                - DOT: {chain_moods['DOT']['ath_distance']:.1f}%
                
                Volume Trends:
                - SOL: {volume_trends.get('SOL', {}).get('change_pct', 0):.1f}% over last hour ({volume_trends.get('SOL', {}).get('trend', 'stable')})
                - DOT: {volume_trends.get('DOT', {}).get('change_pct', 0):.1f}% over last hour ({volume_trends.get('DOT', {}).get('trend', 'stable')})
                {volume_context}
                
                Trigger Type: {trigger_type}
                
                Past Context: {callback if callback else 'None'}
                
                Note: Keep the analysis fresh and varied. Avoid repetitive phrases."""
                
                logger.logger.debug("Sending analysis request to Claude")
                response = self.claude_client.messages.create(
                    model=self.config.CLAUDE_MODEL,
                    max_tokens=1000,
                    messages=[{"role": "user", "content": prompt}]
                )
                
                analysis = response.content[0].text
                logger.logger.debug("Received analysis from Claude")
                
                # Store prediction data
                prediction_data = {
                    'analysis': analysis,
                    'sentiment': {chain: mood['mood'] for chain, mood in chain_moods.items()},
                    **{f"{sym.upper()}_price": data['current_price'] for sym, data in crypto_data.items()}
                }
                self._track_prediction(prediction_data, list(crypto_data.keys()))
                
                formatted_tweet = self._format_tweet_analysis(analysis, crypto_data)
                
                # Check for content similarity
                if self.config.db.check_content_similarity(formatted_tweet):
                    logger.logger.info("Similar content detected, retrying analysis")
                    retry_count += 1
                    continue
                
                # Store the content if it's unique
                self.config.db.store_posted_content(
                    content=formatted_tweet,
                    sentiment=chain_moods,
                    trigger_type=trigger_type,
                    price_data={chain: {'price': data['current_price'], 
                                      'volume': data['volume']} 
                              for chain, data in crypto_data.items()},
                    meme_phrases=meme_context
                )
                return formatted_tweet
                
            except Exception as e:
                retry_count += 1
                wait_time = retry_count * 10
                logger.logger.error(f"Analysis error details: {str(e)}", exc_info=True)
                logger.logger.warning(f"Analysis error, attempt {retry_count}, waiting {wait_time}s...")
                time.sleep(wait_time)
                continue
        
        logger.log_error("Market Analysis", "Maximum retries reached")
        return None

    def _track_prediction(self, prediction: Dict[str, Any], relevant_chains: List[str]) -> None:
        """Track predictions for future spicy callbacks"""
        MAX_PREDICTIONS = 20  
        current_prices = {chain: prediction[f'{chain.upper()}_price'] for chain in relevant_chains}
        
        self.past_predictions.append({
            'timestamp': datetime.now(),
            'prediction': prediction['analysis'],
            'prices': current_prices,
            'sentiment': prediction['sentiment'],
            'outcome': None
        })
        
        self.past_predictions = [p for p in self.past_predictions 
                               if (datetime.now() - p['timestamp']).total_seconds() < 86400]     
        
    def _validate_past_prediction(self, prediction: Dict[str, Any], current_prices: Dict[str, float]) -> str:
        """Check if a past prediction was hilariously wrong"""
        sentiment_map = {
            'bullish': 1,
            'bearish': -1,
            'neutral': 0
        }
        
        wrong_chains = []
        for chain, old_price in prediction['prices'].items():
            if chain in current_prices:
                price_change = ((current_prices[chain] - old_price) / old_price) * 100
                chain_sentiment = sentiment_map.get(prediction['sentiment'][chain.upper()], 0)
                
                if (chain_sentiment * price_change) < -2:
                    wrong_chains.append(chain)
        
        return 'wrong' if wrong_chains else 'right'

    def _get_spicy_callback(self, current_prices: Dict[str, float]) -> Optional[str]:
        """Generate witty callbacks to past terrible predictions"""
        recent_predictions = [p for p in self.past_predictions 
                            if p['timestamp'] > (datetime.now() - timedelta(hours=24))]
        
        if not recent_predictions:
            return None
            
        for pred in recent_predictions:
            if pred['outcome'] is None:
                pred['outcome'] = self._validate_past_prediction(pred, current_prices)
                
        wrong_predictions = [p for p in recent_predictions if p['outcome'] == 'wrong']
        if wrong_predictions:
            worst_pred = wrong_predictions[-1]
            time_ago = int((datetime.now() - worst_pred['timestamp']).total_seconds() / 3600)
            
            callbacks = [
                f"(Unlike my galaxy-brain take {time_ago}h ago about {worst_pred['prediction']}... this time I'm sure!)",
                f"(Looks like my {time_ago}h old prediction about {worst_pred['prediction']} aged like milk. But trust me bro!)",
                f"(That awkward moment when your {time_ago}h old prediction of {worst_pred['prediction']} was completely wrong... but this one's different!)"
            ]
            return callbacks[hash(str(datetime.now())) % len(callbacks)]
            
        return None

    def _format_tweet_analysis(self, analysis: str, crypto_data: Dict[str, Any]) -> str:
        """Format analysis for Twitter with L1-specific hashtags"""
        hashtags = "#SOL #DOT #Layer1 #L1Analysis"
        tweet = f"{analysis}\n\n{hashtags}"
        max_length = self.config.TWEET_CONSTRAINTS['HARD_STOP_LENGTH'] - 20
        if len(tweet) > max_length:
            analysis = analysis[:max_length-len(hashtags)-23] + "..."
            tweet = f"{analysis}\n\n{hashtags}"
        
        return tweet

    def _run_analysis_cycle(self) -> None:
        """Run analysis and posting cycle"""
        try:
            market_data = self._get_crypto_data()
            if not market_data:
                logger.logger.error("Failed to fetch market data")
                return
                
            should_post, trigger_type = self._should_post_update(market_data)
            
            if should_post:
                logger.logger.info(f"Starting analysis cycle - Trigger: {trigger_type}")
                analysis = self._analyze_market_sentiment(market_data, trigger_type)
                if not analysis:
                    logger.logger.error("Failed to generate analysis")
                    return
                    
                last_posts = self._get_last_posts()
                if not self._is_duplicate_analysis(analysis, last_posts):
                    if self._post_analysis(analysis):
                        logger.logger.info(f"Successfully posted analysis - Trigger: {trigger_type}")
                    else:
                        logger.logger.error("Failed to post analysis")
                else:
                    logger.logger.info("Skipping duplicate analysis")
            else:
                logger.logger.debug("No significant changes detected, skipping post")
                
        except Exception as e:
            logger.log_error("Analysis Cycle", str(e))

    def _get_last_posts(self) -> List[str]:
        """Get last 10 posts to check for duplicates"""
        try:
            self.browser.driver.get(f'https://twitter.com/{self.config.TWITTER_USERNAME}')
            time.sleep(3)
            
            posts = WebDriverWait(self.browser.driver, 10).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, '[data-testid="tweetText"]'))
            )
            
            return [post.text for post in posts[:10]]
        except Exception as e:
            logger.log_error("Get Last Posts", str(e))
            return []

    def _is_duplicate_analysis(self, new_tweet: str, last_posts: List[str]) -> bool:
        """Check if analysis is a duplicate"""
        try:
            # Check database first
            if self.config.db.check_content_similarity(new_tweet):
                logger.logger.info("Duplicate detected in database")
                return True
                
            # Then check recent posts
            for post in last_posts:
                if post.strip() == new_tweet.strip():
                    logger.logger.info("Duplicate detected in recent posts")
                    return True
                    
            return False
        except Exception as e:
            logger.log_error("Duplicate Check", str(e))
            return False

    def _login_to_twitter(self) -> bool:
        """Log into Twitter with enhanced verification"""
        try:
            logger.logger.info("Starting Twitter login")
            self.browser.driver.set_page_load_timeout(45)
            self.browser.driver.get('https://twitter.com/login')
            time.sleep(5)

            username_field = WebDriverWait(self.browser.driver, 20).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "input[autocomplete='username']"))
            )
            username_field.click()
            time.sleep(1)
            username_field.send_keys(self.config.TWITTER_USERNAME)
            time.sleep(2)

            next_button = WebDriverWait(self.browser.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//span[text()='Next']"))
            )
            next_button.click()
            time.sleep(3)

            password_field = WebDriverWait(self.browser.driver, 20).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "input[type='password']"))
            )
            password_field.click()
            time.sleep(1)
            password_field.send_keys(self.config.TWITTER_PASSWORD)
            time.sleep(2)

            login_button = WebDriverWait(self.browser.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//span[text()='Log in']"))
            )
            login_button.click()
            time.sleep(10) 

            return self._verify_login()

        except Exception as e:
            logger.log_error("Twitter Login", str(e))
            return False

    def _verify_login(self) -> bool:
        """Verify Twitter login success"""
        try:
            verification_methods = [
                lambda: WebDriverWait(self.browser.driver, 30).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="SideNav_NewTweet_Button"]'))
                ),
                lambda: WebDriverWait(self.browser.driver, 30).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="AppTabBar_Profile_Link"]'))
                ),
                lambda: any(path in self.browser.driver.current_url 
                          for path in ['home', 'twitter.com/home'])
            ]
            
            for method in verification_methods:
                try:
                    if method():
                        return True
                except:
                    continue
            
            return False
            
        except Exception as e:
            logger.log_error("Login Verification", str(e))
            return False

    def _post_analysis(self, tweet_text: str) -> bool:
        """Post analysis to Twitter with robust button handling"""
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                self.browser.driver.get('https://twitter.com/compose/tweet')
                time.sleep(3)
                
                text_area = WebDriverWait(self.browser.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="tweetTextarea_0"]'))
                )
                text_area.click()
                time.sleep(1)
                
                text_parts = tweet_text.split('#')
                text_area.send_keys(text_parts[0])
                time.sleep(1)
                for part in text_parts[1:]:
                    text_area.send_keys(f'#{part}')
                    time.sleep(0.5)
                
                time.sleep(2)

                post_button = None
                button_locators = [
                    (By.CSS_SELECTOR, '[data-testid="tweetButton"]'),
                    (By.XPATH, "//div[@role='button'][contains(., 'Post')]"),
                    (By.XPATH, "//span[text()='Post']")
                ]

                for locator in button_locators:
                    try:
                        post_button = WebDriverWait(self.browser.driver, 5).until(
                            EC.element_to_be_clickable(locator)
                        )
                        if post_button:
                            break
                    except:
                        continue

                if post_button:
                    self.browser.driver.execute_script("arguments[0].scrollIntoView(true);", post_button)
                    time.sleep(1)
                    self.browser.driver.execute_script("arguments[0].click();", post_button)
                    time.sleep(5)
                    logger.logger.info("Tweet posted successfully")
                    return True
                else:
                    logger.logger.error("Could not find post button")
                    retry_count += 1
                    time.sleep(2)
                    
            except Exception as e:
                logger.logger.error(f"Tweet posting error, attempt {retry_count + 1}: {str(e)}")
                retry_count += 1
                wait_time = retry_count * 10
                logger.logger.warning(f"Waiting {wait_time}s before retry...")
                time.sleep(wait_time)
                continue
        
        logger.log_error("Tweet Creation", "Maximum retries reached")
        return False

    def _cleanup(self) -> None:
        """Cleanup resources"""
        try:
            if self.browser:
                logger.logger.info("Closing browser...")
                try:
                    self.browser.close_browser()
                    time.sleep(1)
                except Exception as e:
                    logger.logger.warning(f"Error during browser close: {str(e)}")
                    
            if self.config:
                self.config.cleanup()
                
            logger.log_shutdown()
        except Exception as e:
            logger.log_error("Cleanup", str(e))

if __name__ == "__main__":
    bot = Layer1AnalysisBot()
    bot.start()            
